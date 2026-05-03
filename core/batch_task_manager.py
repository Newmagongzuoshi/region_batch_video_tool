import os
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.gif_render_service import GifRenderService
from core.gif_frame_decoder import GifFrameDecoder
from core.tts_windows_sapi import WindowsSapiTTSEngine
from core.video_composer import VideoComposer
from core.ffmpeg_service import FFmpegService
from core.cache_manager import CacheManager
from models.text_layer_model import TextLayerModel
from utils.logger import get_logger

logger = get_logger()

PIPELINE_WORKERS = 6
MAX_RETRIES = 2


class BatchTaskManager:
    """Pipeline-parallel batch processor. GIF+MP3 are intermediate temp files.
    Only MP4 is output to the user's directory.
    """

    def __init__(self):
        self._gif_service: GifRenderService | None = None
        self._ffmpeg = FFmpegService()
        self._composer = VideoComposer(self._ffmpeg)
        self._cache_mgr = CacheManager()
        self._sapi_engine: WindowsSapiTTSEngine | None = None

        self._stopped = False

        # Results tracking (MP4 only)
        self._results: list[dict] = []

        self._gif_text_layer: TextLayerModel | None = None
        self._output_video_dir: str = ""
        self._report_dir: str = ""
        self._source_video_path: str = ""
        self._existing_file_policy: str = "skip"
        self._overlay_x: int = 0
        self._overlay_y: int = 0
        self._overlay_scale: float = 1.0
        self._gif_durations: list[int] = []

        # Temp dirs for intermediate files
        self._gif_temp_dir: str = ""
        self._mp3_temp_dir: str = ""

    def initialize(
        self, gif_decoder, text_layer, source_video_path,
        output_video_dir, report_dir,
        existing_file_policy="skip", sapi_engine=None,
        overlay_x=0, overlay_y=0, overlay_scale=1.0,
    ):
        self._gif_service = GifRenderService(gif_decoder)
        self._gif_text_layer = text_layer
        self._source_video_path = source_video_path
        self._output_video_dir = output_video_dir
        self._report_dir = report_dir
        self._existing_file_policy = existing_file_policy
        self._sapi_engine = sapi_engine
        self._overlay_x = overlay_x
        self._overlay_y = overlay_y
        self._overlay_scale = overlay_scale
        self._gif_durations = gif_decoder.get_durations()
        self._stopped = False
        self._results = []

        # Intermediate temp dirs (cleaned after generation)
        self._gif_temp_dir = os.path.join(self._cache_mgr._video_temp_dir, "gif_temp")
        self._mp3_temp_dir = os.path.join(self._cache_mgr._audio_temp_dir, "mp3_temp")
        os.makedirs(self._gif_temp_dir, exist_ok=True)
        os.makedirs(self._mp3_temp_dir, exist_ok=True)
        os.makedirs(self._output_video_dir, exist_ok=True)
        os.makedirs(self._report_dir, exist_ok=True)

        # Pre-cache video analysis
        self._video_info = self._ffmpeg.probe_video(source_video_path)
        self._video_has_audio = self._video_info.has_audio
        self._video_duration = self._video_info.duration
        logger.info(f"[BATCH] video: {self._video_info.width}x{self._video_info.height} "
                    f"dur={self._video_duration:.1f}s audio={self._video_has_audio}")

        try:
            self._source_loudness = self._composer.analyze_loudness(source_video_path, 3.0)
        except Exception:
            self._source_loudness = {"mean_volume_db": -20.0}

    def run_full_pipeline(self, regions: list[dict], on_progress=None, on_mp4_done=None):
        self._stopped = False
        self._results = [{"region": r["region"], "safe_filename": r["safe_filename"],
                          "mp4": "pending", "error": ""}
                         for r in regions]

        logger.info(f"=== Pipeline: {len(regions)} regions, {PIPELINE_WORKERS} parallel ===")

        total = len(regions)
        completed = 0

        with ThreadPoolExecutor(max_workers=PIPELINE_WORKERS) as ex:
            futures = {ex.submit(self._process_one_region, r): r for r in regions}
            for future in as_completed(futures):
                if self._stopped:
                    break
                r = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Pipeline error [{r['region']}]: {e}")
                completed += 1
                status = self._find_result(r["safe_filename"]).get("mp4", "pending")
                if on_mp4_done:
                    on_mp4_done(r["region"], status)
                if on_progress:
                    on_progress("mp4", {"current": completed, "total": total})

        self._write_report()
        logger.info("=== Pipeline done ===")

    def _process_one_region(self, r: dict):
        region = r["region"]
        safe = r["safe_filename"]

        # --- Step 1: Render GIF (temp) ---
        gif_path = os.path.join(self._gif_temp_dir, f"{safe}.gif")
        if not (self._existing_file_policy == "skip" and os.path.isfile(gif_path) and os.path.getsize(gif_path) > 0):
            try:
                ok = self._gif_service.render_one(
                    region, safe, self._gif_text_layer, gif_path, "", skip_png=True)
                if not ok:
                    self._find_result(safe)["mp4"] = "fail"
                    self._find_result(safe)["error"] = "GIF render failed"
                    return
            except Exception as e:
                self._find_result(safe)["mp4"] = "fail"
                self._find_result(safe)["error"] = str(e)
                return

        if self._stopped:
            return

        # --- Step 2: Synthesize MP3 (temp) ---
        mp3_path = os.path.join(self._mp3_temp_dir, f"{safe}.mp3")
        if self._sapi_engine and not (
            self._existing_file_policy == "skip" and os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0
        ):
            ok = False
            for attempt in range(MAX_RETRIES + 1):
                try:
                    ok = self._sapi_engine.synthesize(region, "", mp3_path)
                    if ok:
                        break
                except Exception:
                    pass
                if attempt < MAX_RETRIES:
                    logger.warning(f"MP3 retry {attempt+1}: {region}")
            if not ok:
                self._find_result(safe)["mp4"] = "fail"
                self._find_result(safe)["error"] = "TTS failed"
                return

        if self._stopped:
            return

        # --- Step 3: Compose MP4 (final output) ---
        mp4_path = os.path.join(self._output_video_dir, f"{safe}.mp4")
        if self._existing_file_policy == "skip" and os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0:
            self._find_result(safe)["mp4"] = "ok"
            return

        for attempt in range(MAX_RETRIES + 1):
            try:
                adjusted_mp3 = os.path.join(self._cache_mgr._audio_temp_dir, f"{safe}_adjusted.mp3")
                try:
                    self._composer.adjust_region_mp3_volume_cached(
                        self._source_loudness, mp3_path, adjusted_mp3)
                except Exception:
                    adjusted_mp3 = mp3_path

                ok = self._composer.compose_final_video_cached(
                    self._source_video_path, gif_path, adjusted_mp3, mp4_path,
                    video_info=self._video_info,
                    gif_durations=self._gif_durations,
                    overlay_x=self._overlay_x,
                    overlay_y=self._overlay_y,
                    overlay_scale=self._overlay_scale,
                )
                if ok and os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0:
                    self._find_result(safe)["mp4"] = "ok"
                    # Clean up intermediate files to prevent disk overflow
                    for tmp in [gif_path, mp3_path, adjusted_mp3]:
                        try:
                            if os.path.isfile(tmp):
                                os.remove(tmp)
                        except Exception:
                            pass
                    return
            except Exception as e:
                logger.error(f"MP4 error [{region}]: {e}")
            if attempt < MAX_RETRIES:
                logger.warning(f"MP4 retry {attempt+1}: {region}")

        self._find_result(safe)["mp4"] = "fail"
        self._find_result(safe)["error"] = "FFmpeg failed"

    def _find_result(self, safe_filename: str) -> dict:
        for r in self._results:
            if r["safe_filename"] == safe_filename:
                return r
        return {}

    def _write_report(self):
        success = [r for r in self._results if r.get("mp4") == "ok"]
        failed = [r for r in self._results if r not in success]

        report_path = os.path.join(self._output_video_dir, "AA视频生成报告.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总计: {len(self._results)}  成功: {len(success)}  失败: {len(failed)}\n")
            f.write("=" * 40 + "\n\n")
            f.write("【成功】\n")
            for r in success:
                f.write(f"  OK  {r['region']}.mp4\n")
            if failed:
                f.write("\n【失败】\n")
                for r in failed:
                    f.write(f"  FAIL  {r['region']}.mp4  ({r.get('error', '')})\n")
            f.write(f"\n" + "=" * 40 + "\n")

        logger.info(f"Report: {len(success)} ok, {len(failed)} failed -> {report_path}")

    def stop(self):
        self._stopped = True

    def is_stopped(self):
        return self._stopped
