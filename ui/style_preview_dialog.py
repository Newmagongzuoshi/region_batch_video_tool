"""Style preview dialog — shows rendered text thumbnails for all templates/styles.

Like CapCut (剪映), each style is shown as a rendered preview so the user
can see exactly what it looks like before applying.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QGridLayout, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage, QFont

from core.text_render_service import TextRenderService
from models.text_layer_model import TextLayerModel


class StylePreviewDialog(QDialog):
    """Modal dialog showing rendered previews of text styles.

    Usage:
        dlg = StylePreviewDialog(styles, current_id, parent=self)
        dlg.style_selected.connect(self._on_style_applied)
        dlg.exec()
    """

    style_selected = Signal(str)  # emits style_id

    THUMB_W = 180
    THUMB_H = 64
    COLS = 3

    def __init__(self, styles: list[dict], current_id: str = "", parent=None):
        """
        Args:
            styles: list of dicts, each with:
                - id: str
                - name: str
                - style_params: dict (TextLayerModel-compatible fields, or raw template style)
            current_id: currently selected style ID (for highlighting)
        """
        super().__init__(parent)
        self.setWindowTitle("选择花字样式")
        self.setMinimumSize(640, 480)
        self.setStyleSheet("QDialog { background: #2c3e50; }")

        self._styles = styles
        self._current_id = current_id
        self._renderer = TextRenderService()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        header = QLabel(f"共 {len(styles)} 个样式 — 点击缩略图直接套用")
        header.setStyleSheet("color: #bdc3c7; font-size: 13px;")
        layout.addWidget(header)

        # Scrollable grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(grid_widget)
        self._grid.setSpacing(8)

        scroll.setWidget(grid_widget)
        layout.addWidget(scroll, 1)

        # Populate
        self._populate()

    def _populate(self):
        col = 0
        row = 0
        for style in self._styles:
            card = self._create_card(style)
            self._grid.addWidget(card, row, col)
            col += 1
            if col >= self.COLS:
                col = 0
                row += 1

    def _create_card(self, style: dict) -> QFrame:
        sid = style["id"]
        name = style["name"]
        params = style.get("style_params", {})

        card = QFrame()
        card.setFixedSize(self.THUMB_W + 12, self.THUMB_H + 36)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        is_current = sid == self._current_id
        card.setStyleSheet(
            f"QFrame {{ background: {'#3d566e' if is_current else '#34495e'}; "
            f"border-radius: 6px; border: {'2px solid #3498db' if is_current else '1px solid #4a6785'}; }}"
            f"QFrame:hover {{ background: #3d566e; border-color: #3498db; }}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 6, 6, 4)
        card_layout.setSpacing(4)

        # Thumbnail image
        pixmap = self._render_thumbnail(params)
        img_label = QLabel()
        img_label.setPixmap(pixmap)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setFixedSize(self.THUMB_W, self.THUMB_H)
        img_label.setStyleSheet("background: transparent; border: none;")
        card_layout.addWidget(img_label, 0, Qt.AlignmentFlag.AlignCenter)

        # Name label
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet(
            f"color: {'#3498db' if is_current else '#ecf0f1'}; font-size: 11px; "
            f"border: none; background: transparent; font-weight: {'bold' if is_current else 'normal'};"
        )
        name_label.setWordWrap(True)
        card_layout.addWidget(name_label)

        # Click handler
        card.mousePressEvent = lambda e, s=sid: self._on_click(s)

        return card

    def _on_click(self, style_id: str):
        self.style_selected.emit(style_id)
        self.accept()

    def _render_thumbnail(self, params: dict) -> QPixmap:
        """Render a small preview of the style using TextRenderService."""
        layer = TextLayerModel()
        # Apply style params
        for key in [
            "font_family", "font_size", "bold", "fill_color", "opacity",
            "stroke_enabled", "stroke_color", "stroke_width",
            "shadow_enabled", "shadow_color", "shadow_opacity",
            "shadow_offset_x", "shadow_offset_y", "shadow_blur",
            "gradient_enabled", "gradient_start", "gradient_end",
            "background_enabled", "background_color", "background_opacity",
            "background_radius", "background_padding",
            "border_enabled", "border_color", "border_width",
        ]:
            if key in params:
                setattr(layer, key, params[key])

        # Reduce font size for thumbnail
        if layer.font_size > 48:
            layer.font_size = 36
        elif layer.font_size > 32:
            layer.font_size = 28

        # Render
        sample_text = params.get("_preview_text", "Aa")
        try:
            img = self._renderer.render_text(sample_text, layer)
            if img is None:
                return self._empty_pixmap()
            # Scale to fit thumbnail
            img = img.convert("RGBA")
            ratio = min(self.THUMB_W / img.width, self.THUMB_H / img.height, 1.0)
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            img = img.resize((new_w, new_h))

            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimg.copy())
            return pixmap
        except Exception:
            return self._empty_pixmap()

    def _empty_pixmap(self) -> QPixmap:
        pixmap = QPixmap(self.THUMB_W, self.THUMB_H)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap
