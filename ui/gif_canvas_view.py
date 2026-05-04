from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem
from PySide6.QtCore import Qt, QRectF, QTimer, Signal, QPointF
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBrush, QCursor
from PIL import Image

from core.gif_frame_decoder import GifFrameDecoder

CHECKER_SIZE = 16


class GifCanvasView(QGraphicsView):
    frame_changed = Signal(int, int)
    gif_position_changed = Signal(float, float)
    zoom_changed = Signal(int)
    region_selected = Signal(QRectF)  # Rubber-band selection complete (scene coords)

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene()
        self.setScene(self._scene)

        self._decoder: GifFrameDecoder | None = None
        self._current_frame_idx: int = 0
        self._gif_item: QGraphicsPixmapItem | None = None
        self._draggable_text: object | None = None

        # Preview mode
        self._preview_mode: bool = False
        self._bg_pixmap_item: QGraphicsPixmapItem | None = None
        self._gif_locked: bool = False

        self._bg_mode: str = "checkerboard"
        self._video_bg: QPixmap | None = None
        self._playing: bool = False
        self._timer: QTimer | None = None
        self._elapsed_ms: int = 0

        # Rubber-band selection for 框选文字
        self._selection_mode: bool = False
        self._sel_origin = None  # QPointF from mapToScene
        self._sel_rect_item: QGraphicsRectItem | None = None

        # Guides & snap
        self._guide_enabled: bool = True
        self._snap_enabled: bool = True
        self._snap_threshold: int = 10

        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet("background-color: #1a1a2e; border: none;")

        self._checker_pixmap = self._make_checkerboard()

    def _make_checkerboard(self, size: int = CHECKER_SIZE) -> QPixmap:
        pm = QPixmap(size * 2, size * 2)
        painter = QPainter(pm)
        painter.fillRect(0, 0, size, size, QColor(180, 180, 180))
        painter.fillRect(size, size, size, size, QColor(180, 180, 180))
        painter.fillRect(size, 0, size, size, QColor(220, 220, 220))
        painter.fillRect(0, size, size, size, QColor(220, 220, 220))
        painter.end()
        return pm

    def set_decoder(self, decoder: GifFrameDecoder):
        self._decoder = decoder
        self._current_frame_idx = 0
        self._elapsed_ms = 0
        self._show_frame(0)

    def decoder(self) -> GifFrameDecoder | None:
        return self._decoder

    def set_background_mode(self, mode: str):
        self._bg_mode = mode
        self.viewport().update()

    def set_preview_background(self, image_path: str | None):
        """Set video first frame as background for preview mode."""
        if image_path is None:
            if self._bg_pixmap_item:
                self._scene.removeItem(self._bg_pixmap_item)
                self._bg_pixmap_item = None
            self._preview_mode = False
            self._bg_mode = "checkerboard"
            # Disable GIF dragging
            if self._gif_item:
                self._gif_item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable, False)
                self._gif_item.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            pm = QPixmap(image_path)
            if pm.isNull():
                return
            self._preview_mode = True
            self._bg_mode = "video_first_frame"
            if self._bg_pixmap_item:
                self._bg_pixmap_item.setPixmap(pm)
            else:
                self._bg_pixmap_item = QGraphicsPixmapItem(pm)
                self._bg_pixmap_item.setZValue(-1)
                self._scene.addItem(self._bg_pixmap_item)
                br = self._scene.sceneRect()
                pm_rect = QRectF(pm.rect())
                self._scene.setSceneRect(br.united(pm_rect))
            # Enable GIF dragging
            if self._gif_item and not self._gif_locked:
                self._gif_item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable, True)
                self._gif_item.setCursor(Qt.CursorShape.SizeAllCursor)

        self.viewport().update()

    def get_gif_item(self):
        return self._gif_item

    def set_gif_position(self, x: float, y: float):
        if self._gif_item:
            self._gif_item.setPos(x, y)

    def set_gif_locked(self, locked: bool):
        self._gif_locked = locked
        if self._gif_item:
            self._gif_item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable,
                                   self._preview_mode and not locked)
            self._gif_item.setCursor(
                Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor
            )

    def set_gif_scale(self, sx: float, sy: float):
        if self._gif_item:
            from PySide6.QtGui import QTransform
            t = QTransform()
            t.scale(sx, sy)
            self._gif_item.setTransform(t)

    def get_gif_geometry(self) -> dict:
        """Return current GIF overlay position and size info."""
        if not self._gif_item or not self._decoder:
            return {"x": 0, "y": 0, "width": 0, "height": 0, "scale_x": 1.0, "scale_y": 1.0}
        t = self._gif_item.transform()
        orig_w, orig_h = self._decoder.get_size()
        return {
            "x": self._gif_item.x(),
            "y": self._gif_item.y(),
            "width": int(orig_w * t.m11()),
            "height": int(orig_h * t.m22()),
            "scale_x": t.m11(),
            "scale_y": t.m22(),
        }

    def _show_frame(self, idx: int):
        if not self._decoder:
            return
        frame = self._decoder.get_frame(idx)
        if frame is None:
            return
        self._current_frame_idx = idx
        qimg = self._pil_to_qimage(frame)
        pixmap = QPixmap.fromImage(qimg)
        if self._gif_item:
            self._gif_item.setPixmap(pixmap)
        else:
            self._gif_item = QGraphicsPixmapItem(pixmap)
            self._gif_item.setZValue(1)
            self._gif_item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable, False)
            self._gif_item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._gif_item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
            self._gif_item.setAcceptHoverEvents(True)
            self._scene.addItem(self._gif_item)
            self._scene.setSceneRect(QRectF(pixmap.rect()))
            self.resetTransform()

        self._gif_item.setCursor(
            Qt.CursorShape.SizeAllCursor if (self._preview_mode and not self._gif_locked)
            else Qt.CursorShape.ArrowCursor
        )
        self.frame_changed.emit(idx, self._decoder.get_frame_count())

    def _pil_to_qimage(self, pil_image: Image.Image) -> QImage:
        data = pil_image.tobytes("raw", "RGBA")
        qimg = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
        return qimg.copy()

    def play(self):
        if not self._decoder or self._decoder.get_frame_count() <= 1:
            return
        self._playing = True
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)

        def _next_frame():
            if not self._playing or not self._decoder:
                return
            self._elapsed_ms += self._timer.interval()
            idx, frame = self._decoder.get_frame_at_time(self._elapsed_ms)
            if frame:
                qimg = self._pil_to_qimage(frame)
                if self._gif_item:
                    self._gif_item.setPixmap(QPixmap.fromImage(qimg))
                self._current_frame_idx = idx
                self.frame_changed.emit(idx, self._decoder.get_frame_count())

            total_ms = self._decoder.get_total_duration_ms()
            if self._elapsed_ms >= total_ms:
                self._elapsed_ms = 0

            dur = self._decoder.get_duration(self._current_frame_idx)
            if dur <= 0:
                dur = 100
            self._timer.setInterval(dur)

        try:
            self._timer.timeout.disconnect()
        except Exception:
            pass
        self._timer.timeout.connect(_next_frame)
        dur = self._decoder.get_duration(self._current_frame_idx) or 100
        self._timer.start(dur)

    def pause(self):
        self._playing = False
        if self._timer:
            self._timer.stop()

    def stop(self):
        self.pause()
        self._elapsed_ms = 0
        self._show_frame(0)

    def is_playing(self) -> bool:
        return self._playing

    def seek_frame(self, frame_index: int):
        if not self._decoder:
            return
        idx = max(0, min(frame_index, self._decoder.get_frame_count() - 1))
        self._elapsed_ms = sum(self._decoder.get_durations()[:idx])
        self._show_frame(idx)

    def next_frame(self):
        if self._decoder:
            self.seek_frame(self._current_frame_idx + 1)

    def previous_frame(self):
        if self._decoder:
            self.seek_frame(self._current_frame_idx - 1)

    @property
    def current_frame(self) -> int:
        return self._current_frame_idx

    @property
    def total_frames(self) -> int:
        return self._decoder.get_frame_count() if self._decoder else 0

    @property
    def is_preview_mode(self) -> bool:
        return self._preview_mode

    def _emit_zoom(self):
        z = int(self.transform().m11() * 100)
        self.zoom_changed.emit(z)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            self._emit_zoom()
        else:
            event.ignore()

    def zoom_in(self):
        self.scale(1.15, 1.15)
        self._emit_zoom()

    def zoom_out(self):
        self.scale(1 / 1.15, 1 / 1.15)
        self._emit_zoom()

    def zoom_fit(self):
        if not self._scene.sceneRect().isEmpty():
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self._emit_zoom()

    def zoom_100(self):
        self.resetTransform()
        self._emit_zoom()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        if self._bg_mode == "checkerboard":
            painter.drawTiledPixmap(rect, self._checker_pixmap)
        elif self._bg_mode == "black":
            painter.fillRect(rect, QColor(0, 0, 0))
        elif self._bg_mode == "white":
            painter.fillRect(rect, QColor(255, 255, 255))
        else:
            painter.drawTiledPixmap(rect, self._checker_pixmap)

    # ---- Rubber-band selection mode ----

    def set_selection_mode(self, enabled: bool):
        """Toggle box-select mode. When on, mouse drag draws a live selection rect."""
        self._selection_mode = enabled
        if enabled:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            if self._playing:
                self.pause()
        else:
            self._clear_selection_rubber_band()
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def is_selection_mode(self) -> bool:
        return self._selection_mode

    def _clear_selection_rubber_band(self):
        self._sel_origin = None
        if self._sel_rect_item:
            self._scene.removeItem(self._sel_rect_item)
            self._sel_rect_item = None

    def mousePressEvent(self, event):
        if self._selection_mode and event.button() == Qt.MouseButton.LeftButton:
            self._clear_selection_rubber_band()
            sp = self.mapToScene(event.pos())
            self._sel_origin = sp
            # Create live selection rect on scene
            pen = QPen(QColor("#00D2FF"), 2, Qt.PenStyle.DashLine)
            brush = QBrush(QColor(0, 210, 255, 40))
            self._sel_rect_item = QGraphicsRectItem(QRectF(sp, sp))
            self._sel_rect_item.setPen(pen)
            self._sel_rect_item.setBrush(brush)
            self._sel_rect_item.setZValue(20)
            self._scene.addItem(self._sel_rect_item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._selection_mode and self._sel_rect_item and self._sel_origin:
            sp = self.mapToScene(event.pos())
            rect = QRectF(self._sel_origin, sp).normalized()
            self._sel_rect_item.setRect(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._selection_mode and self._sel_rect_item:
            scene_rect = self._sel_rect_item.rect()
            # Keep the rect visible as feedback; it will be cleared on next selection or mode exit
            self.region_selected.emit(scene_rect)
            event.accept()
            return

        super().mouseReleaseEvent(event)
        if self._preview_mode and self._gif_item:
            pos = self._gif_item.pos()
            self.gif_position_changed.emit(pos.x(), pos.y())

    # ---- Public helpers ----

    def add_text_item(self, draggable_item, parent_item=None) -> None:
        self._draggable_text = draggable_item
        self._scene.addItem(draggable_item)
        if parent_item:
            draggable_item.setParentItem(parent_item)
        draggable_item.setZValue(10)

    def remove_text_item(self) -> None:
        if self._draggable_text:
            self._scene.removeItem(self._draggable_text)
            self._draggable_text = None

    def get_current_frame_pil(self) -> Image.Image | None:
        """Return the current frame as a PIL RGBA Image (for analysis)."""
        if not self._decoder:
            return None
        return self._decoder.get_frame(self._current_frame_idx)

    # ---- Guides & Snap ----

    def set_guides(self, enabled: bool):
        self._guide_enabled = enabled
        self.viewport().update()

    def set_snap(self, enabled: bool):
        self._snap_enabled = enabled

    def drawForeground(self, painter: QPainter, rect: QRectF):
        super().drawForeground(painter, rect)
        if not self._guide_enabled:
            return
        sr = self._scene.sceneRect()
        cx, cy = sr.center().x(), sr.center().y()
        pen = QPen(QColor(100, 100, 100, 80), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        # Center cross
        painter.drawLine(QPointF(cx, sr.top()), QPointF(cx, sr.bottom()))
        painter.drawLine(QPointF(sr.left(), cy), QPointF(sr.right(), cy))
        # Safe area (10% margin)
        margin = 0.1
        safe_l = sr.left() + sr.width() * margin
        safe_r = sr.right() - sr.width() * margin
        safe_t = sr.top() + sr.height() * margin
        safe_b = sr.bottom() - sr.height() * margin
        safe_pen = QPen(QColor(200, 200, 200, 60), 1, Qt.PenStyle.DotLine)
        painter.setPen(safe_pen)
        painter.drawRect(QRectF(safe_l, safe_t, safe_r - safe_l, safe_b - safe_t))
