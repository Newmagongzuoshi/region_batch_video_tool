import json, os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox
from PySide6.QtCore import Qt

from utils.path_utils import resolve_data_path


def _config_path():
    return resolve_data_path("config", "app_config.json")


def load_video_compress() -> bool:
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f).get("video_compress", False)
    except Exception:
        return False


def save_video_compress(enabled: bool):
    path = _config_path()
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["video_compress"] = enabled
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("系统设置")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        self._compress_cb = QCheckBox("视频压缩（输出码率降低至 3Mbps，减小文件体积）")
        self._compress_cb.setChecked(load_video_compress())
        self._compress_cb.toggled.connect(self._on_compress_toggled)
        self._compress_cb.setStyleSheet("font-size: 14px; padding: 8px 0;")
        layout.addWidget(self._compress_cb)

        layout.addStretch()

    def _on_compress_toggled(self, checked: bool):
        save_video_compress(checked)
