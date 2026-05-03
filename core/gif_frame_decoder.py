import os
from collections import OrderedDict

from PIL import Image, ImageSequence
from utils.logger import get_logger

logger = get_logger()

CACHE_ALL_THRESHOLD = 200
LRU_WINDOW = 30


class GifFrameDecoder:
    def __init__(self):
        self._path: str | None = None
        self._size: tuple[int, int] = (0, 0)
        self._durations: list[int] = []
        self._total_frames: int = 0
        self._has_alpha: bool = False
        self._frames: dict[int, Image.Image] = {}
        self._use_lru: bool = False

    def load(self, gif_path: str) -> None:
        self._path = gif_path
        self._frames.clear()

        img = Image.open(gif_path)
        self._size = (img.width, img.height)
        self._total_frames = getattr(img, "n_frames", 1)
        self._durations = []
        self._has_alpha = img.mode in ("RGBA", "PA", "LA") or "transparency" in img.info
        self._use_lru = self._total_frames >= CACHE_ALL_THRESHOLD

        frame_index = 0
        for frame in ImageSequence.Iterator(img):
            rgba = frame.convert("RGBA")
            duration = frame.info.get("duration", 100)
            if duration <= 0:
                duration = 100
            self._durations.append(duration)

            if not self._use_lru:
                self._frames[frame_index] = rgba
            frame_index += 1

        img.close()

        if self._total_frames != len(self._durations):
            logger.warning(
                f"Frame count mismatch: expected {self._total_frames}, got {len(self._durations)}"
            )
            self._total_frames = len(self._durations)

        logger.info(
            f"GIF loaded: {self._size[0]}x{self._size[1]}, "
            f"{self._total_frames} frames, "
            f"alpha={self._has_alpha}, lru={self._use_lru}"
        )

    def get_size(self) -> tuple[int, int]:
        return self._size

    def get_frame_count(self) -> int:
        return self._total_frames

    def get_frame(self, index: int) -> Image.Image | None:
        if index < 0 or index >= self._total_frames:
            return None

        if index in self._frames:
            return self._frames[index]

        if self._use_lru:
            return self._load_single_frame(index)

        return None

    def _load_single_frame(self, index: int) -> Image.Image | None:
        if not self._path:
            return None
        img = Image.open(self._path)
        for i, frame in enumerate(ImageSequence.Iterator(img)):
            if i == index:
                rgba = frame.convert("RGBA")
                self._frames[index] = rgba
                self._trim_lru_cache(index)
                img.close()
                return rgba
        img.close()
        return None

    def _trim_lru_cache(self, current: int) -> None:
        keep_start = max(0, current - LRU_WINDOW)
        keep_end = min(self._total_frames, current + LRU_WINDOW + 1)
        keep = set(range(keep_start, keep_end))
        for k in list(self._frames.keys()):
            if k not in keep:
                del self._frames[k]

    def get_duration(self, index: int) -> int:
        if 0 <= index < len(self._durations):
            return self._durations[index]
        return 100

    def get_durations(self) -> list[int]:
        return list(self._durations)

    def has_alpha(self) -> bool:
        return self._has_alpha

    def get_total_duration_ms(self) -> int:
        return sum(self._durations)

    def get_frame_at_time(self, elapsed_ms: int) -> tuple[int, Image.Image | None]:
        """Return (frame_index, frame_image) for a given elapsed time in ms."""
        cumulative = 0
        for i, dur in enumerate(self._durations):
            if elapsed_ms < cumulative + dur:
                frame = self.get_frame(i)
                return i, frame
            cumulative += dur
        # past end: return last frame
        last = self._total_frames - 1
        return last, self.get_frame(last)
