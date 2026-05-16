import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QStackedWidget, QStatusBar, QLabel, QListWidgetItem,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from ui.import_page import ImportPage
from ui.gif_editor_page import GifEditorPage
from ui.voice_page import VoicePage
from ui.api_key_page import ApiKeyPage
from ui.batch_page import BatchPage
from ui.settings_page import SettingsPage

from core.gif_frame_decoder import GifFrameDecoder
from core.batch_task_manager import BatchTaskManager
from core.ffmpeg_service import FFmpegService
from core.tts_windows_sapi import WindowsSapiTTSEngine
from models.text_layer_model import TextLayerModel
from utils.logger import get_logger

logger = get_logger()

PAGES = [
    ("素材导入", ImportPage),
    ("GIF 编辑", GifEditorPage),
    ("语音设置", VoicePage),
    ("API Key 管理", ApiKeyPage),
    ("批量生成", BatchPage),
    ("系统设置", SettingsPage),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("矩量拓客：地区视频批量生成")
        self.resize(1280, 800)
        # App icon
        from utils.path_utils import resolve_path
        icon_path = resolve_path("assets", "icon.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._video_path: str = ""
        self._gif_path: str = ""
        self._txt_path: str = ""
        self._output_dir: str = "output"
        self._text_layer = TextLayerModel()
        self._regions: list = []
        self._batch_manager: BatchTaskManager | None = None
        self._ffmpeg = FFmpegService()
        self._sapi_engine: WindowsSapiTTSEngine | None = None

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left navigation
        nav_widget = QWidget()
        nav_widget.setFixedWidth(180)
        nav_widget.setStyleSheet("background-color: #2c3e50;")
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        nav_title = QLabel("功能导航")
        nav_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_title.setStyleSheet(
            "color: white; font-size: 16px; font-weight: bold; padding: 16px 0;"
        )
        nav_layout.addWidget(nav_title)

        self.nav_list = QListWidget()
        self.nav_list.setStyleSheet("""
            QListWidget {
                background-color: #2c3e50;
                border: none;
                color: #bdc3c7;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 12px 16px;
                border-bottom: 1px solid #34495e;
            }
            QListWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
            QListWidget::item:hover:!selected {
                background-color: #34495e;
            }
        """)
        for name, _ in PAGES:
            self.nav_list.addItem(QListWidgetItem(name))

        self.nav_list.setCurrentRow(0)
        nav_layout.addWidget(self.nav_list)
        main_layout.addWidget(nav_widget)

        self.stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        for name, PageClass in PAGES:
            page = PageClass()
            self._pages[name] = page
            self.stack.addWidget(page)

        main_layout.addWidget(self.stack, 1)
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)

        self._wire_signals()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 — 请先在「素材导入」页面导入素材")

    def _wire_signals(self):
        import_page = self._pages["素材导入"]
        gif_page = self._pages["GIF 编辑"]
        batch_page = self._pages["批量生成"]

        import_page.import_done.connect(self._on_import_done)
        gif_page.text_layer_changed.connect(self._on_text_layer_changed)

        # API key changes → refresh voice engines
        api_page = self._pages["API Key 管理"]
        api_page.keys_changed.connect(self.sync_voice_engines)

        # Batch page: one-click generate
        batch_page.generate_requested.connect(self._on_generate)

    def sync_voice_engines(self):
        """Called when API keys change to refresh voice engine list."""
        voice_page = self._pages["语音设置"]
        voice_page.refresh_api_engines()

    def _on_import_done(self, result: dict):
        paths = result.get("paths", {})
        self._video_path = paths.get("video", "")
        self._gif_path = paths.get("gif", "")
        self._txt_path = paths.get("txt", "")
        self._output_dir = paths.get("output", "output")

        info = result.get("info", {})
        region_count = info.get("regions", {}).get("count", 0)

        from core.region_reader import RegionReader
        reader = RegionReader()
        self._regions = reader.load(self._txt_path)

        self.status_bar.showMessage(
            f"素材导入成功 | "
            f"GIF: {info.get('gif', {}).get('width', '?')}x{info.get('gif', {}).get('height', '?')} "
            f"{info.get('gif', {}).get('frames', '?')}帧 | "
            f"地区: {region_count}个"
        )

        gif_page = self._pages["GIF 编辑"]
        if self._gif_path:
            gif_page.load_gif(self._gif_path)
        if self._video_path:
            gif_page.set_video_path(self._video_path)

        # Apply extracted colors and defaults from check-material step
        colors = result.get("colors")
        if colors:
            tl = gif_page._text_layer
            tl.fill_color = colors.get("fill", tl.fill_color)
            tl.stroke_color = colors.get("stroke", tl.stroke_color)
            tl.stroke_enabled = True
            tl.stroke_mode = "outer"
            tl.glow_enabled = False
            tl.font_size = 60
            tl.weight = 1350
            tl.text_template = "{地区}"
            tl.center_horizontal = True
            tl.x = 0
            tl.y = 0
            gif_page._sync_ui_from_layer()
            tl.stroke_width = 3
            gif_page._stroke_width_spin.setValue(3)

            # Add text first (vertically centered), then reposition above flower text
            gif_page._add_text()
            text_top_y = colors.get("text_top_y", 0)
            if gif_page._text_item and text_top_y > 0:
                pixmap = gif_page._text_item._pixmap
                if pixmap and not pixmap.isNull():
                    # Position "{地区}" so its bottom is 8px above flower text top
                    new_y = max(0, text_top_y - pixmap.height() - 8)
                    tl.y = new_y
                    gif_page._text_item.setPos(gif_page._text_item.x(), new_y)
                    gif_page._y_spin.blockSignals(True)
                    gif_page._y_spin.setValue(int(new_y))
                    gif_page._y_spin.blockSignals(False)

            gif_page.text_layer_changed.emit(tl)

        self._switch_to("GIF 编辑")
        # Auto-enter video preview mode after import
        gif_page.enter_preview_mode()

    def _on_text_layer_changed(self, text_layer: TextLayerModel):
        self._text_layer = text_layer

    def _on_generate(self):
        """One-click: initialize batch manager and start generating."""
        if not self._regions:
            self.status_bar.showMessage("请先在「素材导入」页面导入素材")
            return

        # Prepare paths
        base = os.path.abspath(self._output_dir)
        video_dir = os.path.join(base, "生成的视频")

        gif_decoder = GifFrameDecoder()
        gif_decoder.load(self._gif_path)

        gif_page = self._pages["GIF 编辑"]
        overlay = gif_page.get_gif_overlay_info()

        self._batch_manager = BatchTaskManager()
        voice_page = self._pages["语音设置"]
        tts_engine = voice_page.get_engine()

        # Read current text layer directly from editor (not cached copy — may be stale)
        current_text_layer = gif_page.get_text_layer()

        self._batch_manager.initialize(
            gif_decoder=gif_decoder,
            text_layer=current_text_layer,
            source_video_path=self._video_path,
            output_video_dir=video_dir,
            report_dir=video_dir,
            existing_file_policy="skip",
            sapi_engine=tts_engine,
            overlay_x=overlay.get("x", 0),
            overlay_y=overlay.get("y", 0),
            overlay_scale=overlay.get("scale_x", 1.0),
        )

        # Give manager and output dir to batch page, then start
        batch_page = self._pages["批量生成"]
        batch_page.set_manager(self._batch_manager)
        batch_page.set_output_dir(base)
        # Show generation scheme
        encoder = self._batch_manager._composer._encoder
        tts_engine = self._batch_manager._sapi_engine
        tts_desc = tts_engine.engine_name if tts_engine else "无"
        batch_page.update_scheme_info(
            encoder_desc=encoder["description"],
            workers=self._batch_manager._worker_count,
            use_split=self._batch_manager._use_split,
            head_dur=self._batch_manager._gif_duration_s,
            tts_desc=tts_desc,
        )
        batch_page.start_with_regions(
            [{"region": r.clean_name, "safe_filename": r.safe_filename}
             for r in self._regions]
        )

        self._switch_to("批量生成")
        self.status_bar.showMessage(f"正在批量生成 {len(self._regions)} 个地区...")

    def _switch_to(self, name: str):
        for i, (n, _) in enumerate(PAGES):
            if n == name:
                self.nav_list.setCurrentRow(i)
                break

    def get_shared_state(self) -> dict:
        return {
            "video_path": self._video_path,
            "gif_path": self._gif_path,
            "txt_path": self._txt_path,
            "output_dir": self._output_dir,
            "text_layer": self._text_layer,
            "regions": self._regions,
        }
