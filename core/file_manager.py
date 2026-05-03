import os

from utils.path_utils import resolve_path, ensure_dir
from utils.logger import get_logger

logger = get_logger()

REQUIRED_DIRS = [
    "output/材料库",
    "output/生成的视频",
    "cache/render_frames",
    "cache/audio_temp",
    "cache/video_temp",
    "logs",
]


def init_app_dirs() -> None:
    for d in REQUIRED_DIRS:
        path = resolve_path(*d.split("/"))
        ensure_dir(path)
        logger.info(f"Directory ready: {path}")


def get_output_gif_dir() -> str:
    return resolve_path("output", "材料库")


def get_output_video_dir() -> str:
    return resolve_path("output", "生成的视频")


def get_cache_dir() -> str:
    return resolve_path("cache")


def get_render_frames_dir() -> str:
    return resolve_path("cache", "render_frames")


def get_audio_temp_dir() -> str:
    return resolve_path("cache", "audio_temp")


def get_video_temp_dir() -> str:
    return resolve_path("cache", "video_temp")


def get_logs_dir() -> str:
    return resolve_path("logs")
