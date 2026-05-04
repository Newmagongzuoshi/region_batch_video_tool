import os
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QGroupBox,
    QColorDialog, QLineEdit, QFormLayout, QSlider,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage, QColor

from core.gif_frame_decoder import GifFrameDecoder
from core.text_render_service import TextRenderService
from core.template_manager import TemplateManager
from core.ffmpeg_service import FFmpegService
from models.text_layer_model import TextLayerModel
from ui.gif_canvas_view import GifCanvasView
from ui.draggable_text_item import DraggableTextItem
from utils.logger import get_logger

logger = get_logger()

FONT_DIR = "C:/Windows/Fonts"
_SYSTEM_FONTS: dict[str, str] = {}
_FONT_DISPLAY_NAMES: list[str] = []


def _scan_fonts():
    global _SYSTEM_FONTS, _FONT_DISPLAY_NAMES
    if _SYSTEM_FONTS:
        return
    candidates = {}
    for f in os.listdir(FONT_DIR):
        lower = f.lower()
        if lower.endswith(('.ttf', '.ttc', '.otf')):
            name = os.path.splitext(f)[0]
            candidates[name] = os.path.join(FONT_DIR, f)

    priority = [
        ("微软雅黑", ["msyh", "msyhbd"]),
        ("黑体", ["simhei"]),
        ("宋体", ["simsun"]),
        ("楷体", ["simkai"]),
        ("仿宋", ["simfang"]),
        ("Arial", ["arial"]),
        ("Calibri", ["calibri"]),
        ("Times New Roman", ["times"]),
        ("Georgia", ["georgia"]),
        ("Verdana", ["verdana"]),
        ("Tahoma", ["tahoma"]),
        ("Comic Sans MS", ["comic"]),
        ("Impact", ["impact"]),
        ("Segoe UI", ["segoeui"]),
    ]
    for display_name, keys in priority:
        for key in keys:
            if key in candidates:
                _SYSTEM_FONTS[display_name] = candidates[key]
                _FONT_DISPLAY_NAMES.append(display_name)
                break
    for name, path in sorted(candidates.items()):
        if name not in _SYSTEM_FONTS:
            _SYSTEM_FONTS[name] = path
            _FONT_DISPLAY_NAMES.append(name)


