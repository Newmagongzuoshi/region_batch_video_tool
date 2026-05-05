import os
import shutil

from utils.path_utils import resolve_data_path, ensure_dir
from utils.logger import get_logger

logger = get_logger()


class CacheManager:
    def __init__(self):
        self._render_frames_dir = resolve_data_path("cache", "render_frames")
        self._audio_temp_dir = resolve_data_path("cache", "audio_temp")
        self._video_temp_dir = resolve_data_path("cache", "video_temp")

    def ensure_render_dir(self, safe_filename: str) -> str:
        path = os.path.join(self._render_frames_dir, safe_filename)
        ensure_dir(path)
        return path

    def get_render_dir(self, safe_filename: str) -> str:
        return os.path.join(self._render_frames_dir, safe_filename)

    def clear_render_frames(self, safe_filename: str | None = None):
        if safe_filename:
            path = os.path.join(self._render_frames_dir, safe_filename)
            if os.path.isdir(path):
                shutil.rmtree(path)
        else:
            for item in os.listdir(self._render_frames_dir):
                item_path = os.path.join(self._render_frames_dir, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
        logger.info(f"Cleared render frames: {safe_filename or 'all'}")

    def clear_audio_temp(self):
        for item in os.listdir(self._audio_temp_dir):
            item_path = os.path.join(self._audio_temp_dir, item)
            try:
                if os.path.isfile(item_path):
                    os.remove(item_path)
            except Exception as e:
                logger.warning(f"Failed to remove {item_path}: {e}")

    def clear_video_temp(self):
        for item in os.listdir(self._video_temp_dir):
            item_path = os.path.join(self._video_temp_dir, item)
            try:
                if os.path.isfile(item_path):
                    os.remove(item_path)
            except Exception as e:
                logger.warning(f"Failed to remove {item_path}: {e}")

    def clear_all(self):
        self.clear_render_frames()
        self.clear_audio_temp()
        self.clear_video_temp()
        logger.info("All cache cleared")

    def get_size_mb(self) -> float:
        total = 0
        for base in [self._render_frames_dir, self._audio_temp_dir, self._video_temp_dir]:
            if os.path.isdir(base):
                for dirpath, _, filenames in os.walk(base):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        try:
                            total += os.path.getsize(fp)
                        except OSError:
                            pass
        return total / (1024 * 1024)
