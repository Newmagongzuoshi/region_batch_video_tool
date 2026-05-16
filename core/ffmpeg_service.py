import os
import subprocess
import sys

from models.video_info_model import VideoInfoModel
from utils.path_utils import resolve_path, get_app_dir
from utils.logger import get_logger

logger = get_logger()


class FFmpegService:
    def __init__(self):
        self._ffmpeg_path: str | None = None
        self._ffprobe_path: str | None = None
        self._detected = False
        self._detect()

    def _detect(self) -> None:
        # Search order:
        # 1. EXE directory (for PyInstaller bundles, user puts ffmpeg next to exe)
        # 2. EXE directory / tools/ffmpeg/
        # 3. Project tools/ffmpeg/ (dev mode)
        # 4. System PATH
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else None
        search_paths = []
        if exe_dir:
            search_paths.append(exe_dir)
            search_paths.append(os.path.join(exe_dir, "tools", "ffmpeg"))
        search_paths.append(resolve_path("tools", "ffmpeg"))
        search_paths.append(get_app_dir())

        for base in search_paths:
            if not os.path.isdir(base):
                continue
            ffmpeg_exe = os.path.join(base, "ffmpeg.exe")
            ffprobe_exe = os.path.join(base, "ffprobe.exe")
            if os.path.isfile(ffmpeg_exe):
                self._ffmpeg_path = ffmpeg_exe
            if os.path.isfile(ffprobe_exe):
                self._ffprobe_path = ffprobe_exe

        for cmd_name, attr in [("ffmpeg", "_ffmpeg_path"), ("ffprobe", "_ffprobe_path")]:
            if getattr(self, attr) is None:
                found = self._find_in_path(cmd_name + ".exe")
                if found:
                    setattr(self, attr, found)

        self._detected = self._ffmpeg_path is not None and self._ffprobe_path is not None

        if self._detected:
            logger.info(f"FFmpeg: {self._ffmpeg_path}")
            logger.info(f"FFprobe: {self._ffprobe_path}")
        else:
            logger.warning("FFmpeg/FFprobe not found. Video composition will not work.")

    @staticmethod
    def _find_in_path(exe_name: str) -> str | None:
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(path_dir, exe_name)
            if os.path.isfile(candidate):
                return candidate
        return None

    @property
    def is_available(self) -> bool:
        return self._detected

    @property
    def ffmpeg_path(self) -> str | None:
        return self._ffmpeg_path

    @property
    def ffprobe_path(self) -> str | None:
        return self._ffprobe_path

    def check_ffmpeg(self) -> bool:
        if not self._ffmpeg_path:
            return False
        try:
            result = subprocess.run(
                [self._ffmpeg_path, "-version"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"ffmpeg -version failed: {e}")
            return False

    def detect_hardware_encoder(self) -> dict:
        """Auto-detect the best available hardware video encoder.

        Actually tests each encoder with a 1-frame encode — some GPUs
        list NVENC but fail at runtime (driver issues).
        """
        if not self._ffmpeg_path:
            return {"codec": "libx264", "preset": "ultrafast",
                    "description": "CPU x264 (fallback)"}

        def _test_encoder(codec: str, preset: str) -> bool:
            try:
                r = subprocess.run(
                    [self._ffmpeg_path, "-y", "-f", "lavfi", "-i",
                     "color=c=black:s=32x32:d=0.1", "-t", "0.1",
                     "-c:v", codec, "-preset", preset, "-pix_fmt", "yuv420p",
                     "-f", "null", "-"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                return r.returncode == 0
            except Exception:
                return False

        # Test GPU encoders in priority order
        for codec, preset, desc in [
            ("h264_nvenc", "p1", "NVIDIA NVENC GPU"),
            ("h264_amf", "speed", "AMD AMF GPU"),
            ("h264_qsv", "veryfast", "Intel QSV GPU"),
        ]:
            if _test_encoder(codec, preset):
                return {"codec": codec, "preset": preset, "description": desc}
            logger.info(f"Encoder {codec} listed but failed runtime test, skipping")

        return {"codec": "libx264", "preset": "ultrafast",
                "description": "CPU x264"}

    def check_ffprobe(self) -> bool:
        if not self._ffprobe_path:
            return False
        try:
            result = subprocess.run(
                [self._ffprobe_path, "-version"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"ffprobe -version failed: {e}")
            return False

    def probe_video(self, video_path: str) -> VideoInfoModel:
        info = VideoInfoModel()
        if not self._ffprobe_path:
            logger.error("ffprobe not available")
            return info

        try:
            result = subprocess.run(
                [
                    self._ffprobe_path,
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    os.path.normpath(video_path),
                ],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode != 0:
                logger.error(f"ffprobe failed: {result.stderr[:500]}")
                return info

            import json
            data = json.loads(result.stdout)

            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    info.width = stream.get("width", 0)
                    info.height = stream.get("height", 0)
                    fps_str = stream.get("r_frame_rate", "0/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        info.fps = float(num) / float(den) if float(den) != 0 else 0
                    info.codec = stream.get("codec_name", "")
                elif stream.get("codec_type") == "audio":
                    info.has_audio = True
                    info.audio_sample_rate = int(stream.get("sample_rate", 0))
                    info.audio_channels = stream.get("channels", 0)

            fmt = data.get("format", {})
            info.duration = float(fmt.get("duration", 0))

            logger.info(
                f"Video: {info.width}x{info.height}, {info.fps:.2f}fps, "
                f"{info.duration:.2f}s, audio={info.has_audio}"
            )
            return info

        except Exception as e:
            logger.error(f"Error probing video: {e}")
            return info

    def extract_first_frame(self, video_path: str, output_png_path: str) -> bool:
        if not self._ffmpeg_path:
            logger.error("ffmpeg not available")
            return False
        try:
            result = subprocess.run(
                [self._ffmpeg_path, "-y", "-i", os.path.normpath(video_path),
                 "-vframes", "1", "-q:v", "2", os.path.normpath(output_png_path)],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            ok = result.returncode == 0 and os.path.isfile(output_png_path)
            if ok:
                logger.info(f"First frame extracted to {output_png_path}")
            else:
                logger.error(f"First frame extraction failed: {result.stderr[:300]}")
            return ok
        except Exception as e:
            logger.error(f"extract_first_frame exception: {e}")
            return False
