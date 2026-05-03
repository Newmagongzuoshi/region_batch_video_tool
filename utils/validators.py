import os
import re

from utils.logger import get_logger

logger = get_logger()

ILLEGAL_CHARS_PATTERN = re.compile(r'[\\/:*?"<>|]')


def validate_video_file(path: str) -> tuple[bool, str]:
    if not path:
        return False, "路径为空"
    if not os.path.isfile(path):
        return False, f"文件不存在: {path}"
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".mp4", ".avi", ".mov", ".mkv"):
        return False, f"不支持的视频格式: {ext}"
    return True, ""


def validate_gif_file(path: str) -> tuple[bool, str]:
    if not path:
        return False, "路径为空"
    if not os.path.isfile(path):
        return False, f"文件不存在: {path}"
    ext = os.path.splitext(path)[1].lower()
    if ext != ".gif":
        return False, f"不是 GIF 文件: {ext}"
    return True, ""


def validate_txt_file(path: str) -> tuple[bool, str]:
    if not path:
        return False, "路径为空"
    if not os.path.isfile(path):
        return False, f"文件不存在: {path}"
    return True, ""


def sanitize_filename(name: str) -> str:
    """Replace illegal Windows filename characters with underscore."""
    return ILLEGAL_CHARS_PATTERN.sub("_", name.strip())


def is_safe_filename(name: str) -> bool:
    return not ILLEGAL_CHARS_PATTERN.search(name)


def check_disk_space(path: str, required_gb: float = 1.0) -> tuple[bool, float]:
    try:
        import shutil
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        return free_gb >= required_gb, free_gb
    except Exception:
        return True, -1
