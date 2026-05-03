import os
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSlider, QGroupBox, QTextEdit, QMessageBox,
)
from PySide6.QtCore import Qt, QUrl, QThread, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from core.tts_windows_sapi import WindowsSapiTTSEngine
from core.tts_custom_http import CustomHttpTTSEngine
from core.tts_volcengine import VolcengineTTSEngine
from core.tts_edge import EdgeTTSEngine
from core.tts_piper import PiperTTSEngine
from core.api_key_manager import ApiKeyManager
from core.ffmpeg_service import FFmpegService
from utils.path_utils import resolve_path
from utils.logger import get_logger

logger = get_logger()


class VoicePage(QWidget):
    def __init__(self):
        super().__init__()
        self._ffmpeg = FFmpegService()
        self._sapi_engine: WindowsSapiTTSEngine | None = None
        self._edge_engine: EdgeTTSEngine | None = None
        self._piper_engine: PiperTTSEngine | None = None
        self._http_engines: list[CustomHttpTTSEngine] = []
        self._api_mgr = ApiKeyManager()

        ffmpeg = self._ffmpeg.ffmpeg_path or "ffmpeg"
        if self._ffmpeg.ffmpeg_path:
            self._sapi_engine = WindowsSapiTTSEngine(ffmpeg_path=ffmpeg)
        self._edge_engine = EdgeTTSEngine(ffmpeg_path=ffmpeg)
        self._piper_engine = PiperTTSEngine(ffmpeg_path=ffmpeg)

        # Audio player
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(1.0)

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

        self._test_text = QTextEdit()
        self._test_text.setMaximumHeight(60)
        self._test_text.setPlaceholderText("输入试听文字...")
        self._test_text.setText("温州市")
        test_layout.addWidget(self._test_text)

        test_btn = QPushButton("试听")
        test_btn.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white; font-size: 14px; "
            "padding: 8px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2980b9; }"
        )
        test_btn.clicked.connect(self._test_tts)
        test_layout.addWidget(test_btn)

        layout.addWidget(test_group)
        layout.addStretch()

        # Build engine list from API keys + local
        self._rebuild_engine_list()

    def refresh_api_engines(self):
        """Call this when API keys change to sync the engine list."""
        self._rebuild_engine_list()

    def _rebuild_engine_list(self):
        self._eng_combo.blockSignals(True)
        self._eng_combo.clear()
        self._http_engines = []

        # Built-in free engines (no API key needed)
        self._eng_combo.addItem("Edge TTS (免费-微软神经网络)", "edge")
        self._eng_combo.addItem("Piper TTS (本地离线)", "piper")
        self._eng_combo.addItem("Windows 本地 TTS (SAPI5)", "sapi")

        # API key configs from ApiKeyManager
        for cfg in self._api_mgr.list_configs():
            if cfg.get("enabled", True):
                provider = cfg.get("provider", "custom_http")
                label = f"{cfg['display_name']} ({provider})"
                self._eng_combo.addItem(label, f"{provider}:{cfg['config_id']}")

        self._eng_combo.blockSignals(False)
        self._on_engine_changed(0)

    def _parse_engine(self):
        """Returns (provider, config_id) from current engine selection."""
        val = self._eng_combo.currentData() or ""
        if val in ("sapi", "edge", "piper"):
            return (val, "")
        if ":" in val:
            parts = val.split(":", 1)
            return (parts[0], parts[1])
        return ("custom_http", val)

    def _on_engine_changed(self, idx: int):
        provider, _ = self._parse_engine()

        self._voice_combo.clear()
        if provider == "sapi":
            if self._sapi_engine:
                for v in self._sapi_engine.list_voices():
                    self._voice_combo.addItem(v["name"], v["id"])
        elif provider == "edge":
            from core.tts_edge import EDGE_VOICES
            for v in EDGE_VOICES:
                self._voice_combo.addItem(v["name"], v["id"])
        elif provider == "piper":
            from core.tts_piper import PIPER_VOICES
            for v in PIPER_VOICES:
                self._voice_combo.addItem(v["name"], v["id"])
        elif provider == "volcengine":
            from core.tts_volcengine import VOICE_TYPES
            for vt in VOICE_TYPES:
                self._voice_combo.addItem(vt["name"], vt["id"])
        else:
            self._voice_combo.addItem("默认音色", "")

    def _test_tts(self):
        text = self._test_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入试听文字")
            return

        provider, config_id = self._parse_engine()
        voice_id = self._voice_combo.currentData() or ""
        speed = self._speed_slider.value() / 100.0
        volume = self._vol_slider.value() / 100.0

        self._player.stop()
        self._test_text.setEnabled(False)

        # Run synthesis in background thread to avoid UI freeze
        self._tts_worker = _TTSWorker(
            provider, config_id, voice_id, text, speed, volume,
            self._sapi_engine, self._edge_engine, self._piper_engine, self._api_mgr
        )
        self._tts_worker.finished.connect(self._on_tts_done)
        self._tts_worker.start()

    def _on_tts_done(self, ok: bool, tmp_path: str):
        self._test_text.setEnabled(True)
        if ok and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 100:
            self._player.setSource(QUrl.fromLocalFile(tmp_path))
            self._player.play()
        else:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            QMessageBox.warning(self, "失败", "语音合成失败，请稍后重试")

    def get_engine(self):
        """Return the active TTS engine for batch use (with user-selected voice)."""
        provider, config_id = self._parse_engine()
        voice_id = self._voice_combo.currentData() or ""

        if provider == "sapi":
            if voice_id and self._sapi_engine:
                self._sapi_engine._voice = voice_id
            return self._sapi_engine
        elif provider == "edge":
            if voice_id and self._edge_engine:
                self._edge_engine._voice = voice_id
            return self._edge_engine
        elif provider == "piper":
            if voice_id and self._piper_engine:
                self._piper_engine._voice_id = voice_id
            return self._piper_engine
        elif provider == "volcengine":
            app_id = self._api_mgr.get_app_id(config_id)
            token = self._api_mgr.get_key(config_id)
            voice = self._voice_combo.currentData() or "BV001_streaming"
            return VolcengineTTSEngine(app_id, token, voice)
        else:
            api_key = self._api_mgr.get_key(config_id)
            entry = self._api_mgr.get_entry(config_id)
            if entry:
                cfg = {
                    "provider_name": entry.get("display_name", "Custom"),
                    "method": "POST",
                    "endpoint": entry.get("endpoint", ""),
                    "headers": {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    "body": {"text": "{{text}}", "voice": "{{voice_id}}"},
                    "response_type": "binary",
                }
                return CustomHttpTTSEngine(cfg, api_key)
        return self._sapi_engine

    def get_voice_params(self) -> dict:
        return {
            "engine": self._eng_combo.currentData(),
            "voice_id": self._voice_combo.currentData() or "",
            "speed": self._speed_slider.value() / 100.0,
            "volume": self._vol_slider.value() / 100.0,
        }


class _TTSWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, provider, config_id, voice_id, text, speed, volume,
                 sapi_engine, edge_engine, piper_engine, api_mgr):
        super().__init__()
        self._provider = provider
        self._config_id = config_id
        self._voice_id = voice_id
        self._text = text
        self._speed = speed
        self._volume = volume
        self._sapi = sapi_engine
        self._edge = edge_engine
        self._piper = piper_engine
        self._api_mgr = api_mgr

    def run(self):
        import uuid, os, tempfile
        tmp_path = os.path.join(tempfile.gettempdir(),
                                f"_tts_test_{uuid.uuid4().hex[:6]}.mp3")
        ok = False
        try:
            p = self._provider
            if p == "sapi" and self._sapi:
                ok = self._sapi.synthesize(self._text, self._voice_id, tmp_path,
                                           speed=self._speed, volume=self._volume)
            elif p == "edge" and self._edge:
                ok = self._edge.synthesize(self._text, self._voice_id, tmp_path,
                                           speed=self._speed)
            elif p == "piper" and self._piper:
                ok = self._piper.synthesize(self._text, self._voice_id, tmp_path,
                                            speed=self._speed)
            elif p == "volcengine":
                from core.tts_volcengine import VolcengineTTSEngine
                app_id = self._api_mgr.get_app_id(self._config_id)
                token = self._api_mgr.get_key(self._config_id)
                engine = VolcengineTTSEngine(app_id, token, self._voice_id)
                ok = engine.synthesize(self._text, self._voice_id, tmp_path,
                                       speed=self._speed)
            else:
                from core.tts_custom_http import CustomHttpTTSEngine
                api_key = self._api_mgr.get_key(self._config_id)
                entry = self._api_mgr.get_entry(self._config_id)
                if entry:
                    cfg = {
                        "provider_name": entry.get("display_name", "Custom"),
                        "method": "POST",
                        "endpoint": entry.get("endpoint", ""),
                        "headers": {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        "body": {"text": "{{text}}", "voice": "{{voice_id}}"},
                        "response_type": "binary",
                    }
                    engine = CustomHttpTTSEngine(cfg, api_key)
                    ok = engine.synthesize(self._text, self._voice_id, tmp_path,
                                           speed=self._speed)
        except Exception:
            ok = False
        self.finished.emit(ok, tmp_path)
