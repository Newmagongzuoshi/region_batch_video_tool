"""Professional font picker dialog with search, groups, and live preview."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QSplitter, QWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from core.font_manager import get_font_manager, FontInfo


class FontPickerDialog(QDialog):
    font_selected = Signal(str)

    def __init__(self, current_family: str = "Microsoft YaHei", parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择字体")
        self.setMinimumSize(620, 460)
        self.setStyleSheet(
            "QDialog { background: #f5f6fa; }"
        )

        self._fm = get_font_manager()
        self._current = current_family
        self._all_groups = self._fm.get_groups()
        self._group_names = list(self._all_groups.keys())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Search bar
        search_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索字体（支持中文/英文）...")
        self._search_edit.setStyleSheet(
            "QLineEdit { padding: 6px 10px; border: 1px solid #dcdde1; "
            "border-radius: 4px; font-size: 13px; background: #fff; color: #333; }"
        )
        self._search_edit.textChanged.connect(self._on_search)
        search_row.addWidget(self._search_edit)
        layout.addLayout(search_row)

        # Splitter: groups | font list
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: group list
        self._group_list = QListWidget()
        self._group_list.setFixedWidth(160)
        self._group_list.setStyleSheet(
            "QListWidget { border: 1px solid #dcdde1; border-radius: 4px; "
            "background: #fff; color: #333; font-size: 12px; }"
            "QListWidget::item { padding: 4px 8px; }"
            "QListWidget::item:selected { background: #3498db; color: #fff; }"
        )
        for gname in self._group_names:
            item = QListWidgetItem(gname)
            if gname == "推荐字体":
                item.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
            self._group_list.addItem(item)
        self._group_list.currentRowChanged.connect(self._on_group_changed)
        splitter.addWidget(self._group_list)

        # Right: font preview list
        self._font_list = QListWidget()
        self._font_list.setStyleSheet(
            "QListWidget { border: 1px solid #dcdde1; border-radius: 4px; "
            "background: #fff; color: #333; font-size: 14px; }"
            "QListWidget::item { padding: 6px 10px; }"
            "QListWidget::item:selected { background: #3498db; color: #fff; }"
        )
        self._font_list.itemClicked.connect(self._on_font_clicked)
        splitter.addWidget(self._font_list)
        layout.addWidget(splitter, 1)

        # Info row
        info = QLabel("已安装字体可直接使用；未安装字体会自动使用兜底字体，不影响渲染。")
        info.setStyleSheet("color: #888; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Show initial group
        rec_idx = self._group_names.index("推荐字体") if "推荐字体" in self._group_names else 0
        self._group_list.setCurrentRow(rec_idx)

    # ---- slots ----

    def _on_group_changed(self, row: int):
        if row < 0 or row >= len(self._group_names):
            return
        gname = self._group_names[row]
        fonts = self._all_groups.get(gname, [])
        self._populate_font_list(fonts)
        self._search_edit.clear()

    def _on_search(self, text: str):
        text = text.strip()
        if text:
            self._group_list.clearSelection()
            results = self._fm.search(text)
            self._populate_font_list(results)
        elif self._group_list.currentRow() >= 0:
            self._on_group_changed(self._group_list.currentRow())

    def _populate_font_list(self, fonts: list[FontInfo]):
        self._font_list.clear()
        for fi in fonts:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, fi.family)

            # Build display text
            display = fi.family
            if fi.built_in:
                display += "  [内置]"
            elif not fi.installed:
                display += "  [未安装]"

            item.setText(display)

            # For built-in fonts, register with QFontDatabase so QFont can use them
            if fi.built_in and fi.path:
                from PySide6.QtGui import QFontDatabase
                QFontDatabase.addApplicationFont(fi.path)

            # Try to render in the font itself
            if fi.installed and fi.path:
                font = QFont(fi.family)
                item.setFont(font)
            else:
                item.setFont(QFont("Microsoft YaHei", 10))

            if not fi.installed:
                item.setForeground(QColor("#999999"))
            elif fi.family == self._current:
                item.setFont(QFont(fi.family, 11, QFont.Weight.Bold))

            self._font_list.addItem(item)

    def _on_font_clicked(self, item: QListWidgetItem):
        family = item.data(Qt.ItemDataRole.UserRole)
        if family:
            self._fm.mark_used(family)
            self.font_selected.emit(family)
            self.accept()
