import os
import time
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

# Adaptive concurrency based on encoder type and CPU cores.
CPU_COUNT = os.cpu_count() or 4
MAX_RETRIES = 2


def _get_worker_count(encoder_codec: str) -> int:
    """Adaptive worker count: GPU encoders have limited concurrent sessions."""
    if "nvenc" in encoder_codec:
        # NVIDIA NVENC: 2-3 concurrent sessions on consumer GPUs
        return min(CPU_COUNT, 4)
    elif "amf" in encoder_codec:
        return min(CPU_COUNT, 4)
    elif "qsv" in encoder_codec:
        return min(CPU_COUNT, 6)
    else:
        # CPU x264: oversubscribe but don't thrash
        if CPU_COUNT <= 4:
            return 8
        elif CPU_COUNT <= 8:
            return 16
        else:
            return min(CPU_COUNT * 2, 24)


class BatchTaskManager:
    """High-performance batch processor with video pre-split optimization.

    - Pre-splits source video into head (GIF duration) + tail segments ONCE
    - Each region only encodes the short head segment, then concat with tail
    - Massively reduces re-encoding time for long videos with short GIF overlays
    """

    def __init__(self):
        self._gif_service: GifRenderService | None = None
        self._ffmpeg = FFmpegService()
        self._composer = VideoComposer(self._ffmpeg)
        self._cache_mgr = CacheManager()
        self._sapi_engine: WindowsSapiTTSEngine | None = None

        self._stopped = False
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

        self._gif_temp_dir = os.path.join(self._cache_mgr._video_temp_dir, "gif_temp")
        self._mp3_temp_dir = os.path.join(self._cache_mgr._audio_temp_dir, "mp3_temp")
        os.makedirs(self._gif_temp_dir, exist_ok=True)
        os.makedirs(self._mp3_temp_dir, exist_ok=True)
        os.makedirs(self._output_video_dir, exist_ok=True)
        os.makedirs(self._report_dir, exist_ok=True)

        self._video_info = self._ffmpeg.probe_video(source_video_path)
        self._video_has_audio = self._video_info.has_audio
        self._video_duration = self._video_info.duration

        try:
            self._source_loudness = self._composer.analyze_loudness(source_video_path, 3.0)
        except Exception:
            self._source_loudness = {"mean_volume_db": -20.0}

        # ---- Pre-split source video: head (GIF duration) + tail ----
        self._gif_duration_s = sum(self._gif_durations) / 1000.0
        self._head_path = ""
        self._tail_path = ""
        self._head_info = self._video_info
        self._use_split = False  # only set True after verified success

        if self._video_duration > self._gif_duration_s + 0.5:
            cache_dir = self._cache_mgr._video_temp_dir
            self._head_path = os.path.join(cache_dir, "_source_head.mp4")
            self._tail_path = os.path.join(cache_dir, "_source_tail.mp4")
            if not os.path.isfile(self._head_path):
                logger.info(f"[SPLIT] Cutting head ({self._gif_duration_s:.1f}s) + tail from source")
                try:
                    self._split_source(source_video_path, self._head_path, self._tail_path,
                                       self._gif_duration_s)
                except Exception as e:
                    logger.warning(f"[SPLIT] Failed: {e}, will use full-source compose")
            # Verify split succeeded
            if os.path.isfile(self._head_path) and os.path.getsize(self._head_path) > 1000:
                self._head_info = self._ffmpeg.probe_video(self._head_path)
                if self._head_info.duration > 0.1:
                    self._use_split = True
                    logger.info(f"[SPLIT] Verified OK: head={self._head_info.duration:.1f}s")
                else:
                    logger.warning(f"[SPLIT] Head segment invalid, using full-source compose")
            else:
                logger.warning(f"[SPLIT] Head file missing/empty, using full-source compose")

        self._worker_count = _get_worker_count(
            self._composer._encoder["codec"]
        )
        logger.info(
            f"[BATCH] {CPU_COUNT} cores, {self._worker_count} workers, "
            f"encoder={self._composer._encoder['description']}, "
            f"split={self._use_split}"
        )

    def run_full_pipeline(self, regions: list[dict], on_progress=None, on_mp4_done=None):
        self._stopped = False
        self._results = [{"region": r["region"], "safe_filename": r["safe_filename"],
                          "mp4": "pending", "error": ""}
                         for r in regions]

        total = len(regions)
        completed = 0
        logger.info(f"=== Pipeline: {total} regions, {self._worker_count} workers ===")

        with ThreadPoolExecutor(max_workers=self._worker_count) as ex:
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

        # --- Step 1: GIF ---
        gif_path = os.path.join(self._gif_temp_dir, f"{safe}.gif")
        gif_ok = False
        if self._existing_file_policy == "skip" and os.path.isfile(gif_path) and os.path.getsize(gif_path) > 0:
            gif_ok = True
        else:
            try:
                gif_ok = self._gif_service.render_one(
                    region, safe, self._gif_text_layer, gif_path, "", skip_png=True)
            except Exception:
                gif_ok = False
        if not gif_ok:
            self._find_result(safe)["mp4"] = "fail"
            self._find_result(safe)["error"] = "GIF render failed"
            return

        # --- Step 2: MP3 ---
        mp3_path = os.path.join(self._mp3_temp_dir, f"{safe}.mp3")
        mp3_ok = True
        if self._existing_file_policy != "skip" or not os.path.isfile(mp3_path) or os.path.getsize(mp3_path) <= 0:
            mp3_ok = False
            if self._sapi_engine:
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        if self._sapi_engine.synthesize(region, "", mp3_path):
                            mp3_ok = True
                            break
                    except Exception:
                        pass
                    if attempt < MAX_RETRIES:
                        time.sleep(1)
        if not mp3_ok:
            self._find_result(safe)["mp4"] = "fail"
            self._find_result(safe)["error"] = "TTS failed"
            return

        if self._stopped:
            return

        # --- Step 3: MP4 composition ---
        mp4_path = os.path.join(self._output_video_dir, f"{safe}.mp4")
        if self._existing_file_policy == "skip" and os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0:
            self._find_result(safe)["mp4"] = "ok"
            self._cleanup_temp(gif_path, mp3_path)
            return

        for attempt in range(MAX_RETRIES + 1):
            try:
                adjusted_mp3 = os.path.join(self._cache_mgr._audio_temp_dir,
                                            f"{safe}_adjusted.mp3")
                try:
                    self._composer.adjust_region_mp3_volume_cached(
                        self._source_loudness, mp3_path, adjusted_mp3)
                except Exception:
                    adjusted_mp3 = mp3_path

                ok = self._compose_mp4_fast(gif_path, adjusted_mp3, mp4_path, safe)
                if ok and os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0:
                    self._find_result(safe)["mp4"] = "ok"
                    self._cleanup_temp(gif_path, mp3_path, adjusted_mp3)
                    return
            except Exception as e:
                logger.error(f"MP4 error [{region}]: {e}")
            if attempt < MAX_RETRIES:
                logger.warning(f"MP4 retry {attempt+1}: {region}")

        self._find_result(safe)["mp4"] = "fail"
        self._find_result(safe)["error"] = "FFmpeg failed"

    @staticmethod
    def _split_source(src: str, head: str, tail: str, split_time: float):
        """Cut source into head (0–split_time) and tail (split_time–end) with copy codec."""
        import subprocess, sys
        ff = FFmpegService()
        fex = ff.ffmpeg_path or "ffmpeg"
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        # Head
        r = subprocess.run([fex, "-y", "-i", src, "-t", str(split_time),
                           "-c", "copy", "-avoid_negative_ts", "make_zero", head],
                          capture_output=True, text=True, timeout=60, creationflags=flags)
        if r.returncode != 0:
            raise RuntimeError(f"Head split failed: {r.stderr[-200:]}")
        # Tail
        r = subprocess.run([fex, "-y", "-ss", str(split_time), "-i", src,
                           "-c", "copy", "-avoid_negative_ts", "make_zero", tail],
                          capture_output=True, text=True, timeout=60, creationflags=flags)
        if r.returncode != 0:
            raise RuntimeError(f"Tail split failed: {r.stderr[-200:]}")

    def _compose_mp4_fast(self, gif_path: str, mp3_path: str, output_path: str,
                          safe_name: str) -> bool:
        """Compose video — uses pre-split head+tail when available."""
        if self._use_split and self._head_path and self._tail_path:
            import subprocess, sys
            # Compose GIF + audio onto HEAD segment only
            head_out = os.path.join(self._cache_mgr._video_temp_dir,
                                    f"{safe_name}_head.mp4")
            ok = self._composer.compose_final_video_cached(
                self._head_path, gif_path, mp3_path, head_out,
                video_info=self._head_info,
                gif_durations=self._gif_durations,
                overlay_x=self._overlay_x, overlay_y=self._overlay_y,
                overlay_scale=self._overlay_scale,
            )
            if not ok:
                return False

            # Lossless concat: head_out + tail → output
            try:
                concat_list = os.path.join(self._cache_mgr._video_temp_dir,
                                          f"{safe_name}_concat.txt")
                with open(concat_list, "w") as f:
                    f.write(f"file '{os.path.abspath(head_out)}'\n")
                    f.write(f"file '{os.path.abspath(self._tail_path)}'\n")
                ff = FFmpegService()
                fex = ff.ffmpeg_path or "ffmpeg"
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                r = subprocess.run(
                    [fex, "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                     "-c", "copy", "-movflags", "+faststart", output_path],
                    capture_output=True, text=True, timeout=60,
                    creationflags=flags,
                )
                if r.returncode == 0 and os.path.isfile(output_path):
                    # Cleanup head_out
                    try: os.remove(head_out)
                    except: pass
                    try: os.remove(concat_list)
                    except: pass
                    return True
                logger.error(f"Concat failed: {r.stderr[-200:]}")
            except Exception as e:
                logger.error(f"Concat error: {e}")

            # Fallback: compose on full source
            return self._composer.compose_final_video_cached(
                self._source_video_path, gif_path, mp3_path, output_path,
                video_info=self._video_info, gif_durations=self._gif_durations,
                overlay_x=self._overlay_x, overlay_y=self._overlay_y,
                overlay_scale=self._overlay_scale,
            )

        # No split: compose as before
        return self._composer.compose_final_video_cached(
            self._source_video_path, gif_path, mp3_path, output_path,
            video_info=self._video_info, gif_durations=self._gif_durations,
            overlay_x=self._overlay_x, overlay_y=self._overlay_y,
            overlay_scale=self._overlay_scale,
        )

    def _cleanup_temp(self, *paths):
        for p in paths:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass

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
