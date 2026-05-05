import json
import os
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QGroupBox,
    QColorDialog, QLineEdit, QFormLayout, QSlider, QDialog,
    QDialogButtonBox, QTextEdit, QScrollArea, QGridLayout,
)
from PySide6.QtCore import Qt, Signal, QRectF, QEvent
from PySide6.QtGui import QPixmap, QImage, QColor

from core.font_style_analyzer import (
    analyze_text_style as analyze_font_style,
    generate_style_id, save_style_json, style_to_text_layer,
)
from core.file_manager import get_custom_styles_dir
from core.font_manager import get_font_manager
from ui.font_picker_dialog import FontPickerDialog
from ui.style_preview_dialog import StylePreviewDialog
from core.gif_frame_decoder import GifFrameDecoder
from core.text_render_service import TextRenderService
from core.template_manager import TemplateManager
from core.ffmpeg_service import FFmpegService
from models.text_layer_model import TextLayerModel
from ui.gif_canvas_view import GifCanvasView
from ui.draggable_text_item import DraggableTextItem
from utils.logger import get_logger

logger = get_logger()

# ---- Presets ----
PRESET_LIST: list[tuple[str, str]] = [
    ("preset_yellow_black", "黄字黑边"),
    ("preset_white_black", "白字黑边"),
    ("preset_red_white", "红字白边"),
    ("preset_black_white_bg", "黑字白底"),
    ("preset_white_black_bg", "白字黑底"),
    ("preset_red_white_bg", "红底白字"),
    ("preset_factory_ad", "工厂广告标题"),
    ("preset_contact", "联系方式"),
]

PRESET_STYLES: dict[str, dict] = {
    "preset_yellow_black": {"font_size": 72, "bold": True, "fill_color": "#FFD700",
        "stroke_enabled": True, "stroke_color": "#000000", "stroke_width": 8,
        "shadow_enabled": True, "shadow_color": "#000000", "shadow_opacity": 0.5,
        "shadow_offset_x": 3, "shadow_offset_y": 3, "shadow_blur": 4,
        "background_enabled": False, "border_enabled": False},
    "preset_white_black": {"font_size": 72, "bold": True, "fill_color": "#FFFFFF",
        "stroke_enabled": True, "stroke_color": "#000000", "stroke_width": 6,
        "shadow_enabled": True, "shadow_color": "#000000", "shadow_opacity": 0.4,
        "shadow_offset_x": 2, "shadow_offset_y": 2, "shadow_blur": 3,
        "background_enabled": False, "border_enabled": False},
    "preset_red_white": {"font_size": 70, "bold": True, "fill_color": "#FF3333",
        "stroke_enabled": True, "stroke_color": "#FFFFFF", "stroke_width": 5,
        "shadow_enabled": False, "background_enabled": False, "border_enabled": False},
    "preset_black_white_bg": {"font_size": 56, "bold": True, "fill_color": "#000000",
        "stroke_enabled": False, "shadow_enabled": False,
        "background_enabled": True, "background_color": "#FFFFFF", "background_opacity": 0.85,
        "background_radius": 8, "background_padding": 10, "border_enabled": False},
    "preset_white_black_bg": {"font_size": 60, "bold": True, "fill_color": "#FFFFFF",
        "stroke_enabled": True, "stroke_color": "#000000", "stroke_width": 3,
        "shadow_enabled": False,
        "background_enabled": True, "background_color": "#000000", "background_opacity": 0.7,
        "background_radius": 8, "background_padding": 10, "border_enabled": False},
    "preset_red_white_bg": {"font_size": 64, "bold": True, "fill_color": "#FFFFFF",
        "stroke_enabled": True, "stroke_color": "#CC0000", "stroke_width": 4,
        "shadow_enabled": False,
        "background_enabled": True, "background_color": "#FF0000", "background_opacity": 0.9,
        "background_radius": 6, "background_padding": 12, "border_enabled": False},
    "preset_factory_ad": {"font_size": 68, "bold": True, "fill_color": "#FFD700",
        "stroke_enabled": True, "stroke_color": "#FF0000", "stroke_width": 6,
        "shadow_enabled": True, "shadow_color": "#990000", "shadow_opacity": 0.6,
        "shadow_offset_x": 4, "shadow_offset_y": 4, "shadow_blur": 5,
        "background_enabled": True, "background_color": "#000000", "background_opacity": 0.5,
        "background_radius": 10, "background_padding": 14, "border_enabled": False},
    "preset_contact": {"font_size": 48, "bold": False, "fill_color": "#FFFFFF",
        "stroke_enabled": True, "stroke_color": "#333333", "stroke_width": 3,
        "shadow_enabled": False,
        "background_enabled": True, "background_color": "#000000", "background_opacity": 0.55,
        "background_radius": 6, "background_padding": 8, "border_enabled": False},
}

