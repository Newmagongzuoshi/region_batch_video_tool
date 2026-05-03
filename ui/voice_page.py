import json
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSlider, QGroupBox, QTextEdit, QMessageBox,
)
from PySide6.QtCore import Qt

from core.tts_windows_sapi import WindowsSapiTTSEngine
from core.ffmpeg_service import FFmpegService
from utils.path_utils import resolve_path
from utils.logger import get_logger

logger = get_logger()


class VoicePage(QWidget):
    def __init__(self):
        super().__init__()
        self._ffmpeg = FFmpegService()
        self._engine: WindowsSapiTTSEngine | None = None
        self._api_engine = None

        if self._ffmpeg.ffmpeg_path:
            self._engine = WindowsSapiTTSEngine(ffmpeg_path=self._ffmpeg.ffmpeg_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("语音设置")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        # Engine selection
        eng_group = QGroupBox("语音引擎")
        eng_layout = QVBoxLayout(eng_group)

        eng_row = QHBoxLayout()
        eng_row.addWidget(QLabel("引擎:"))
        self._eng_combo = QComboBox()
        self._eng_combo.addItem("Windows 本地 TTS (SAPI5)")
        self._eng_combo.currentIndexChanged.connect(self._on_engine_changed)
        eng_row.addWidget(self._eng_combo, 1)
        eng_layout.addLayout(eng_row)

        # Voice selection
        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("音色:"))
        self._voice_combo = QComboBox()
        voice_row.addWidget(self._voice_combo, 1)
        eng_layout.addLayout(voice_row)

        layout.addWidget(eng_group)

        # Voice parameters
        param_group = QGroupBox("语音参数")
        param_layout = QVBoxLayout(param_group)

        # Speed
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("语速:"))
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(50, 200)
        self._speed_slider.setValue(100)
        self._speed_label = QLabel("1.0x")
        self._speed_slider.valueChanged.connect(
            lambda v: self._speed_label.setText(f"{v / 100:.1f}x")
        )
        speed_row.addWidget(self._speed_slider, 1)
        speed_row.addWidget(self._speed_label)
        param_layout.addLayout(speed_row)

        # Volume
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("音量:"))
        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(10, 200)
        self._vol_slider.setValue(100)
        self._vol_label = QLabel("1.0")
        self._vol_slider.valueChanged.connect(
            lambda v: self._vol_label.setText(f"{v / 100:.1f}")
        )
        vol_row.addWidget(self._vol_slider, 1)
        vol_row.addWidget(self._vol_label)
        param_layout.addLayout(vol_row)

        layout.addWidget(param_group)

        # Test section
        test_group = QGroupBox("试听")
        test_layout = QVBoxLayout(test_group)

        test_row = QHBoxLayout()
        self._test_text = QTextEdit()
        self._test_text.setMaximumHeight(60)
        self._test_text.setPlaceholderText("输入试听文字...")
        self._test_text.setText("温州市")
        test_layout.addWidget(self._test_text)

        test_btn = QPushButton("试听")
        test_btn.clicked.connect(self._test_tts)
        test_layout.addWidget(test_btn)

        layout.addWidget(test_group)

        # Batch generate MP3 button
        gen_btn = QPushButton("批量生成所有地区 MP3")
        gen_btn.setStyleSheet(
            "QPushButton { background-color: #e67e22; color: white; font-size: 14px; "
            "padding: 10px 20px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #d35400; }"
        )
        gen_btn.clicked.connect(self._on_batch_mp3)
        layout.addWidget(gen_btn)

        layout.addStretch()

        # Populate voices
        self._refresh_voices()

    def _refresh_voices(self):
        self._voice_combo.clear()
        if self._engine:
            for v in self._engine.list_voices():
                self._voice_combo.addItem(v["name"], v["id"])

    def _on_engine_changed(self, idx: int):
        self._refresh_voices()

    def _test_tts(self):
        text = self._test_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入试听文字")
            return

        if self._engine is None:
            QMessageBox.warning(self, "提示", "语音引擎未初始化 (需要 FFmpeg)")
            return

        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), "_tts_test.mp3")
        voice_id = self._voice_combo.currentData() or ""
        speed = self._speed_slider.value() / 100.0
        volume = self._vol_slider.value() / 100.0

        ok = self._engine.synthesize(text, voice_id, tmp_path, speed=speed, volume=volume)
        if ok:
            QMessageBox.information(self, "成功", f"试听文件已生成:\n{tmp_path}")
        else:
            QMessageBox.warning(self, "失败", "语音生成失败，请检查日志")

    def _on_batch_mp3(self):
        QMessageBox.information(self, "提示", "批量生成 MP3 功能请在「批量生成」页面操作")

    def get_engine(self):
        return self._engine

    def get_voice_params(self) -> dict:
        return {
            "engine": "windows_sapi",
            "voice_id": self._voice_combo.currentData() or "",
            "speed": self._speed_slider.value() / 100.0,
            "volume": self._vol_slider.value() / 100.0,
        }
