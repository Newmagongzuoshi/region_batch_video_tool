import json
import os
import re
import sys
import subprocess

from utils.logger import get_logger

logger = get_logger()


class AudioAnalyzer:
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self._ffmpeg = ffmpeg_path

    def analyze_loudness(self, media_path: str, duration: float = 3.0) -> dict:
        """Analyze loudness of the first `duration` seconds of media using volumedetect."""
        try:
            result = subprocess.run(
                [
                    self._ffmpeg, "-y",
                    "-i", media_path,
                    "-t", str(duration),
                    "-af", "volumedetect",
                    "-f", "null", "NUL" if sys.platform == "win32" else "/dev/null",
                ],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            stderr = result.stderr

            mean_match = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", stderr)
            max_match = re.search(r"max_volume:\s*(-?\d+\.?\d*)\s*dB", stderr)

            mean_vol = float(mean_match.group(1)) if mean_match else -20.0
            max_vol = float(max_match.group(1)) if max_match else 0.0

            logger.info(f"Loudness analysis: mean={mean_vol:.1f}dB, max={max_vol:.1f}dB")
            return {"mean_volume_db": mean_vol, "max_volume_db": max_vol}
        except Exception as e:
            logger.error(f"Loudness analysis failed: {e}")
            return {"mean_volume_db": -20.0, "max_volume_db": 0.0}
