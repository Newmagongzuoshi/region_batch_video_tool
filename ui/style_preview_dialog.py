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
from PySide6.QtGui import QPixmap, QImage, QFont, QColor

from core.text_render_service import TextRenderService
from models.text_layer_model import TextLayerModel


class StylePreviewDialog(QDialog):
    """Modal dialog showing rendered previews of text styles.

    Uses batch rendering with QTimer to avoid blocking the UI thread.
    """

    style_selected = Signal(str)

    THUMB_W = 150
    THUMB_H = 64
    COLS = 10
    BATCH_SIZE = 12

    _pixmap_cache: dict[str, QPixmap] = {}

    def __init__(self, styles: list[dict], current_id: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择花字样式")
        self.setMinimumSize(1200, 650)
        self.setStyleSheet("QDialog { background: #2c3e50; }")

        self._styles = styles
        self._current_id = current_id
        self._renderer = TextRenderService()
        self._cards: list[QFrame] = []
        self._img_labels: list[QLabel] = []
        self._batch_idx = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QLabel(f"共 {len(styles)} 个样式 — 点击缩略图直接套用")
        header.setStyleSheet("color: #bdc3c7; font-size: 13px;")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(grid_widget)
        self._grid.setSpacing(8)

        scroll.setWidget(grid_widget)
        layout.addWidget(scroll, 1)

        # Create all cards first (fast, no rendering), then batch-render
        col = 0; row = 0
        for style in self._styles:
            card, img_label = self._create_card_shell(style)
            self._cards.append(card)
            self._img_labels.append(img_label)
            self._grid.addWidget(card, row, col)
            col += 1
            if col >= self.COLS:
                col = 0; row += 1

        # Start batch rendering
        self._render_next_batch()

    def _create_card_shell(self, style: dict) -> tuple[QFrame, QLabel]:
        """Create card frame + placeholder image (fast, no rendering)."""
        sid = style["id"]
        name = style["name"]
        is_current = sid == self._current_id

        card = QFrame()
        card.setFixedSize(self.THUMB_W + 12, self.THUMB_H + 36)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(
            f"QFrame {{ background: {'#3d566e' if is_current else '#34495e'}; "
            f"border-radius: 6px; border: {'2px solid #3498db' if is_current else '1px solid #4a6785'}; }}"
            f"QFrame:hover {{ background: #3d566e; border-color: #3498db; }}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(6, 6, 6, 4)
        card_layout.setSpacing(4)

        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setFixedSize(self.THUMB_W, self.THUMB_H)
        img_label.setStyleSheet("background: #f5f5f5; border-radius: 3px; color: #888; font-size: 10px;")
        img_label.setText("...")
        card_layout.addWidget(img_label, 0, Qt.AlignmentFlag.AlignCenter)

        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet(
            f"color: {'#3498db' if is_current else '#ecf0f1'}; font-size: 11px; "
            f"border: none; background: transparent; font-weight: {'bold' if is_current else 'normal'};"
        )
        name_label.setWordWrap(True)
        card_layout.addWidget(name_label)

        card.mousePressEvent = lambda e, s=sid: self._on_click(s)

        return card, img_label

    def _render_next_batch(self):
        """Render a batch of thumbnails, then schedule the next batch."""
        from PySide6.QtCore import QTimer

        end = min(self._batch_idx + self.BATCH_SIZE, len(self._styles))
        for i in range(self._batch_idx, end):
            style = self._styles[i]
            sid = style["id"]
            params = style.get("style_params", {})

            # Check cache first
            if sid in self._pixmap_cache:
                pixmap = self._pixmap_cache[sid]
            else:
                pixmap = self._render_thumbnail(params)
                self._pixmap_cache[sid] = pixmap

            self._img_labels[i].setPixmap(pixmap)
            self._img_labels[i].setText("")

        self._batch_idx = end

        if self._batch_idx < len(self._styles):
            QTimer.singleShot(30, self._render_next_batch)

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
            "stroke_enabled", "stroke_color", "stroke_width", "stroke_mode",
            "glow_enabled", "glow_color", "glow_width", "glow_opacity",
            "shadow_enabled", "shadow_color", "shadow_opacity",
            "shadow_offset_x", "shadow_offset_y", "shadow_blur",
            "gradient_enabled", "gradient_start", "gradient_end",
            "background_enabled", "background_color", "background_opacity",
            "background_radius", "background_padding",
            "border_enabled", "border_color", "border_width", "border_style",
        ]:
            if key in params:
                setattr(layer, key, params[key])

        # Scale for thumbnail — keep stroke visible, disable gradient for clarity
        layer.gradient_enabled = False
        layer.font_size = 36
        layer.weight = min(getattr(layer, 'weight', 1350), 900)
        layer.stroke_width = max(1, layer.stroke_width // 2)
        layer.stroke_mode = "outer"
        layer.glow_enabled = False
        layer.shadow_blur = 0
        layer.shadow_offset_x = 0
        layer.shadow_offset_y = 0

        # Render on white bg for clear preview
        sample_text = params.get("_preview_text", "地区")
        try:
            img = self._renderer.render_text(sample_text, layer)
            if img is None:
                return self._empty_pixmap()
            # Composite on white background for visibility
            from PIL import Image as PILImage
            bg = PILImage.new("RGBA", img.size, (245, 245, 245, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
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
        pixmap.fill(QColor(245, 245, 245))
        return pixmap
