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

    def run_full_pipeline(self, regions: list[dict], on_progress=None):
        self._stopped = False
        self._results = [{"region": r["region"], "safe_filename": r["safe_filename"],
                          "gif": "pending", "mp3": "pending", "mp4": "pending", "error": ""}
                         for r in regions]

        logger.info(f"=== Pipeline start: {len(regions)} regions ===")

        self._process_gif(regions, on_progress)
        if self._stopped:
            self._write_report()
            return

        self._process_mp3(regions, on_progress)
        if self._stopped:
            self._write_report()
            return

        self._process_mp4(regions, on_progress)
        self._write_report()
        logger.info("=== Pipeline done ===")

    def _find_result(self, safe_filename: str) -> dict:
        for r in self._results:
            if r["safe_filename"] == safe_filename:
                return r
        return {}

    def _process_gif(self, regions: list[dict], on_progress=None):
        self._gif_total = len(regions)
        self._gif_done = 0
        logger.info(f"GIF: {self._gif_total} tasks ({GIF_WORKERS} concurrent)")

        with ThreadPoolExecutor(max_workers=GIF_WORKERS) as ex:
            futures = {}
            for r in regions:
                gif_path = os.path.join(self._output_gif_dir, f"{r['safe_filename']}.gif")
                if self._existing_file_policy == "skip" and os.path.isfile(gif_path) and os.path.getsize(gif_path) > 0:
                    self._find_result(r["safe_filename"])["gif"] = "ok"
                    self._gif_done += 1
                    continue
                futures[ex.submit(self._render_one_gif, r)] = r

            for future in as_completed(futures):
                if self._stopped:
                    break
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"GIF future: {e}")
                self._gif_done += 1
                if on_progress:
                    on_progress("gif", {"current": self._gif_done, "total": self._gif_total})

    def _render_one_gif(self, r: dict):
        gif_path = os.path.join(self._output_gif_dir, f"{r['safe_filename']}.gif")
        result = self._find_result(r["safe_filename"])
        try:
            png_dir = self._cache_mgr.ensure_render_dir(r["safe_filename"])
            ok = self._gif_service.render_one(
                r["region"], r["safe_filename"], self._gif_text_layer, gif_path, png_dir
            )
            result["gif"] = "ok" if ok else "fail"
            if not ok:
                result["error"] = "GIF render failed"
        except Exception as e:
            result["gif"] = "fail"
            result["error"] = str(e)

    def _process_mp3(self, regions: list[dict], on_progress=None):
        self._mp3_total = len(regions)
        self._mp3_done = 0
        if self._sapi_engine is None:
            for r in self._results:
                r["mp3"] = "skip"
            return

        logger.info(f"MP3: {self._mp3_total} tasks ({MP3_WORKERS} concurrent)")
        with ThreadPoolExecutor(max_workers=MP3_WORKERS) as ex:
            futures = {}
            for r in regions:
                mp3_path = os.path.join(self._output_gif_dir, f"{r['safe_filename']}.mp3")
                if self._existing_file_policy == "skip" and os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0:
                    self._find_result(r["safe_filename"])["mp3"] = "ok"
                    self._mp3_done += 1
                    continue
                futures[ex.submit(self._synthesize_one, r)] = r

            for future in as_completed(futures):
                if self._stopped:
                    break
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"MP3 future: {e}")
                self._mp3_done += 1
                if on_progress:
                    on_progress("mp3", {"current": self._mp3_done, "total": self._mp3_total})

    def _synthesize_one(self, r: dict):
        mp3_path = os.path.join(self._output_gif_dir, f"{r['safe_filename']}.mp3")
        result = self._find_result(r["safe_filename"])
        for attempt in range(MAX_RETRIES + 1):
            try:
                ok = self._sapi_engine.synthesize(r["region"], "", mp3_path)
                if ok:
                    result["mp3"] = "ok"
                    return
            except Exception:
                pass
            if attempt < MAX_RETRIES:
                logger.warning(f"MP3 retry {attempt+1}: {r['region']}")
        result["mp3"] = "fail"
        result["error"] = result.get("error", "") + "; MP3 failed"

    def _process_mp4(self, regions: list[dict], on_progress=None):
        ready = [r for r in regions
                 if self._find_result(r["safe_filename"]).get("gif") == "ok"
                 and self._find_result(r["safe_filename"]).get("mp3") == "ok"]
        self._mp4_total = len(ready)
        self._mp4_done = 0
        if not ready:
            return
        if not os.path.isfile(self._source_video_path):
            logger.error(f"Source video missing: {self._source_video_path}")
            return

        logger.info(f"MP4: {self._mp4_total} tasks ({MP4_WORKERS} concurrent)")
        with ThreadPoolExecutor(max_workers=MP4_WORKERS) as ex:
            futures = {}
            for r in ready:
                mp4_path = os.path.join(self._output_video_dir, f"{r['safe_filename']}.mp4")
                if self._existing_file_policy == "skip" and os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0:
                    self._find_result(r["safe_filename"])["mp4"] = "ok"
                    self._mp4_done += 1
                    continue
                futures[ex.submit(self._compose_one, r)] = r

            for future in as_completed(futures):
                if self._stopped:
                    break
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"MP4 future: {e}")
                self._mp4_done += 1
                if on_progress:
                    on_progress("mp4", {"current": self._mp4_done, "total": self._mp4_total})

    def _compose_one(self, r: dict):
        mp4_path = os.path.join(self._output_video_dir, f"{r['safe_filename']}.mp4")
        gif_path = os.path.join(self._output_gif_dir, f"{r['safe_filename']}.gif")
        mp3_path = os.path.join(self._output_gif_dir, f"{r['safe_filename']}.mp3")
        result = self._find_result(r["safe_filename"])

        for attempt in range(MAX_RETRIES + 1):
            try:
                adjusted_mp3 = os.path.join(self._cache_mgr._audio_temp_dir,
                                            f"{r['safe_filename']}_adjusted.mp3")
                try:
                    adjusted_mp3 = self._composer.adjust_region_mp3_volume(
                        self._source_video_path, mp3_path, adjusted_mp3)
                except Exception:
                    adjusted_mp3 = mp3_path

                png_dir = self._cache_mgr.get_render_dir(r["safe_filename"])
                logger.info(f"[COMPOSE] region={r['region']} scale={self._overlay_scale} x={self._overlay_x} y={self._overlay_y}")
                ok = self._composer.compose_final_video(
                    self._source_video_path, gif_path, adjusted_mp3, mp4_path,
                    png_sequence_dir=png_dir,
                    gif_durations=self._gif_durations,
                    overlay_x=self._overlay_x,
                    overlay_y=self._overlay_y,
                    overlay_scale=self._overlay_scale,
                )
                if ok and os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0:
                    result["mp4"] = "ok"
                    return
            except Exception as e:
                logger.error(f"MP4 error [{r['region']}]: {e}")
            if attempt < MAX_RETRIES:
                logger.warning(f"MP4 retry {attempt+1}: {r['region']}")
        result["mp4"] = "fail"
        result["error"] = result.get("error", "") + "; MP4 failed"

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