class GifEditorPage(QWidget):
    text_layer_changed = Signal(object)

    def __init__(self):
        super().__init__()
        _scan_fonts()

        self._decoder: GifFrameDecoder | None = None
        self._text_layer = TextLayerModel()
        self._text_item: DraggableTextItem | None = None
        self._render_service = TextRenderService()
        self._template_mgr = TemplateManager()
        self._ffmpeg = FFmpegService()
        self._video_path: str = ""
        self._preview_frame_path: str = ""
        # Persistent overlay position (survives preview on/off)
        self._overlay_x: int = 0
        self._overlay_y: int = 0
        self._overlay_scale: float = 1.0

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === Canvas ===
        canvas_container = QWidget()
        canvas_container.setStyleSheet("background-color: #1a1a2e;")
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QWidget()
        toolbar.setStyleSheet("background-color: #2c3e50; padding: 4px;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        toolbar_layout.setSpacing(6)

        self._play_btn = QPushButton("▶ 播放")
        self._play_btn.setStyleSheet(
            "QPushButton { color: white; background: #27ae60; padding: 4px 12px; "
            "border-radius: 3px; } QPushButton:hover { background: #219a52; }"
        )
        self._play_btn.clicked.connect(self._toggle_play)
        toolbar_layout.addWidget(self._play_btn)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.clicked.connect(lambda: self._canvas.previous_frame())
        toolbar_layout.addWidget(self._prev_btn)

        self._next_btn = QPushButton("▶")
        self._next_btn.clicked.connect(lambda: self._canvas.next_frame())
        toolbar_layout.addWidget(self._next_btn)

        self._frame_label = QLabel("帧: 0/0")
        self._frame_label.setStyleSheet("color: #bdc3c7; font-size: 12px; min-width: 70px;")
        toolbar_layout.addWidget(self._frame_label)

        self._gif_size_label = QLabel("")
        self._gif_size_label.setStyleSheet("color: #95a5a6; font-size: 11px;")
        toolbar_layout.addWidget(self._gif_size_label)

        toolbar_layout.addStretch()

        # Preview mode toggle
        self._preview_btn = QPushButton("👁 视频预览")
        self._preview_btn.setCheckable(True)
        self._preview_btn.setStyleSheet(
            "QPushButton { color: #ecf0f1; background: #8e44ad; padding: 4px 12px; "
            "border-radius: 3px; } QPushButton:checked { background: #e67e22; }"
        )
        self._preview_btn.clicked.connect(self._toggle_preview)
        toolbar_layout.addWidget(self._preview_btn)

        bg_label = QLabel("背景:")
        bg_label.setStyleSheet("color: #bdc3c7; font-size: 11px;")
        toolbar_layout.addWidget(bg_label)
        self._bg_combo = QComboBox()
        self._bg_combo.addItems(["棋盘格", "黑色", "白色"])
        self._bg_combo.currentIndexChanged.connect(self._on_bg_changed)
        self._bg_combo.setMaximumWidth(80)
        toolbar_layout.addWidget(self._bg_combo)

        toolbar_layout.addStretch()

        # Zoom controls
        zoom_label = QLabel("画布:")
        zoom_label.setStyleSheet("color: #bdc3c7; font-size: 11px;")
        toolbar_layout.addWidget(zoom_label)
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedSize(24, 24)
        zoom_out_btn.setStyleSheet("QPushButton { color: white; background: #555; border-radius: 2px; } QPushButton:hover { background: #777; }")
        zoom_out_btn.clicked.connect(lambda: self._canvas.zoom_out())
        toolbar_layout.addWidget(zoom_out_btn)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("color: #bdc3c7; font-size: 11px; min-width: 36px;")
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar_layout.addWidget(self._zoom_label)
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedSize(24, 24)
        zoom_in_btn.setStyleSheet("QPushButton { color: white; background: #555; border-radius: 2px; } QPushButton:hover { background: #777; }")
        zoom_in_btn.clicked.connect(lambda: self._canvas.zoom_in())
        toolbar_layout.addWidget(zoom_in_btn)
        fit_btn = QPushButton("适应")
        fit_btn.setFixedSize(36, 24)
        fit_btn.setStyleSheet("QPushButton { color: white; background: #555; border-radius: 2px; font-size: 10px; } QPushButton:hover { background: #777; }")
        fit_btn.clicked.connect(lambda: self._canvas.zoom_fit())
        toolbar_layout.addWidget(fit_btn)

        canvas_layout.addWidget(toolbar)

        self._canvas = GifCanvasView()
        canvas_layout.addWidget(self._canvas, 1)

        main_layout.addWidget(canvas_container, 1)

        # === Right panel ===
        panel = QWidget()
        panel.setFixedWidth(320)
        panel.setStyleSheet("background-color: #f5f6fa;")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(6)
        panel_layout.setContentsMargins(12, 12, 12, 12)

        # Preview: GIF position/size
        self._preview_group = QGroupBox("视频预览 — GIF 叠加位置")
        self._preview_group.setVisible(False)
        prev_layout = QVBoxLayout(self._preview_group)

        prev_info = QLabel("GIF 以原始尺寸叠加到视频上。拖动 GIF 调整位置。")
        prev_info.setWordWrap(True)
        prev_info.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        prev_layout.addWidget(prev_info)

        pos_form = QFormLayout()
        gif_pos_row = QHBoxLayout()
        self._gif_x_spin = QSpinBox()
        self._gif_x_spin.setRange(-9999, 9999)
        self._gif_x_spin.valueChanged.connect(self._on_gif_pos_changed)
        gif_pos_row.addWidget(QLabel("X:"))
        gif_pos_row.addWidget(self._gif_x_spin)
        self._gif_y_spin = QSpinBox()
        self._gif_y_spin.setRange(-9999, 9999)
        self._gif_y_spin.valueChanged.connect(self._on_gif_pos_changed)
        gif_pos_row.addWidget(QLabel("Y:"))
        gif_pos_row.addWidget(self._gif_y_spin)
        prev_layout.addLayout(gif_pos_row)

        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("缩放:"))
        self._gif_scale_spin = QDoubleSpinBox()
        self._gif_scale_spin.setRange(0.1, 3.0)
        self._gif_scale_spin.setSingleStep(0.05)
        self._gif_scale_spin.setValue(1.0)
        self._gif_scale_spin.valueChanged.connect(self._on_gif_scale_changed)
        scale_row.addWidget(self._gif_scale_spin)
        scale_row.addStretch()
        prev_layout.addLayout(scale_row)

        self._gif_lock_cb = QCheckBox("锁定 GIF 位置")
        self._gif_lock_cb.toggled.connect(self._on_gif_lock_toggled)
        prev_layout.addWidget(self._gif_lock_cb)

        reset_pos_btn = QPushButton("重置位置 (0, 0)")
        reset_pos_btn.clicked.connect(self._reset_gif_position)
        prev_layout.addWidget(reset_pos_btn)

        panel_layout.addWidget(self._preview_group)

        # Text content
        text_group = QGroupBox("文字内容")
        text_layout = QVBoxLayout(text_group)
        tmpl_row = QHBoxLayout()
        tmpl_row.addWidget(QLabel("文字:"))
        self._text_tmpl_edit = QLineEdit(self._text_layer.text_template)
        self._text_tmpl_edit.setPlaceholderText("{地区} 将被替换为地区名")
        self._text_tmpl_edit.textChanged.connect(self._on_text_changed)
        tmpl_row.addWidget(self._text_tmpl_edit)
        text_layout.addLayout(tmpl_row)

        add_btn = QPushButton("+ 添加文字到 GIF")
        add_btn.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white; font-size: 13px; "
            "font-weight: bold; padding: 8px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2980b9; }"
        )
        add_btn.clicked.connect(self._add_text)
        text_layout.addWidget(add_btn)

        del_btn = QPushButton("删除文字")
        del_btn.setStyleSheet("QPushButton { color: #e74c3c; font-size: 11px; }")
        del_btn.clicked.connect(self._remove_text)
        text_layout.addWidget(del_btn)
        panel_layout.addWidget(text_group)

        # Font settings
        font_group = QGroupBox("字体设置")
        font_layout = QVBoxLayout(font_group)

        ff_row = QHBoxLayout()
        ff_row.addWidget(QLabel("字体:"))
        self._font_combo = QComboBox()
        self._font_combo.addItems(_FONT_DISPLAY_NAMES)
        idx = self._font_combo.findText("微软雅黑")
        if idx >= 0:
            self._font_combo.setCurrentIndex(idx)
        self._font_combo.currentTextChanged.connect(self._on_font_changed)
        ff_row.addWidget(self._font_combo, 1)
        font_layout.addLayout(ff_row)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("字号:"))
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 200)
        self._font_size_spin.setValue(48)
        self._font_size_spin.valueChanged.connect(self._on_style_changed)
        size_row.addWidget(self._font_size_spin)
        size_row.addStretch()
        font_layout.addLayout(size_row)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("颜色:"))
        self._fill_color_btn = QPushButton()
        self._fill_color_btn.setFixedSize(28, 28)
        self._fill_color_btn.setStyleSheet(
            f"background-color: {self._text_layer.fill_color}; border: 2px solid #ccc; border-radius: 3px;"
        )
        self._fill_color_btn.clicked.connect(lambda: self._pick_color("fill"))
        color_row.addWidget(self._fill_color_btn)
        color_row.addStretch()
        color_row.addWidget(QLabel("透明度:"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(10, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        color_row.addWidget(self._opacity_slider, 1)
        font_layout.addLayout(color_row)

        panel_layout.addWidget(font_group)

        # Effects
        effects_group = QGroupBox("文字特效")
        effects_layout = QVBoxLayout(effects_group)

        stroke_row = QHBoxLayout()
        self._stroke_cb = QCheckBox("描边")
        self._stroke_cb.toggled.connect(self._on_style_changed)
        stroke_row.addWidget(self._stroke_cb)
        self._stroke_width_spin = QSpinBox()
        self._stroke_width_spin.setRange(1, 15)
        self._stroke_width_spin.setValue(3)
        self._stroke_width_spin.valueChanged.connect(self._on_style_changed)
        stroke_row.addWidget(QLabel("宽:"))
        stroke_row.addWidget(self._stroke_width_spin)
        self._stroke_color_btn = QPushButton()
        self._stroke_color_btn.setFixedSize(22, 22)
        self._stroke_color_btn.setStyleSheet(
            f"background-color: {self._text_layer.stroke_color}; border: 1px solid #999;"
        )
        self._stroke_color_btn.clicked.connect(lambda: self._pick_color("stroke"))
        stroke_row.addWidget(self._stroke_color_btn)
        stroke_row.addStretch()
        effects_layout.addLayout(stroke_row)

        shadow_row = QHBoxLayout()
        self._shadow_cb = QCheckBox("阴影")
        self._shadow_cb.toggled.connect(self._on_style_changed)
        shadow_row.addWidget(self._shadow_cb)
        shadow_row.addStretch()
        effects_layout.addLayout(shadow_row)

        grad_row = QHBoxLayout()
        self._gradient_cb = QCheckBox("渐变色")
        self._gradient_cb.toggled.connect(self._on_style_changed)
        grad_row.addWidget(self._gradient_cb)
        grad_row.addStretch()
        effects_layout.addLayout(grad_row)

        self._bg_enabled_cb = QCheckBox("文字底色框")
        self._bg_enabled_cb.toggled.connect(self._on_style_changed)
        effects_layout.addWidget(self._bg_enabled_cb)

        panel_layout.addWidget(effects_group)

        # Text position
        pos_group = QGroupBox("文字位置")
        pos_layout = QVBoxLayout(pos_group)
        pos_row = QHBoxLayout()
        self._x_spin = QSpinBox()
        self._x_spin.setRange(-9999, 9999)
        self._x_spin.valueChanged.connect(self._on_pos_spin)
        pos_row.addWidget(QLabel("X:"))
        pos_row.addWidget(self._x_spin)
        self._y_spin = QSpinBox()
        self._y_spin.setRange(-9999, 9999)
        self._y_spin.valueChanged.connect(self._on_pos_spin)
        pos_row.addWidget(QLabel("Y:"))
        pos_row.addWidget(self._y_spin)
        pos_layout.addLayout(pos_row)
        self._center_h_cb = QCheckBox("水平居中")
        self._center_h_cb.setChecked(self._text_layer.center_horizontal)
        self._center_h_cb.toggled.connect(self._on_center_h_toggled)
        pos_layout.addWidget(self._center_h_cb)

        self._lock_cb = QCheckBox("锁定位置")
        self._lock_cb.toggled.connect(self._on_lock_toggled)
        pos_layout.addWidget(self._lock_cb)
        panel_layout.addWidget(pos_group)

        # Template quick select
        tmpl_group = QGroupBox("快速套用模板")
        tmpl_layout = QVBoxLayout(tmpl_group)
        self._tmpl_combo = QComboBox()
        self._tmpl_combo.addItem("-- 选择模板 --")
        for t in self._template_mgr.get_all_templates():
            self._tmpl_combo.addItem(f"{t.category[:4]}: {t.template_name}", t.template_id)
        self._tmpl_combo.currentIndexChanged.connect(self._on_template_selected)
        tmpl_layout.addWidget(self._tmpl_combo)
        panel_layout.addWidget(tmpl_group)

        panel_layout.addStretch()
        main_layout.addWidget(panel)

        self._canvas.frame_changed.connect(self._on_frame_changed)
        self._canvas.gif_position_changed.connect(self._on_canvas_gif_moved)
        self._canvas.zoom_changed.connect(lambda v: self._zoom_label.setText(f"{v}%"))

    # === Public API ===
    def load_gif(self, gif_path: str):
        self._decoder = GifFrameDecoder()
        self._decoder.load(gif_path)
        self._canvas.set_decoder(self._decoder)
        self._canvas.zoom_fit()
        self._update_gif_info_label()

    def set_video_path(self, video_path: str):
        self._video_path = video_path
        self._preview_btn.setEnabled(bool(video_path))

    def get_text_layer(self) -> TextLayerModel:
        self._sync_text_from_item()
        return self._text_layer

    def get_gif_overlay_info(self) -> dict:
        """Return GIF overlay geometry for video composition (persistent)."""
        return {
            "x": self._overlay_x, "y": self._overlay_y,
            "scale_x": self._overlay_scale, "scale_y": self._overlay_scale,
        }

    def apply_template(self, template: dict):
        style = template if "style" not in template else template.get("style", template)
        self._text_layer.template_id = template.get("template_id", "")
        self._text_layer.font_family = style.get("font_family", "Microsoft YaHei")
        self._text_layer.font_size = style.get("font_size", 48)
        self._text_layer.fill_color = style.get("fill_color", "#FFFFFF")
        self._text_layer.stroke_enabled = style.get("stroke_enabled", False)
        self._text_layer.stroke_color = style.get("stroke_color", "#000000")
        self._text_layer.stroke_width = style.get("stroke_width", 3)
        self._text_layer.shadow_enabled = style.get("shadow_enabled", False)
        self._text_layer.shadow_color = style.get("shadow_color", "#000000")
        self._text_layer.shadow_offset_x = style.get("shadow_offset_x", 3)
        self._text_layer.shadow_offset_y = style.get("shadow_offset_y", 3)
        self._text_layer.shadow_blur = style.get("shadow_blur", 4)
        self._text_layer.gradient_enabled = style.get("gradient_enabled", False)
        self._text_layer.gradient_start = style.get("gradient_start", "#FFFFFF")
        self._text_layer.gradient_end = style.get("gradient_end", "#FFD700")
        self._text_layer.background_enabled = style.get("background_enabled", False)
        self._text_layer.background_color = style.get("background_color", "#000000")
        self._text_layer.background_radius = style.get("background_radius", 12)
        self._text_layer.opacity = style.get("opacity", 1.0)

        self._sync_ui_from_layer()
        if self._text_item is None:
            self._add_text()
        else:
            self._render_preview()

    # === Preview mode ===
    def _toggle_preview(self, checked: bool):
        if checked:
            self._enter_preview_mode()
        else:
            self._exit_preview_mode()

    def _enter_preview_mode(self):
        if not self._video_path or not os.path.isfile(self._video_path):
            self._preview_btn.setChecked(False)
            return

        tmp_dir = tempfile.gettempdir()
        self._preview_frame_path = os.path.join(tmp_dir, "_rbvt_preview_frame.png")
        ok = self._ffmpeg.extract_first_frame(self._video_path, self._preview_frame_path)
        if not ok:
            self._preview_btn.setChecked(False)
            return

        self._canvas.set_preview_background(self._preview_frame_path)
        self._canvas.zoom_fit()
        self._preview_group.setVisible(True)
        self._bg_combo.setEnabled(False)

        # Restore saved position (not reset!)
        self._canvas.set_gif_position(self._overlay_x, self._overlay_y)
        self._canvas.set_gif_scale(self._overlay_scale, self._overlay_scale)
        self._gif_x_spin.blockSignals(True)
        self._gif_x_spin.setValue(self._overlay_x)
        self._gif_x_spin.blockSignals(False)
        self._gif_y_spin.blockSignals(True)
        self._gif_y_spin.setValue(self._overlay_y)
        self._gif_y_spin.blockSignals(False)
        self._gif_scale_spin.blockSignals(True)
        self._gif_scale_spin.setValue(self._overlay_scale)
        self._gif_scale_spin.blockSignals(False)

    def _exit_preview_mode(self):
        self._canvas.set_preview_background(None)
        self._preview_group.setVisible(False)
        self._bg_combo.setEnabled(True)
        self._bg_combo.setCurrentIndex(0)
        # Keep overlay position persistent — do NOT reset!

        if self._preview_frame_path and os.path.isfile(self._preview_frame_path):
            try:
                os.remove(self._preview_frame_path)
            except Exception:
                pass
            self._preview_frame_path = ""

    def _on_gif_pos_changed(self):
        self._overlay_x = self._gif_x_spin.value()
        self._overlay_y = self._gif_y_spin.value()
        self._canvas.set_gif_position(self._overlay_x, self._overlay_y)

    def _on_gif_scale_changed(self, val: float):
        self._overlay_scale = val
        self._canvas.set_gif_scale(val, val)

    def _on_canvas_gif_moved(self, x: float, y: float):
        """Sync spin boxes when GIF is dragged on canvas."""
        self._overlay_x = int(x)
        self._overlay_y = int(y)
        self._gif_x_spin.blockSignals(True)
        self._gif_x_spin.setValue(int(x))
        self._gif_x_spin.blockSignals(False)
        self._gif_y_spin.blockSignals(True)
        self._gif_y_spin.setValue(int(y))
        self._gif_y_spin.blockSignals(False)

    def _on_gif_lock_toggled(self, locked: bool):
        self._canvas.set_gif_locked(locked)

    def _reset_gif_position(self):
        self._gif_x_spin.setValue(0)
        self._gif_y_spin.setValue(0)
        self._gif_scale_spin.setValue(1.0)

    # === Internal ===
    def _update_gif_info_label(self):
        if not self._decoder:
            return
        gif_w, gif_h = self._decoder.get_size()
        fc = self._decoder.get_frame_count()
        dur = self._decoder.get_total_duration_ms() / 1000.0
        self._frame_label.setText(f"帧: 0/{fc}")
        self._gif_size_label.setText(f"{gif_w}×{gif_h} | {fc}帧 | {dur:.1f}s")

    def _sync_ui_from_layer(self):
        self._font_size_spin.blockSignals(True)
        self._font_size_spin.setValue(self._text_layer.font_size)
        self._font_size_spin.blockSignals(False)
        self._stroke_cb.setChecked(self._text_layer.stroke_enabled)
        self._stroke_width_spin.setValue(self._text_layer.stroke_width)
        self._shadow_cb.setChecked(self._text_layer.shadow_enabled)
        self._gradient_cb.setChecked(self._text_layer.gradient_enabled)
        self._bg_enabled_cb.setChecked(self._text_layer.background_enabled)
        self._x_spin.blockSignals(True)
        self._x_spin.setValue(int(self._text_layer.x))
        self._x_spin.blockSignals(False)
        self._y_spin.blockSignals(True)
        self._y_spin.setValue(int(self._text_layer.y))
        self._y_spin.blockSignals(False)
        self._opacity_slider.setValue(int(self._text_layer.opacity * 100))
        self._update_color_buttons()

    def _toggle_play(self):
        if self._canvas.is_playing():
            self._canvas.pause()
            self._play_btn.setText("▶ 播放")
        else:
            self._canvas.play()
            self._play_btn.setText("⏸ 暂停")

    def _on_frame_changed(self, current: int, total: int):
        self._frame_label.setText(f"帧: {current}/{total}")

    def _on_bg_changed(self, idx: int):
        modes = ["checkerboard", "black", "white"]
        if idx < len(modes):
            self._canvas.set_background_mode(modes[idx])

    def _on_text_changed(self, text: str):
        self._text_layer.text_template = text
        self._render_preview()

    def _on_font_changed(self, font_name: str):
        self._text_layer.font_family = font_name
        self._text_layer.font_path = _SYSTEM_FONTS.get(font_name)
        self._render_preview()

    def _on_style_changed(self):
        self._text_layer.font_size = self._font_size_spin.value()
        self._text_layer.stroke_enabled = self._stroke_cb.isChecked()
        self._text_layer.stroke_width = self._stroke_width_spin.value()
        self._text_layer.shadow_enabled = self._shadow_cb.isChecked()
        self._text_layer.gradient_enabled = self._gradient_cb.isChecked()
        self._text_layer.background_enabled = self._bg_enabled_cb.isChecked()
        self._render_preview()

    def _on_opacity_changed(self, val: int):
        self._text_layer.opacity = val / 100.0
        self._render_preview()

    def _pick_color(self, target: str):
        if target == "fill":
            current = QColor(self._text_layer.fill_color)
        else:
            current = QColor(self._text_layer.stroke_color)
        color = QColorDialog.getColor(current, self, "选择颜色")
        if color.isValid():
            if target == "fill":
                self._text_layer.fill_color = color.name()
            else:
                self._text_layer.stroke_color = color.name()
            self._update_color_buttons()
            self._render_preview()

    def _update_color_buttons(self):
        self._fill_color_btn.setStyleSheet(
            f"background-color: {self._text_layer.fill_color}; border: 2px solid #ccc; border-radius: 3px;"
        )
        self._stroke_color_btn.setStyleSheet(
            f"background-color: {self._text_layer.stroke_color}; border: 1px solid #999;"
        )

    def _on_pos_spin(self):
        self._text_layer.x = self._x_spin.value()
        self._text_layer.y = self._y_spin.value()
        if self._text_item:
            self._text_item.setPos(self._text_layer.x, self._text_layer.y)
            self.text_layer_changed.emit(self._text_layer)

    def _on_center_h_toggled(self, checked: bool):
        self._text_layer.center_horizontal = checked
        if checked and self._text_item:
            self._recenter_text()

    def _on_lock_toggled(self, locked: bool):
        if self._text_item:
            self._text_item.set_locked(locked)

    def _on_template_selected(self, idx: int):
        if idx <= 0:
            return
        tid = self._tmpl_combo.currentData()
        tmpl = self._template_mgr.get_template(tid)
        if tmpl:
            self.apply_template(tmpl.style)
            self._tmpl_combo.blockSignals(True)
            self._tmpl_combo.setCurrentIndex(0)
            self._tmpl_combo.blockSignals(False)

    def _add_text(self):
        if not self._decoder:
            return

        pixmap = self._render_text_pixmap(self._text_layer.text_template)
        if pixmap is None or pixmap.isNull():
            logger.error("Failed to render text pixmap")
            return

        if self._text_item:
            self._canvas.remove_text_item()
            self._text_item = None

        self._text_item = DraggableTextItem(pixmap, self._text_layer.text_template)
        self._text_item.position_changed.connect(self._on_item_moved)
        gif_item = self._canvas.get_gif_item()
        self._canvas.add_text_item(self._text_item, parent_item=gif_item)

        gif_w, gif_h = self._decoder.get_size()
        x = max(0, (gif_w - pixmap.width()) / 2)
        y = max(0, (gif_h - pixmap.height()) / 2)
        self._text_item.setPos(x, y)
        self._text_layer.x = x
        self._text_layer.y = y
        self._x_spin.blockSignals(True)
        self._x_spin.setValue(int(x))
        self._x_spin.blockSignals(False)
        self._y_spin.blockSignals(True)
        self._y_spin.setValue(int(y))
        self._y_spin.blockSignals(False)

        self.text_layer_changed.emit(self._text_layer)

    def _remove_text(self):
        if self._text_item:
            self._canvas.remove_text_item()
            self._text_item = None
            self.text_layer_changed.emit(self._text_layer)

    def _render_preview(self):
        if not self._text_item:
            return
        pixmap = self._render_text_pixmap(self._text_layer.text_template)
        if pixmap and not pixmap.isNull():
            self._text_item.update_pixmap(pixmap)
        if self._text_layer.center_horizontal:
            self._recenter_text()
        self.text_layer_changed.emit(self._text_layer)

    def _recenter_text(self):
        """Re-center text horizontally on the GIF/video."""
        if not self._text_item or not self._decoder:
            return
        pixmap = self._text_item._pixmap
        if pixmap is None or pixmap.isNull():
            return
        gif_w, gif_h = self._decoder.get_size()
        x = max(0, (gif_w - pixmap.width()) / 2)
        self._text_item.setPos(x, self._text_layer.y)
        self._text_layer.x = x
        self._x_spin.blockSignals(True)
        self._x_spin.setValue(int(x))
        self._x_spin.blockSignals(False)

    def _render_text_pixmap(self, text: str) -> QPixmap | None:
        try:
            img = self._render_service.render_text(text, self._text_layer)
            if img is None:
                return None
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            return QPixmap.fromImage(qimg.copy())
        except Exception as e:
            logger.error(f"Render text failed: {e}")
            return None

    def _on_item_moved(self, x: float, y: float):
        if self._text_layer.center_horizontal and self._text_item and self._decoder:
            # In centered mode, only Y is draggable; X stays centered
            pixmap = self._text_item._pixmap
            if pixmap:
                gif_w = self._decoder.get_size()[0]
                x = max(0, (gif_w - pixmap.width()) / 2)
        self._text_layer.x = x
        self._text_layer.y = y
        self._x_spin.blockSignals(True)
        self._x_spin.setValue(int(x))
        self._x_spin.blockSignals(False)
        self._y_spin.blockSignals(True)
        self._y_spin.setValue(int(y))
        self._y_spin.blockSignals(False)
        self.text_layer_changed.emit(self._text_layer)

    def _sync_text_from_item(self):
        if self._text_item:
            self._text_layer.x = self._text_item.x()
            self._text_layer.y = self._text_item.y()

    def has_text(self) -> bool:
        return self._text_item is not None
