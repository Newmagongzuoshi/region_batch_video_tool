import os
import sys


def get_app_dir() -> str:
    """Read-only app directory (bundled assets, templates)."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_data_dir() -> str:
    """Writable data directory — Documents/矩量拓客：视频批量生成/ or project root."""
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.expanduser("~"), "Documents", "矩量拓客：视频批量生成")
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def resolve_path(*segments: str) -> str:
    """Resolve relative to read-only app dir (assets, config)."""
    return os.path.normpath(os.path.join(get_app_dir(), *segments))


def resolve_data_path(*segments: str) -> str:
    """Resolve relative to writable data dir (cache, logs, output)."""
    return os.path.normpath(os.path.join(get_data_dir(), *segments))


def to_native_path(path: str) -> str:
    """Ensure path works with subprocess calls (handles Chinese chars)."""
    return os.path.normpath(path)


def safe_filename(name: str) -> str:
    r"""Clean Windows-illegal filename characters: \ / : * ? " < > |"""
    illegal = r'\/:*?"<>|'
    result = name.strip()
    for ch in illegal:
        result = result.replace(ch, '_')
    return result
