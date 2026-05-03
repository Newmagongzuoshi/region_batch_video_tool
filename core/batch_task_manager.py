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

GIF_WORKERS = 4
MP3_WORKERS = 3
MP4_WORKERS = 2
MAX_RETRIES = 2


class BatchTaskManager:
    """Simple batch processor. Generates GIF→MP3→MP4 for each region.

    No SQLite, no complex task tracking. Results written to a report file.
    """

    def __init__(self):
        self._gif_service: GifRenderService | None = None
        self._ffmpeg = FFmpegService()
        self._composer = VideoComposer(self._ffmpeg)
        self._cache_mgr = CacheManager()
        self._sapi_engine: WindowsSapiTTSEngine | None = None

        self._stopped = False

        # Results tracking (in-memory)
        self._results: list[dict] = []
        self._gif_total = 0
        self._gif_done = 0
        self._mp3_total = 0
        self._mp3_done = 0
        self._mp4_total = 0
        self._mp4_done = 0

        self._gif_text_layer: TextLayerModel | None = None
        self._output_gif_dir: str = ""
        self._output_video_dir: str = ""
        self._report_dir: str = ""
        self._source_video_path: str = ""
        self._existing_file_policy: str = "skip"
        self._overlay_x: int = 0
        self._overlay_y: int = 0
        self._overlay_scale: float = 1.0
        self._gif_durations: list[int] = []

    def initialize(
        self, gif_decoder, text_layer, source_video_path,
        output_gif_dir, output_video_dir, report_dir,
        existing_file_policy="skip", sapi_engine=None,
        overlay_x=0, overlay_y=0, overlay_scale=1.0,
    ):
        self._gif_service = GifRenderService(gif_decoder)
        self._gif_text_layer = text_layer
        self._source_video_path = source_video_path
        self._output_gif_dir = output_gif_dir
        self._output_video_dir = output_video_dir
        self._report_dir = report_dir
        self._existing_file_policy = existing_file_policy
        self._sapi_engine = sapi_engine
        self._overlay_x = overlay_x
        self._overlay_y = overlay_y
        self._overlay_scale = overlay_scale
        logger.info(f"[BATCH] initialize: overlay_x={overlay_x} overlay_y={overlay_y} overlay_scale={overlay_scale}")
        self._gif_durations = gif_decoder.get_durations()
        self._stopped = False
        self._results = []
        os.makedirs(self._output_gif_dir, exist_ok=True)
        os.makedirs(self._output_video_dir, exist_ok=True)
        os.makedirs(self._report_dir, exist_ok=True)

        # Pre-cache video analysis (do once, not per region)
        self._video_info = self._ffmpeg.probe_video(source_video_path)
        self._video_has_audio = self._video_info.has_audio
        self._video_duration = self._video_info.duration
        logger.info(f"[BATCH] video cached: {self._video_info.width}x{self._video_info.height} "
                    f"dur={self._video_duration:.1f}s audio={self._video_has_audio}")

        # Pre-cache source loudness for MP3 volume matching
        try:
            self._source_loudness = self._composer.analyze_loudness(source_video_path, 3.0)
        except Exception:
            self._source_loudness = {"mean_volume_db": -20.0}

    def run_full_pipeline(self, regions: list[dict], on_progress=None, on_mp4_done=None):
        self._stopped = False
        self._results = [{"region": r["region"], "safe_filename": r["safe_filename"],
                          "gif": "pending", "mp3": "pending", "mp4": "pending", "error": ""}
                         for r in regions]

        logger.info(f"=== Pipeline start: {len(regions)} regions (pipeline-parallel) ===")

        # Pipeline parallelism: each region goes GIF→MP3→MP4 independently.
        # 6 concurrent pipelines so multiple MP4 encodings run simultaneously.
        PIPELINE_WORKERS = 6
        total = len(regions)
        completed = 0

        with ThreadPoolExecutor(max_workers=PIPELINE_WORKERS) as ex:
            futures = {
                ex.submit(self._process_one_region, r): r
                for r in regions
            }
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
        """Process GIF → MP3 → MP4 for a single region end-to-end."""
        region = r["region"]
        safe = r["safe_filename"]

        # --- GIF ---
        gif_path = os.path.join(self._output_gif_dir, f"{safe}.gif")
        if self._existing_file_policy == "skip" and os.path.isfile(gif_path) and os.path.getsize(gif_path) > 0:
            self._find_result(safe)["gif"] = "ok"
        else:
            try:
                ok = self._gif_service.render_one(
                    region, safe, self._gif_text_layer, gif_path, "",
                    skip_png=True,
                )
                self._find_result(safe)["gif"] = "ok" if ok else "fail"
            except Exception as e:
                self._find_result(safe)["gif"] = "fail"
                self._find_result(safe)["error"] = str(e)
                return

        if self._stopped:
            return

        # --- MP3 ---
        mp3_path = os.path.join(self._output_gif_dir, f"{safe}.mp3")
        if self._existing_file_policy == "skip" and os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0:
            self._find_result(safe)["mp3"] = "ok"
        elif self._sapi_engine:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    ok = self._sapi_engine.synthesize(region, "", mp3_path)
                    if ok:
                        self._find_result(safe)["mp3"] = "ok"
                        break
                except Exception:
                    pass
                if attempt == MAX_RETRIES:
                    self._find_result(safe)["mp3"] = "fail"
        else:
            self._find_result(safe)["mp3"] = "skip"

        if self._stopped:
            return

        # --- MP4 ---
        if self._find_result(safe).get("gif") != "ok" or self._find_result(safe).get("mp3") != "ok":
            self._find_result(safe)["mp4"] = "fail"
            return

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
                    return
            except Exception as e:
                logger.error(f"MP4 error [{region}]: {e}")
            if attempt < MAX_RETRIES:
                logger.warning(f"MP4 retry {attempt+1}: {region}")
        self._find_result(safe)["mp4"] = "fail"

    def _find_result(self, safe_filename: str) -> dict:
        for r in self._results:
            if r["safe_filename"] == safe_filename:
                return r
        return {}

    def _write_report(self):
        success = [r for r in self._results
                   if r.get("gif") == "ok" and r.get("mp3") == "ok" and r.get("mp4") == "ok"]
        failed = [r for r in self._results if r not in success]
        skipped = [r for r in self._results
                   if r.get("gif") == "skip" and r.get("mp3") == "skip" and r.get("mp4") == "skip"]

        report = {
            "time": datetime.now().isoformat(),
            "total": len(self._results),
            "success": len(success),
            "failed": len(failed),
            "skipped": len(skipped),
            "success_list": [r["region"] for r in success],
            "failed_list": [{"region": r["region"], "error": r.get("error", "")} for r in failed],
            "skipped_list": [r["region"] for r in skipped],
        }

        report_path = os.path.join(self._report_dir, "report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # Also write simple text files
        with open(os.path.join(self._report_dir, "成功.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(report["success_list"]))

        with open(os.path.join(self._report_dir, "失败.txt"), "w", encoding="utf-8") as f:
            for item in report["failed_list"]:
                f.write(f"{item['region']}: {item['error']}\n")

        logger.info(f"Report: {report['success']} ok, {report['failed']} failed, {report['skipped']} skipped")

    def stop(self):
        self._stopped = True

    def is_stopped(self):
        return self._stopped