# Button styles used in panel + handlers
BTN_CHECKED_STYLE = (
    "QPushButton { background: #3498db; color: #fff; border: 1px solid #2980b9; "
    "padding: 3px 10px; border-radius: 3px; font-size: 11px; }"
)
BTN_UNCHECKED_STYLE = (
    "QPushButton { background: #fff; color: #555; border: 1px solid #dcdde1; "
    "padding: 3px 10px; border-radius: 3px; font-size: 11px; }"
    "QPushButton:hover { background: #ecf0f1; }"
)

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
        self._undo_stack: list[TextLayerModel] = []
        self._render_service = TextRenderService()
        self._template_mgr = TemplateManager()
        self._font_mgr = get_font_manager()
        self._ffmpeg = FFmpegService()
        self._video_path: str = ""
        self._preview_frame_path: str = ""
        self._gif_path: str = ""
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

        self._box_select_btn = QPushButton("⬜ 框选文字")
        self._box_select_btn.setCheckable(True)
        self._box_select_btn.setStyleSheet(
            "QPushButton { color: #ecf0f1; background: #2980b9; padding: 4px 12px; "
            "border-radius: 3px; } QPushButton:checked { background: #e74c3c; }"
        )
        self._box_select_btn.clicked.connect(self._toggle_box_select)
        toolbar_layout.addWidget(self._box_select_btn)

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

        # ========== Right Panel (scrollable) ==========
        GROUP_STYLE = (
            "QGroupBox { font-weight: bold; color: #2c3e50; border: 1px solid #dcdde1; "
            "border-radius: 6px; margin-top: 8px; padding-top: 16px; background: #fff; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #2c3e50; }"
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f5f6fa; }")

        panel = QWidget()
        panel.setStyleSheet("background-color: #f5f6fa;")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(6)
        panel_layout.setContentsMargins(10, 8, 10, 12)

        def _styled_group(title: str) -> QGroupBox:
            g = QGroupBox(title)
            g.setStyleSheet(GROUP_STYLE)
            return g

        def _color_btn(hex_color: str, width: int = 52) -> QPushButton:
            btn = QPushButton(hex_color)
            btn.setFixedSize(width, 22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {hex_color}; border: 1px solid #bdc3c7; "
                f"border-radius: 3px; font-size: 9px; color: #fff; text-shadow: 0 0 2px #000; }}"
            )
            return btn

        def _spin(min_v: int, max_v: int, val: int, w: int = 80) -> QSpinBox:
            s = QSpinBox()
            s.setRange(min_v, max_v)
            s.setValue(val)
            s.setFixedWidth(w)
            s.wheelEvent = lambda e: e.ignore()  # block mouse wheel
            return s

        def _dslider(min_v: int, max_v: int, val: int) -> QSlider:
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(min_v, max_v)
            sl.setValue(val)
            return sl

        # ---------------------------------------------------------------
        # PRESETS
        # ---------------------------------------------------------------
        presets_group = _styled_group("快捷预设 ▸ 一键套用")
        presets_lo = QVBoxLayout(presets_group)
        presets_lo.setSpacing(4)
        self._preset_btns: list[QPushButton] = []
        preset_grid = QHBoxLayout()
        preset_grid.setSpacing(4)
        for i, (pid, pname) in enumerate(PRESET_LIST):
            btn = QPushButton(pname)
            btn.setToolTip(f"套用「{pname}」预设")
            btn.setStyleSheet(BTN_UNCHECKED_STYLE)
            btn.clicked.connect(lambda checked, p=pid: self._on_preset(p))
            self._preset_btns.append(btn)
            preset_grid.addWidget(btn)
            if (i + 1) % 4 == 0:
                presets_lo.addLayout(preset_grid)
                preset_grid = QHBoxLayout()
                preset_grid.setSpacing(4)
        if preset_grid.count() > 0:
            presets_lo.addLayout(preset_grid)
        panel_layout.addWidget(presets_group)

        # ---------------------------------------------------------------
        # TEMPLATES & BOX-STYLES (moved after presets)
        # ---------------------------------------------------------------
        tmpl_group = _styled_group("快速套用模板")
        tmpl_lo = QVBoxLayout(tmpl_group)
        self._tmpl_pinned: set[str] = set()
        self._tmpl_combo = None  # replaced by preview button
        tmpl_preview_btn = QPushButton("👁 选择模板样式")
        tmpl_preview_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 8px 12px; border: 1px solid #3498db; "
            "border-radius: 4px; color: #3498db; background: #fff; font-weight: bold; }"
            "QPushButton:hover { background: #3498db; color: #fff; }"
        )
        tmpl_preview_btn.clicked.connect(self._show_template_preview)
        tmpl_lo.addWidget(tmpl_preview_btn)
        panel_layout.addWidget(tmpl_group)

        self._box_styles: list[dict] = []
        self._box_pinned: set[str] = set()
        box_group = _styled_group("框选识别的花字")
        box_lo = QVBoxLayout(box_group)
        self._box_combo = None
        box_preview_btn = QPushButton("👁 选择框选样式")
        box_preview_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 8px 12px; border: 1px solid #e67e22; "
            "border-radius: 4px; color: #e67e22; background: #fff; font-weight: bold; }"
            "QPushButton:hover { background: #e67e22; color: #fff; }"
        )
        box_preview_btn.clicked.connect(self._show_box_preview)
        box_lo.addWidget(box_preview_btn)
        panel_layout.addWidget(box_group)

        # Context menus removed with combos — use preview dialog instead

        # ---------------------------------------------------------------
        # CONTENT
        # ---------------------------------------------------------------
        content_group = _styled_group("内容")
        c_lo = QVBoxLayout(content_group)
        c_lo.setSpacing(4)
        self._text_tmpl_edit = QLineEdit(self._text_layer.text_template)
        self._text_tmpl_edit.setPlaceholderText("支持多行 / 变量 {地区}")
        self._text_tmpl_edit.textChanged.connect(self._on_text_changed)
        self._text_tmpl_edit.setStyleSheet("QLineEdit { padding: 4px 6px; border: 1px solid #dcdde1; border-radius: 3px; font-size: 12px; }")
        c_lo.addWidget(self._text_tmpl_edit)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ 添加到 GIF")
        add_btn.setStyleSheet("QPushButton { background: #3498db; color: #fff; font-size: 12px; font-weight: bold; padding: 5px 12px; border-radius: 3px; } QPushButton:hover { background: #2980b9; }")
        add_btn.clicked.connect(self._add_text)
        btn_row.addWidget(add_btn)
        del_btn = QPushButton("删除文字")
        del_btn.setStyleSheet("QPushButton { color: #e74c3c; font-size: 11px; padding: 5px 10px; } QPushButton:hover { color: #c0392b; }")
        del_btn.clicked.connect(self._remove_text)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        c_lo.addLayout(btn_row)
        panel_layout.addWidget(content_group)

        # ---------------------------------------------------------------
        # FONT (enhanced with FontPicker, weight, quick sizes)
        # ---------------------------------------------------------------
        font_group = _styled_group("字体")
        f_lo = QVBoxLayout(font_group)
        f_lo.setSpacing(4)

        # Font picker button (replaces QComboBox)
        ff_row = QHBoxLayout(); ff_row.setSpacing(6)
        ff_row.addWidget(QLabel("字体"))
        self._font_btn = QPushButton(self._text_layer.font_family)
        self._font_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 4px 8px; border: 1px solid #dcdde1; "
            "border-radius: 3px; background: #fff; font-size: 11px; }"
            "QPushButton:hover { border-color: #3498db; }"
        )
        self._font_btn.clicked.connect(self._open_font_picker)
        ff_row.addWidget(self._font_btn, 1)
        f_lo.addLayout(ff_row)

        # Size + weight row
        f2_row = QHBoxLayout(); f2_row.setSpacing(4)
        f2_row.addWidget(QLabel("字号"))
        self._font_size_spin = _spin(10, 300, 72, 84)
        self._font_size_spin.valueChanged.connect(self._on_style_changed)
        f2_row.addWidget(self._font_size_spin)
        f2_row.addSpacing(4)
        f2_row.addWidget(QLabel("字重"))
        self._weight_spin = _spin(100, 9999, 700, 82)
        self._weight_spin.setSingleStep(100)
        self._weight_spin.valueChanged.connect(self._on_weight_changed)
        f2_row.addWidget(self._weight_spin)
        f2_row.addStretch()
        f_lo.addLayout(f2_row)

        # Quick size buttons
        qs_row = QHBoxLayout(); qs_row.setSpacing(2)
        for sz in [24, 36, 48, 60, 72, 96, 120, 150, 180]:
            btn = QPushButton(str(sz))
            btn.setFixedSize(32, 18)
            btn.setStyleSheet("QPushButton { font-size: 9px; padding: 0; border: 1px solid #dcdde1; border-radius: 2px; background: #fff; } QPushButton:hover { background: #3498db; color: #fff; }")
            btn.clicked.connect(lambda checked, s=sz: self._set_font_size(s))
            qs_row.addWidget(btn)
        qs_row.addStretch()
        f_lo.addLayout(qs_row)

        # Color row + palette quick picks
        fc_row = QHBoxLayout(); fc_row.setSpacing(6)
        fc_row.addWidget(QLabel("颜色"))
        self._fill_color_btn = _color_btn(self._text_layer.fill_color, 52)
        self._fill_color_btn.clicked.connect(lambda: self._pick_color("fill"))
        fc_row.addWidget(self._fill_color_btn)
        fc_row.addStretch()
        palette_btn = QPushButton("▾ 色板")
        palette_btn.setStyleSheet("QPushButton { font-size: 10px; padding: 2px 6px; border: 1px solid #dcdde1; border-radius: 3px; background: #fff; } QPushButton:hover { background: #ecf0f1; }")
        palette_btn.clicked.connect(self._show_color_palette)
        fc_row.addWidget(palette_btn)
        f_lo.addLayout(fc_row)

        # Spacing & alignment
        f3_row = QHBoxLayout(); f3_row.setSpacing(6)
        f3_row.addWidget(QLabel("字距")); self._letter_spin = _spin(-10, 50, 0, 78)
        self._letter_spin.valueChanged.connect(self._on_style_changed); f3_row.addWidget(self._letter_spin)
        f3_row.addSpacing(6)
        f3_row.addWidget(QLabel("行距")); self._line_spin = _spin(0, 100, 8, 78)
        self._line_spin.valueChanged.connect(self._on_style_changed); f3_row.addWidget(self._line_spin)
        f3_row.addStretch()
        f_lo.addLayout(f3_row)

        align_row = QHBoxLayout(); align_row.setSpacing(4)
        align_row.addWidget(QLabel("对齐"))
        self._align_btns: dict[str, QPushButton] = {}
        for ak, al in [("left", "⬅左"), ("center", "■中"), ("right", "右➡")]:
            btn = QPushButton(al); btn.setCheckable(True)
            btn.setStyleSheet(BTN_UNCHECKED_STYLE)
            btn.clicked.connect(lambda checked, a=ak: self._on_align(a))
            self._align_btns[ak] = btn; align_row.addWidget(btn)
        self._align_btns["center"].setChecked(True)
        align_row.addStretch()
        f_lo.addLayout(align_row)
        panel_layout.addWidget(font_group)

        # ---------------------------------------------------------------
        # GRADIENT (dedicated section)
        # ---------------------------------------------------------------
        grad_group = _styled_group("渐变")
        grad_lo = QVBoxLayout(grad_group); grad_lo.setSpacing(4)

        self._grad_cb = QCheckBox("启用渐变")
        self._grad_cb.setChecked(self._text_layer.gradient_enabled)
        self._grad_cb.toggled.connect(self._on_style_changed)
        grad_lo.addWidget(self._grad_cb)

        # Type: linear / radial
        gt_row = QHBoxLayout(); gt_row.setSpacing(6)
        gt_row.addWidget(QLabel("类型"))
        self._grad_type_combo = QComboBox()
        self._grad_type_combo.addItems(["线性渐变", "径向渐变"])
        self._grad_type_combo.currentIndexChanged.connect(self._on_grad_type_changed)
        gt_row.addWidget(self._grad_type_combo, 1)
        grad_lo.addLayout(gt_row)

        # Start + End colors
        gc_row = QHBoxLayout(); gc_row.setSpacing(6)
        gc_row.addWidget(QLabel("起始"))
        self._grad_start_btn = _color_btn(self._text_layer.gradient_start, 48)
        self._grad_start_btn.clicked.connect(lambda: self._pick_color("gradient_start"))
        gc_row.addWidget(self._grad_start_btn)
        gc_row.addWidget(QLabel("结束"))
        self._grad_end_btn = _color_btn(self._text_layer.gradient_end, 48)
        self._grad_end_btn.clicked.connect(lambda: self._pick_color("gradient_end"))
        gc_row.addWidget(self._grad_end_btn)
        grad_lo.addLayout(gc_row)
        # Mid color
        gmidc_row = QHBoxLayout(); gmidc_row.setSpacing(6)
        gmidc_row.addWidget(QLabel("中间"))
        self._grad_mid_btn = _color_btn("", 48)
        self._grad_mid_btn.clicked.connect(lambda: self._pick_color("gradient_mid"))
        gmidc_row.addWidget(self._grad_mid_btn)
        gmidc_row.addWidget(QLabel("(可选)"))
        gmidc_row.addStretch()
        grad_lo.addLayout(gmidc_row)

        # Midpoint slider
        gmid_row = QHBoxLayout(); gmid_row.setSpacing(4)
        gmid_row.addWidget(QLabel("渐变范围"))
        self._grad_midpoint_sl = QSlider(Qt.Orientation.Horizontal)
        self._grad_midpoint_sl.setRange(0, 100)
        self._grad_midpoint_sl.setValue(50)
        self._grad_midpoint_sl.valueChanged.connect(self._on_style_changed)
        gmid_row.addWidget(self._grad_midpoint_sl, 1)
        grad_lo.addLayout(gmid_row)

        # Direction (for linear)
        self._grad_dir_row = QHBoxLayout(); self._grad_dir_row.setSpacing(4)
        self._grad_dir_row.addWidget(QLabel("方向"))
        self._grad_dir_combo = QComboBox()
        self._grad_dir_combo.addItems(["上→下", "左→右", "左上→右下", "右上→左下"])
        self._grad_dir_combo.currentIndexChanged.connect(self._on_grad_dir_changed)
        self._grad_dir_row.addWidget(self._grad_dir_combo, 1)
        grad_lo.addLayout(self._grad_dir_row)

        # Preset gradients (3-stop)
        PRESET_GRADIENTS: list[tuple[str, str, str, str]] = [
            ("金橙高亮", "#FF9A00", "#FFC83D", "#FFF3A3"),
            ("红金吸睛", "#D62828", "#F77F00", "#FFD166"),
            ("蓝紫流光", "#3A0CA3", "#4361EE", "#4CC9F0"),
            ("玫红橙亮", "#FF006E", "#FB5607", "#FFBE0B"),
            ("青蓝高亮", "#00C2FF", "#00E5FF", "#A0F8FF"),
            ("紫粉高亮", "#7B2CBF", "#C77DFF", "#FFD6FF"),
            ("黄白高亮", "#F4B400", "#FFD84D", "#FFF6BF"),
            ("绿色活力", "#00B894", "#00CEC9", "#81ECEC"),
            ("橙红爆款", "#FF512F", "#F09819", "#FFE259"),
            ("蓝白清爽", "#007CF0", "#00DFD8", "#FFFFFF"),
        ]
        gpreset_grid = QGridLayout(); gpreset_grid.setSpacing(2)
        for i, (gname, gs, gm, ge) in enumerate(PRESET_GRADIENTS):
            btn = QPushButton(gname)
            btn.setFixedSize(42, 20)
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 9px; padding: 0; border: 1px solid #dcdde1; "
                f"border-radius: 2px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {gs}, stop:0.5 {gm}, stop:1 {ge}); color: #fff; text-shadow: 0 0 2px #000; }}"
                f"QPushButton:hover {{ border: 2px solid #3498db; }}"
            )
            btn.clicked.connect(lambda checked, s=gs, m=gm, e=ge: self._apply_gradient_preset(s, m, e))
            gpreset_grid.addWidget(btn, i // 5, i % 5)
        grad_lo.addLayout(gpreset_grid)

        panel_layout.addWidget(grad_group)

        # ---------------------------------------------------------------
        # STROKE
        # ---------------------------------------------------------------
        stroke_group = _styled_group("描边")
        s_lo = QVBoxLayout(stroke_group); s_lo.setSpacing(4)
        s_enable_row = QHBoxLayout()
        self._stroke_cb = QCheckBox("启用描边"); self._stroke_cb.setChecked(True)
        self._stroke_cb.toggled.connect(self._on_style_changed)
        s_enable_row.addWidget(self._stroke_cb); s_enable_row.addStretch()
        s_lo.addLayout(s_enable_row)
        s_color_row = QHBoxLayout(); s_color_row.setSpacing(6)
        s_color_row.addWidget(QLabel("颜色"))
        self._stroke_color_btn = _color_btn(self._text_layer.stroke_color, 48)
        self._stroke_color_btn.clicked.connect(lambda: self._pick_color("stroke"))
        s_color_row.addWidget(self._stroke_color_btn)
        s_color_row.addSpacing(6)
        s_color_row.addWidget(QLabel("粗细")); self._stroke_width_spin = _spin(0, 30, 8, 74)
        self._stroke_width_spin.valueChanged.connect(self._on_style_changed)
        s_color_row.addWidget(self._stroke_width_spin); s_color_row.addWidget(QLabel("px"))
        s_color_row.addStretch()
        s_lo.addLayout(s_color_row)

        # Stroke opacity
        sop_row = QHBoxLayout(); sop_row.setSpacing(6)
        sop_row.addWidget(QLabel("不透明度"))
        self._stroke_opacity_sl = QSlider(Qt.Orientation.Horizontal)
        self._stroke_opacity_sl.setRange(5, 100)
        self._stroke_opacity_sl.setValue(100)
        self._stroke_opacity_sl.valueChanged.connect(self._on_style_changed)
        sop_row.addWidget(self._stroke_opacity_sl, 1)
        s_lo.addLayout(sop_row)
        panel_layout.addWidget(stroke_group)

        # ---------------------------------------------------------------
        # SHADOW
        # ---------------------------------------------------------------
        shadow_group = _styled_group("阴影")
        sh_lo = QVBoxLayout(shadow_group); sh_lo.setSpacing(4)
        self._shadow_cb = QCheckBox("启用阴影"); self._shadow_cb.setChecked(True)
        self._shadow_cb.toggled.connect(self._on_style_changed)
        sh_lo.addWidget(self._shadow_cb)
        sh_c_row = QHBoxLayout(); sh_c_row.setSpacing(6)
        sh_c_row.addWidget(QLabel("颜色"))
        self._shadow_color_btn = _color_btn(self._text_layer.shadow_color, 48)
        self._shadow_color_btn.clicked.connect(lambda: self._pick_color("shadow"))
        sh_c_row.addWidget(self._shadow_color_btn)
        sh_c_row.addSpacing(6)
        sh_c_row.addWidget(QLabel("不透明")); self._shadow_opacity_sl = _dslider(5, 100, 50)
        self._shadow_opacity_sl.valueChanged.connect(self._on_style_changed)
        sh_c_row.addWidget(self._shadow_opacity_sl, 1)
        sh_lo.addLayout(sh_c_row)
        sh_off_row = QHBoxLayout(); sh_off_row.setSpacing(4)
        sh_off_row.addWidget(QLabel("X")); self._shadow_x_spin = _spin(-50, 50, 3, 70)
        self._shadow_x_spin.valueChanged.connect(self._on_style_changed); sh_off_row.addWidget(self._shadow_x_spin)
        sh_off_row.addSpacing(2)
        sh_off_row.addWidget(QLabel("Y")); self._shadow_y_spin = _spin(-50, 50, 3, 70)
        self._shadow_y_spin.valueChanged.connect(self._on_style_changed); sh_off_row.addWidget(self._shadow_y_spin)
        sh_off_row.addSpacing(2)
        sh_off_row.addWidget(QLabel("模糊")); self._shadow_blur_spin = _spin(0, 50, 4, 70)
        self._shadow_blur_spin.valueChanged.connect(self._on_style_changed); sh_off_row.addWidget(self._shadow_blur_spin)
        sh_off_row.addStretch()
        sh_lo.addLayout(sh_off_row)
        panel_layout.addWidget(shadow_group)

        # ---------------------------------------------------------------
        # BACKGROUND
        # ---------------------------------------------------------------
        bg_group = _styled_group("背景")
        bg_lo = QVBoxLayout(bg_group); bg_lo.setSpacing(4)
        self._bg_enabled_cb = QCheckBox("启用背景框")
        self._bg_enabled_cb.toggled.connect(self._on_style_changed)
        bg_lo.addWidget(self._bg_enabled_cb)
        bg_c_row = QHBoxLayout(); bg_c_row.setSpacing(6)
        bg_c_row.addWidget(QLabel("颜色"))
        self._bg_color_btn = _color_btn(self._text_layer.background_color, 48)
        self._bg_color_btn.clicked.connect(lambda: self._pick_color("background"))
        bg_c_row.addWidget(self._bg_color_btn)
        bg_c_row.addSpacing(6)
        bg_c_row.addWidget(QLabel("不透明")); self._bg_opacity_sl = _dslider(5, 100, 60)
        self._bg_opacity_sl.valueChanged.connect(self._on_style_changed)
        bg_c_row.addWidget(self._bg_opacity_sl, 1)
        bg_lo.addLayout(bg_c_row)
        bg_p_row = QHBoxLayout(); bg_p_row.setSpacing(4)
        bg_p_row.addWidget(QLabel("圆角")); self._bg_radius_spin = _spin(0, 40, 12, 70)
        self._bg_radius_spin.valueChanged.connect(self._on_style_changed); bg_p_row.addWidget(self._bg_radius_spin)
        bg_p_row.addSpacing(2)
        bg_p_row.addWidget(QLabel("内距")); self._bg_padding_spin = _spin(0, 40, 12, 70)
        self._bg_padding_spin.valueChanged.connect(self._on_style_changed); bg_p_row.addWidget(self._bg_padding_spin)
        bg_p_row.addStretch()
        bg_lo.addLayout(bg_p_row)
        panel_layout.addWidget(bg_group)

        # ---------------------------------------------------------------
        # BORDER
        # ---------------------------------------------------------------
        border_group = _styled_group("边框")
        bd_lo = QVBoxLayout(border_group); bd_lo.setSpacing(4)
        self._border_cb = QCheckBox("启用背景边框")
        self._border_cb.toggled.connect(self._on_style_changed)
        bd_lo.addWidget(self._border_cb)
        bd_c_row = QHBoxLayout(); bd_c_row.setSpacing(6)
        bd_c_row.addWidget(QLabel("颜色"))
        self._border_color_btn = _color_btn(self._text_layer.border_color, 48)
        self._border_color_btn.clicked.connect(lambda: self._pick_color("border"))
        bd_c_row.addWidget(self._border_color_btn)
        bd_c_row.addSpacing(6)
        bd_c_row.addWidget(QLabel("粗细")); self._border_width_spin = _spin(1, 10, 2, 70)
        self._border_width_spin.valueChanged.connect(self._on_style_changed)
        bd_c_row.addWidget(self._border_width_spin)
        bd_c_row.addSpacing(6)
        bd_c_row.addWidget(QLabel("不透明")); self._border_opacity_sl = _dslider(5, 100, 100)
        self._border_opacity_sl.valueChanged.connect(self._on_style_changed)
        bd_c_row.addWidget(self._border_opacity_sl, 1)
        bd_lo.addLayout(bd_c_row)
        panel_layout.addWidget(border_group)

        # ---------------------------------------------------------------
        # POSITION
        # ---------------------------------------------------------------
        pos_group = _styled_group("位置")
        pos_lo = QVBoxLayout(pos_group); pos_lo.setSpacing(4)
        coord_row = QHBoxLayout(); coord_row.setSpacing(6)
        coord_row.addWidget(QLabel("X")); self._x_spin = QSpinBox(); self._x_spin.setRange(-9999, 9999)
        self._x_spin.valueChanged.connect(self._on_pos_spin); coord_row.addWidget(self._x_spin)
        coord_row.addWidget(QLabel("Y")); self._y_spin = QSpinBox(); self._y_spin.setRange(-9999, 9999)
        self._y_spin.valueChanged.connect(self._on_pos_spin); coord_row.addWidget(self._y_spin)
        pos_lo.addLayout(coord_row)

        self._center_h_cb = QCheckBox("水平居中"); self._center_h_cb.setChecked(True)
        self._center_h_cb.toggled.connect(self._on_center_h_toggled)
        pos_lo.addWidget(self._center_h_cb)
        self._lock_cb = QCheckBox("锁定位置")
        self._lock_cb.toggled.connect(self._on_lock_toggled)
        pos_lo.addWidget(self._lock_cb)

        quick_row1 = QHBoxLayout(); quick_row1.setSpacing(4)
        for tag, lbl, xp, yp in [("tl", "↖左上", 0, 0), ("tc", "↑顶部中", 50, 0), ("tr", "↗右上", 100, 0)]:
            btn = QPushButton(lbl); btn.setStyleSheet(BTN_UNCHECKED_STYLE)
            btn.clicked.connect(lambda checked, px=xp, py=yp: self._quick_pos(px, py))
            quick_row1.addWidget(btn)
        pos_lo.addLayout(quick_row1)
        quick_row2 = QHBoxLayout(); quick_row2.setSpacing(4)
        for tag, lbl, xp, yp in [("ml", "←左中", 0, 50), ("mc", "●正中", 50, 50), ("mr", "右中→", 100, 50)]:
            btn = QPushButton(lbl); btn.setStyleSheet(BTN_UNCHECKED_STYLE)
            btn.clicked.connect(lambda checked, px=xp, py=yp: self._quick_pos(px, py))
            quick_row2.addWidget(btn)
        pos_lo.addLayout(quick_row2)
        quick_row3 = QHBoxLayout(); quick_row3.setSpacing(4)
        for tag, lbl, xp, yp in [("bl", "↙左下", 0, 100), ("bc", "↓底部中", 50, 100), ("br", "↘右下", 100, 100)]:
            btn = QPushButton(lbl); btn.setStyleSheet(BTN_UNCHECKED_STYLE)
            btn.clicked.connect(lambda checked, px=xp, py=yp: self._quick_pos(px, py))
            quick_row3.addWidget(btn)
        pos_lo.addLayout(quick_row3)

        # Anchor
        anc_row = QHBoxLayout(); anc_row.setSpacing(6)
        anc_row.addWidget(QLabel("锚点"))
        self._anchor_combo = QComboBox()
        self._anchor_combo.addItems(["左上", "上中", "右上", "左中", "中心", "右中", "左下", "下中", "右下"])
        self._anchor_combo.setCurrentIndex(4)  # 中心
        self._anchor_combo.currentIndexChanged.connect(self._on_anchor_changed)
        anc_row.addWidget(self._anchor_combo, 1)
        pos_lo.addLayout(anc_row)

        # Guides & snap
        guide_row = QHBoxLayout(); guide_row.setSpacing(8)
        self._guide_cb = QCheckBox("辅助线"); self._guide_cb.setChecked(True)
        self._guide_cb.toggled.connect(self._on_guide_toggled)
        guide_row.addWidget(self._guide_cb)
        self._snap_cb = QCheckBox("吸附对齐"); self._snap_cb.setChecked(True)
        self._snap_cb.toggled.connect(self._on_snap_toggled)
        guide_row.addWidget(self._snap_cb)
        guide_row.addStretch()
        pos_lo.addLayout(guide_row)

        panel_layout.addWidget(pos_group)

        # ---------------------------------------------------------------
        # SAVE / UNDO
        # ---------------------------------------------------------------
        action_group = _styled_group("样式操作")
        act_lo = QHBoxLayout(action_group); act_lo.setSpacing(6)
        save_btn = QPushButton("💾 保存样式"); save_btn.setStyleSheet(BTN_UNCHECKED_STYLE)
        save_btn.clicked.connect(self._on_save_style)
        act_lo.addWidget(save_btn)
        undo_btn = QPushButton("↩ 撤销"); undo_btn.setStyleSheet(BTN_UNCHECKED_STYLE)
        undo_btn.clicked.connect(self._on_undo)
        act_lo.addWidget(undo_btn)
        panel_layout.addWidget(action_group)

        # Preview group (hidden by default)
        self._preview_group = QGroupBox("视频预览 — GIF 叠加位置")
        self._preview_group.setVisible(False)
        self._preview_group.setStyleSheet(GROUP_STYLE)
        prev_layout = QVBoxLayout(self._preview_group)
        prev_layout.addWidget(QLabel("拖动 GIF 调整位置"))
        gif_pos_row = QHBoxLayout()
        self._gif_x_spin = QSpinBox(); self._gif_x_spin.setRange(-9999, 9999)
        self._gif_x_spin.valueChanged.connect(self._on_gif_pos_changed)
        gif_pos_row.addWidget(QLabel("X:")); gif_pos_row.addWidget(self._gif_x_spin)
        self._gif_y_spin = QSpinBox(); self._gif_y_spin.setRange(-9999, 9999)
        self._gif_y_spin.valueChanged.connect(self._on_gif_pos_changed)
        gif_pos_row.addWidget(QLabel("Y:")); gif_pos_row.addWidget(self._gif_y_spin)
        prev_layout.addLayout(gif_pos_row)
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("缩放:"))
        self._gif_scale_spin = QDoubleSpinBox(); self._gif_scale_spin.setRange(0.1, 3.0)
        self._gif_scale_spin.setSingleStep(0.05); self._gif_scale_spin.setValue(1.0)
        self._gif_scale_spin.wheelEvent = lambda e: e.ignore()
        self._gif_scale_spin.valueChanged.connect(self._on_gif_scale_changed)
        scale_row.addWidget(self._gif_scale_spin); scale_row.addStretch()
        prev_layout.addLayout(scale_row)
        self._gif_lock_cb = QCheckBox("锁定 GIF 位置")
        self._gif_lock_cb.toggled.connect(self._on_gif_lock_toggled)
        prev_layout.addWidget(self._gif_lock_cb)
        reset_pos_btn = QPushButton("重置位置 (0, 0)")
        reset_pos_btn.clicked.connect(self._reset_gif_position)
        prev_layout.addWidget(reset_pos_btn)
        panel_layout.addWidget(self._preview_group)

        panel_layout.addStretch()
        scroll.setWidget(panel)

        # Block mouse wheel on all spinboxes/combos/sliders so scrolling the panel
        # doesn't accidentally change values
        def _block_wheel(widget):
            from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox, QSlider
            if isinstance(widget, (QSpinBox, QDoubleSpinBox, QComboBox, QSlider)):
                widget.wheelEvent = lambda e: e.ignore()
            for child in widget.children():
                _block_wheel(child)
        _block_wheel(panel)
        main_layout.addWidget(scroll)

        self._canvas.frame_changed.connect(self._on_frame_changed)
        self._canvas.gif_position_changed.connect(self._on_canvas_gif_moved)
        self._canvas.zoom_changed.connect(lambda v: self._zoom_label.setText(f"{v}%"))
        self._canvas.region_selected.connect(self._on_region_selected)

        # === Public API ===
    def load_gif(self, gif_path: str):
        self._gif_path = gif_path
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
        tl = self._text_layer
        tl.template_id = template.get("template_id", "")

        font_family = style.get("font_family", "Microsoft YaHei")
        tl.font_family = font_family
        tl.font_path = _SYSTEM_FONTS.get(font_family)

        for key, default in [
            ("font_size", 72), ("bold", True), ("italic", False),
            ("fill_color", "#FFD700"), ("opacity", 1.0),
            ("letter_spacing", 0), ("line_spacing", 8), ("align", "center"),
            ("stroke_enabled", True), ("stroke_color", "#000000"), ("stroke_width", 8),
            ("stroke_opacity", 1.0),
            ("shadow_enabled", True), ("shadow_color", "#000000"), ("shadow_opacity", 0.5),
            ("shadow_offset_x", 3), ("shadow_offset_y", 3), ("shadow_blur", 4),
            ("gradient_enabled", False), ("gradient_start", "#FFFFFF"), ("gradient_end", "#FFD700"),
            ("background_enabled", False), ("background_color", "#000000"),
            ("background_opacity", 0.6), ("background_radius", 12), ("background_padding", 12),
            ("border_enabled", False), ("border_color", "#FFFFFF"),
            ("border_width", 2), ("border_opacity", 1.0),
        ]:
            if key in style:
                setattr(tl, key, style[key])

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

    def _toggle_box_select(self, checked: bool):
        """Enter/exit box-select mode for font style analysis (works in preview too)."""
        if checked:
            self._canvas.set_selection_mode(True)
        else:
            self._canvas.set_selection_mode(False)

    def _on_region_selected(self, scene_rect: QRectF):
        """Handle rubber-band selection: analyze, save independent style JSON + crop, apply."""
        self._box_select_btn.setChecked(False)
        self._canvas.set_selection_mode(False)

        pil_frame = self._canvas.get_current_frame_pil()
        if pil_frame is None:
            logger.warning("Box-select: no PIL frame available (no decoder/frame loaded)")
            return

        gif_item = self._canvas.get_gif_item()
        if gif_item is None:
            logger.warning("Box-select: no GIF item on canvas")
            return

        logger.info(f"Box-select: scene_rect=({scene_rect.x():.0f},{scene_rect.y():.0f},{scene_rect.width():.0f},{scene_rect.height():.0f})")

        top_left = gif_item.mapFromScene(scene_rect.topLeft())
        bot_right = gif_item.mapFromScene(scene_rect.bottomRight())
        rx = max(0, int(min(top_left.x(), bot_right.x())))
        ry = max(0, int(min(top_left.y(), bot_right.y())))
        rw = max(1, int(abs(bot_right.x() - top_left.x())))
        rh = max(1, int(abs(bot_right.y() - top_left.y())))

        fw, fh = pil_frame.size
        logger.info(f"Box-select: raw_crop=({rx},{ry},{rw},{rh}) frame=({fw},{fh})")

        rx = min(rx, fw - 1)
        ry = min(ry, fh - 1)
        rw = min(rw, fw - rx)
        rh = min(rh, fh - ry)

        if rw < 4 or rh < 4:
            logger.warning(f"Box-select: region too small ({rw}x{rh}), skipping")
            return

        try:
            custom_dir = get_custom_styles_dir()
            style_id = generate_style_id(custom_dir)

            # Save cropped image
            crop = pil_frame.crop((rx, ry, rx + rw, ry + rh))
            crop_filename = f"{style_id}_crop.png"
            crop_path = os.path.join(custom_dir, crop_filename)
            crop.save(crop_path, "PNG")

            # Analyze and build independent style JSON
            source_img = self._gif_path or "unknown"
            style_dict = analyze_font_style(
                pil_frame, (rx, ry, rw, rh),
                style_id=style_id, source_image=source_img,
            )
            style_dict["cropped_image"] = crop_filename

            # Save independent style JSON
            json_path = save_style_json(style_dict, custom_dir)
            logger.info(f"Custom style saved: {json_path}")

            # Build display name
            features = style_dict.get("style_features", {})
            keywords = features.get("keywords", [])
            tag = keywords[0] if keywords else "框选"
            name = f"{tag}_{style_id.split('_')[-1]}"

            # Add to box-select dropdown (separate from template dropdown)
            self._box_styles.append({
                "style_id": style_id,
                "name": name,
                "json_path": json_path,
            })
            self._refresh_box_combo()

            # Auto-apply to current text layer
            self.apply_template({"style": style_to_text_layer(style_dict)})

            # Show result dialog
            result_json = json.dumps(style_dict, ensure_ascii=False, indent=2)
            self._show_style_result_dialog(result_json, name)

        except Exception as e:
            logger.error(f"Font style analysis failed: {e}")

    def _show_style_result_dialog(self, json_str: str, template_name: str = ""):
        """Show analyzed independent style JSON in a dialog with copy/apply options."""
        dlg = QDialog(self)
        dlg.setWindowTitle("框选文字 — 独立花字样式分析结果")
        dlg.setMinimumSize(540, 500)
        layout = QVBoxLayout(dlg)

        info_text = (f"✅ 独立花字样式已保存到 custom_styles/ 目录\n"
                     f"✅ 已添加到下拉框：{template_name}\n"
                     "以下是根据选中区域像素分析得出的完整样式 JSON。")
        info = QLabel(info_text)
        info.setWordWrap(True)
        info.setStyleSheet("color: #27ae60; font-size: 13px; font-weight: bold; margin-bottom: 4px;")
        layout.addWidget(info)

        text_edit = QTextEdit()
        text_edit.setPlainText(json_str)
        text_edit.setStyleSheet(
            "QTextEdit { font-family: 'Consolas', 'Courier New', monospace; "
            "font-size: 12px; background: #1e1e2e; color: #cdd6f4; "
            "border: 1px solid #45475a; border-radius: 4px; padding: 8px; }"
        )
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit, 1)

        btn_box = QDialogButtonBox()
        apply_btn = QPushButton("套用到当前文字样式")
        apply_btn.setStyleSheet(
            "QPushButton { background: #27ae60; color: white; padding: 6px 16px; "
            "border-radius: 4px; font-weight: bold; } QPushButton:hover { background: #219a52; }"
        )
        copy_btn = QPushButton("复制到剪贴板")
        copy_btn.setStyleSheet(
            "QPushButton { background: #3498db; color: white; padding: 6px 16px; "
            "border-radius: 4px; } QPushButton:hover { background: #2980b9; }"
        )
        close_btn = QPushButton("关闭")
        btn_box.addButton(apply_btn, QDialogButtonBox.ButtonRole.ActionRole)
        btn_box.addButton(copy_btn, QDialogButtonBox.ButtonRole.ActionRole)
        btn_box.addButton(close_btn, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(btn_box)

        apply_btn.clicked.connect(lambda: self._apply_analyzed_style(json_str, dlg))
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(json_str))
        close_btn.clicked.connect(dlg.close)

        dlg.exec()

    def _apply_analyzed_style(self, json_str: str, dlg: QDialog):
        """Apply the independent style JSON to the current text layer."""
        try:
            style_dict = json.loads(json_str)
        except Exception:
            return
        layer_style = style_to_text_layer(style_dict)
        self.apply_template({"style": layer_style})
        dlg.close()

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard."""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)

    def _show_tmpl_context_menu(self, pos):
        pass  # Combos removed; manage via preview dialog

    def _show_box_context_menu(self, pos):
        pass  # Combos removed; manage via preview dialog

    def _refresh_template_combo(self):
        """No-op: combo removed, preview dialog is now the sole selector."""

    def _refresh_box_combo(self):
        """No-op: combo removed, preview dialog is now the sole selector."""

    def _on_box_style_selected(self, idx: int):
        """Load and apply a saved box-select style JSON."""
        if idx <= 0 or idx - 1 >= len(self._box_styles):
            return
        style_ref = self._box_styles[idx - 1]
        json_path = style_ref["json_path"]
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                style_dict = json.load(f)
            self.apply_template({"style": style_to_text_layer(style_dict)})
        except Exception as e:
            logger.error(f"Failed to load box style {json_path}: {e}")

    def _show_template_preview(self):
        """Open style preview dialog for all templates."""
        styles = []
        for t in self._template_mgr.get_all_templates():
            styles.append({
                "id": t.template_id,
                "name": t.template_name,
                "style_params": {**t.style, "_preview_text": "Aa"},
            })
        if styles:
            dlg = StylePreviewDialog(styles, "", self)
            dlg.style_selected.connect(self._on_preview_style_applied)
            dlg.exec()

    def _show_box_preview(self):
        """Open style preview dialog for all box-select styles."""
        styles = []
        for s in self._box_styles:
            style_dict = None
            json_path = s.get("json_path", "")
            if json_path and os.path.isfile(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        style_dict = json.load(f)
                except Exception:
                    pass
            if style_dict:
                params = style_to_text_layer(style_dict)
                params["_preview_text"] = "Aa"
                styles.append({
                    "id": s["style_id"],
                    "name": s["name"],
                    "style_params": params,
                })
        if styles:
            dlg = StylePreviewDialog(styles, "", self)
            dlg.style_selected.connect(self._on_preview_style_applied)
            dlg.exec()

    def _on_preview_style_applied(self, style_id: str):
        """Called when a style is selected in the preview dialog."""
        # Try template first
        tmpl = self._template_mgr.get_template(style_id)
        if tmpl:
            self.apply_template(tmpl.style)
            return
        # Try box-style
        for s in self._box_styles:
            if s["style_id"] == style_id:
                json_path = s.get("json_path", "")
                if json_path and os.path.isfile(json_path):
                    try:
                        with open(json_path, "r", encoding="utf-8") as f:
                            style_dict = json.load(f)
                        self.apply_template({"style": style_to_text_layer(style_dict)})
                    except Exception:
                        pass
                return

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
        tl = self._text_layer
        self._font_btn.setText(tl.font_family)
        self._font_size_spin.setValue(tl.font_size)
        self._weight_spin.setValue(tl.weight)
        self._letter_spin.setValue(tl.letter_spacing)
        self._line_spin.setValue(tl.line_spacing)
        for ak, btn in self._align_btns.items():
            btn.setChecked(ak == tl.align)
        # Gradient
        self._grad_cb.setChecked(tl.gradient_enabled)
        self._grad_midpoint_sl.setValue(int(tl.gradient_midpoint * 100))
        self._grad_type_combo.setCurrentIndex(1 if tl.gradient_type == "radial" else 0)
        gd_map = {"topToBottom": 0, "leftToRight": 1, "leftTopToRightBot": 2, "rightTopToLeftBot": 3}
        self._grad_dir_combo.setCurrentIndex(gd_map.get(tl.gradient_direction, 0))
        # Show/hide direction based on type
        for i in range(self._grad_dir_row.count()):
            w = self._grad_dir_row.itemAt(i).widget()
            if w: w.setVisible(tl.gradient_type != "radial")
        self._stroke_cb.setChecked(tl.stroke_enabled)
        self._stroke_width_spin.setValue(tl.stroke_width)
        self._stroke_opacity_sl.setValue(int(tl.stroke_opacity * 100))
        self._shadow_cb.setChecked(tl.shadow_enabled)
        self._shadow_opacity_sl.setValue(int(tl.shadow_opacity * 100))
        self._shadow_x_spin.setValue(tl.shadow_offset_x)
        self._shadow_y_spin.setValue(tl.shadow_offset_y)
        self._shadow_blur_spin.setValue(tl.shadow_blur)
        self._bg_enabled_cb.setChecked(tl.background_enabled)
        self._bg_opacity_sl.setValue(int(tl.background_opacity * 100))
        self._bg_radius_spin.setValue(tl.background_radius)
        self._bg_padding_spin.setValue(tl.background_padding)
        self._border_cb.setChecked(tl.border_enabled)
        self._border_width_spin.setValue(tl.border_width)
        self._border_opacity_sl.setValue(int(tl.border_opacity * 100))
        # Anchor
        anc_map = {"topLeft": 0, "topCenter": 1, "topRight": 2,
                   "centerLeft": 3, "center": 4, "centerRight": 5,
                   "bottomLeft": 6, "bottomCenter": 7, "bottomRight": 8}
        self._anchor_combo.setCurrentIndex(anc_map.get(tl.anchor, 4))
        self._guide_cb.setChecked(tl.guide_enabled)
        self._snap_cb.setChecked(tl.snap_enabled)
        self._x_spin.setValue(int(tl.x))
        self._y_spin.setValue(int(tl.y))
        self._center_h_cb.setChecked(tl.center_horizontal)
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
        self._push_undo()
        self._text_layer.font_size = self._font_size_spin.value()
        self._text_layer.letter_spacing = self._letter_spin.value()
        self._text_layer.line_spacing = self._line_spin.value()
        self._text_layer.gradient_enabled = self._grad_cb.isChecked()
        self._text_layer.gradient_midpoint = self._grad_midpoint_sl.value() / 100.0
        self._text_layer.stroke_enabled = self._stroke_cb.isChecked()
        self._text_layer.stroke_width = self._stroke_width_spin.value()
        self._text_layer.stroke_opacity = self._stroke_opacity_sl.value() / 100.0
        self._text_layer.shadow_enabled = self._shadow_cb.isChecked()
        self._text_layer.shadow_opacity = self._shadow_opacity_sl.value() / 100.0
        self._text_layer.shadow_offset_x = self._shadow_x_spin.value()
        self._text_layer.shadow_offset_y = self._shadow_y_spin.value()
        self._text_layer.shadow_blur = self._shadow_blur_spin.value()
        self._text_layer.background_enabled = self._bg_enabled_cb.isChecked()
        self._text_layer.background_opacity = self._bg_opacity_sl.value() / 100.0
        self._text_layer.background_radius = self._bg_radius_spin.value()
        self._text_layer.background_padding = self._bg_padding_spin.value()
        self._text_layer.border_enabled = self._border_cb.isChecked()
        self._text_layer.border_width = self._border_width_spin.value()
        self._text_layer.border_opacity = self._border_opacity_sl.value() / 100.0
        self._render_preview()

    def _on_weight_changed(self, val: int):
        self._text_layer.weight = val
        self._text_layer.bold = val >= 600
        self._render_preview()

    def _on_grad_dir_changed(self, idx: int):
        dir_map = {0: "topToBottom", 1: "leftToRight", 2: "leftTopToRightBot", 3: "rightTopToLeftBot"}
        self._text_layer.gradient_direction = dir_map.get(idx, "topToBottom")
        self._render_preview()

    def _on_grad_type_changed(self, idx: int):
        self._text_layer.gradient_type = "radial" if idx == 1 else "linear"
        # Show direction only for linear
        for i in range(self._grad_dir_row.count()):
            w = self._grad_dir_row.itemAt(i).widget()
            if w: w.setVisible(idx == 0)
        self._render_preview()

    def _apply_gradient_preset(self, start: str, mid: str, end: str):
        self._text_layer.gradient_enabled = True
        self._text_layer.gradient_start = start
        self._text_layer.gradient_mid = mid
        self._text_layer.gradient_end = end
        self._grad_cb.setChecked(True)
        self._sync_ui_from_layer()
        self._render_preview()

    def _on_anchor_changed(self, idx: int):
        anchor_map = {0: "topLeft", 1: "topCenter", 2: "topRight",
                      3: "centerLeft", 4: "center", 5: "centerRight",
                      6: "bottomLeft", 7: "bottomCenter", 8: "bottomRight"}
        self._text_layer.anchor = anchor_map.get(idx, "center")
        self._text_layer.center_horizontal = "Center" in anchor_map.get(idx, "center")

    def _on_guide_toggled(self, checked: bool):
        self._text_layer.guide_enabled = checked
        self._canvas.set_guides(checked)

    def _on_snap_toggled(self, checked: bool):
        self._text_layer.snap_enabled = checked
        self._canvas.set_snap(checked)

    def _open_font_picker(self):
        dlg = FontPickerDialog(self._text_layer.font_family, self)
        dlg.font_selected.connect(self._on_font_picked)
        dlg.exec()

    def _on_font_picked(self, family: str):
        self._text_layer.font_family = family
        self._text_layer.font_path = self._font_mgr.get_font_path(family)
        if not self._font_mgr.is_installed(family):
            fb_family, fb_path = self._font_mgr.get_effective_font(family)
            self._text_layer.font_path = fb_path
            self._text_layer.font_family = family  # Keep requested name
        self._font_btn.setText(family)
        self._render_preview()

    def _set_font_size(self, size: int):
        self._font_size_spin.setValue(size)
        self._render_preview()

    def _show_color_palette(self):
        palette_colors = [
            "#111111", "#666666", "#F5F5F5", "#F7F1E8", "#C9A227", "#4A3428",
            "#102A43", "#1F3D2B", "#FFD400", "#E60012", "#FF7A00", "#1E63FF",
            "#FFFFFF",
        ]
        dlg = QDialog(self)
        dlg.setWindowTitle("高级色板")
        dlg.setFixedSize(260, 200)
        lo = QVBoxLayout(dlg)
        grid = QHBoxLayout()
        for i, c in enumerate(palette_colors):
            btn = QPushButton()
            btn.setFixedSize(32, 24)
            btn.setStyleSheet(f"QPushButton {{ background-color: {c}; border: 1px solid #ccc; border-radius: 3px; }} QPushButton:hover {{ border: 2px solid #3498db; }}")
            btn.clicked.connect(lambda checked, clr=c: self._apply_palette_color(clr, dlg))
            grid.addWidget(btn)
            if (i + 1) % 7 == 0:
                lo.addLayout(grid)
                grid = QHBoxLayout()
        if grid.count() > 0:
            lo.addLayout(grid)
        dlg.exec()

    def _apply_palette_color(self, color: str, dlg: QDialog):
        self._text_layer.fill_color = color
        if self._text_layer.gradient_enabled:
            self._text_layer.gradient_start = color
        self._update_color_buttons()
        self._render_preview()
        dlg.accept()

    def _on_opacity_changed(self, val: int):
        self._text_layer.opacity = val / 100.0
        self._render_preview()

    def _on_align(self, align: str):
        self._text_layer.align = align
        for ak, btn in self._align_btns.items():
            btn.setStyleSheet(BTN_CHECKED_STYLE if ak == align else BTN_UNCHECKED_STYLE)
        self._render_preview()

    def _on_preset(self, preset_id: str):
        style = PRESET_STYLES.get(preset_id, {})
        if style:
            self._push_undo()
            for k, v in style.items():
                if hasattr(self._text_layer, k):
                    setattr(self._text_layer, k, v)
            self._sync_ui_from_layer()
            self._render_preview()

    def _quick_pos(self, xpct: int, ypct: int):
        if not self._decoder:
            return
        gif_w, gif_h = self._decoder.get_size()
        self._text_layer.center_horizontal = (xpct == 50)
        self._text_layer.x = int(gif_w * xpct / 100.0)
        self._text_layer.y = int(gif_h * ypct / 100.0)
        self._sync_ui_from_layer()
        if self._text_item:
            self._text_item.setPos(self._text_layer.x, self._text_layer.y)
        self._render_preview()

    def _on_save_style(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "保存样式", "样式名称：", text="我的自定义样式")
        if ok and name.strip():
            tid = f"custom_{len(self._template_mgr.get_all_templates()) + 1:03d}"
            tl = self._text_layer
            style_dict = {
                "template_id": tid, "template_name": name.strip(), "category": "自定义",
                "font_family": tl.font_family, "font_size": tl.font_size,
                "bold": tl.bold, "italic": tl.italic,
                "fill_color": tl.fill_color, "opacity": tl.opacity,
                "stroke_enabled": tl.stroke_enabled,
                "stroke_color": tl.stroke_color, "stroke_width": tl.stroke_width,
                "shadow_enabled": tl.shadow_enabled,
                "shadow_color": tl.shadow_color, "shadow_opacity": tl.shadow_opacity,
                "shadow_offset_x": tl.shadow_offset_x,
                "shadow_offset_y": tl.shadow_offset_y, "shadow_blur": tl.shadow_blur,
                "background_enabled": tl.background_enabled,
                "background_color": tl.background_color,
                "background_opacity": tl.background_opacity,
                "background_radius": tl.background_radius, "background_padding": tl.background_padding,
                "border_enabled": tl.border_enabled,
                "border_color": tl.border_color, "border_width": tl.border_width,
                "border_opacity": tl.border_opacity,
            }
            self._template_mgr.save_custom_template(tid, name.strip(), "自定义", style_dict)
            self._refresh_template_combo()

    # ---- Undo ----
    def _push_undo(self):
        self._undo_stack.append(self._text_layer.clone())
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _on_undo(self):
        if not self._undo_stack:
            return
        prev = self._undo_stack.pop()
        self._text_layer = prev
        self._sync_ui_from_layer()
        self._render_preview()

    _COLOR_TARGETS = {
        "fill": ("fill_color", "_fill_color_btn"),
        "stroke": ("stroke_color", "_stroke_color_btn"),
        "shadow": ("shadow_color", "_shadow_color_btn"),
        "background": ("background_color", "_bg_color_btn"),
        "border": ("border_color", "_border_color_btn"),
        "gradient_start": ("gradient_start", "_grad_start_btn"),
        "gradient_mid": ("gradient_mid", "_grad_mid_btn"),
        "gradient_end": ("gradient_end", "_grad_end_btn"),
    }

    def _pick_color(self, target: str):
        info = self._COLOR_TARGETS.get(target)
        if not info: return
        attr, _ = info
        current = QColor(getattr(self._text_layer, attr))
        color = QColorDialog.getColor(current, self, "选择颜色")
        if color.isValid():
            setattr(self._text_layer, attr, color.name())
            # If picking fill color while gradient is on, sync gradient_start
            # so the change is visible immediately
            if target == "fill" and self._text_layer.gradient_enabled:
                self._text_layer.gradient_start = color.name()
            self._update_color_buttons()
            self._render_preview()

    def _update_color_buttons(self):
        for _target, (attr, btn_name) in self._COLOR_TARGETS.items():
            if hasattr(self, btn_name):
                btn = getattr(self, btn_name)
                c = getattr(self._text_layer, attr)
                btn.setText(c)
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {c}; border: 1px solid #bdc3c7; "
                    f"border-radius: 3px; font-size: 9px; color: #fff; text-shadow: 0 0 2px #000; }}"
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
        pass  # Combos removed; preview dialog handles selection

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
