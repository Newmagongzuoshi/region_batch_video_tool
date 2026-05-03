import os
import sys
import subprocess

from utils.logger import get_logger

logger = get_logger()


def wav_to_mp3(wav_path: str, mp3_path: str, ffmpeg_path: str = "ffmpeg") -> bool:
    try:
        result = subprocess.run(
            [ffmpeg_path, "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "2", mp3_path],
            capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode != 0:
            logger.error(f"wav_to_mp3 failed: {result.stderr[:300]}")
            return False
        return os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0
    except Exception as e:
        logger.error(f"wav_to_mp3 exception: {e}")
        return False


def adjust_mp3_volume(
    input_path: str,
    output_path: str,
    volume_db: float,
    ffmpeg_path: str = "ffmpeg",
) -> bool:
    try:
        result = subprocess.run(
            [ffmpeg_path, "-y", "-i", input_path, "-af", f"volume={volume_db}dB",
             "-codec:a", "libmp3lame", "-q:a", "2", output_path],
            capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode != 0:
            logger.error(f"adjust_mp3_volume failed: {result.stderr[:300]}")
            return False
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        logger.error(f"adjust_mp3_volume exception: {e}")
        return False
