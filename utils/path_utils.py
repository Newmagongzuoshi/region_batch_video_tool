import os
import sys


def get_app_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def resolve_path(*segments: str) -> str:
    return os.path.normpath(os.path.join(get_app_dir(), *segments))


def safe_filename(name: str) -> str:
    r"""Clean Windows-illegal filename characters: \ / : * ? " < > |"""
    illegal = r'\/:*?"<>|'
    result = name.strip()
    for ch in illegal:
        result = result.replace(ch, '_')
    return result
