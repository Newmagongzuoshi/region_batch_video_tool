from PySide6.QtWidgets import QGraphicsObject
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPen, QColor, QPainter


class DraggableTextItem(QGraphicsObject):
    """A draggable text overlay item using QGraphicsObject for proper signal support."""

    position_changed = Signal(float, float)

    def __init__(self, pixmap, text_template: str = "{地区}", parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._text_template = text_template
        self._locked = False

        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._pixmap.width(), self._pixmap.height())

    def paint(self, painter: QPainter, option, widget=None):
        if self._pixmap.isNull():
            return
        painter.drawPixmap(0, 0, self._pixmap)
        if self.isSelected() and not self._locked:
            pen = QPen(QColor("#3498db"), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect().adjusted(1, 1, -1, -1))

    def set_locked(self, locked: bool):
        self._locked = locked
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, not locked)
        if locked:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.update()

    def is_locked(self) -> bool:
        return self._locked

    def update_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.prepareGeometryChange()
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsObject.GraphicsItemChange.ItemPositionHasChanged:
            self.position_changed.emit(self.x(), self.y())
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if not self._locked:
            self.setSelected(True)
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if not self._locked:
            super().mouseMoveEvent(event)
