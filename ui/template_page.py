from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QGroupBox, QMessageBox,
    QFileDialog, QInputDialog,
)
from PySide6.QtCore import Qt, Signal

from core.template_manager import TemplateManager
from models.template_model import TemplateModel
from utils.logger import get_logger

logger = get_logger()

CATEGORY_ICONS = {
    "抖音醒目标题类": "🎬",
    "工厂推广类": "🏭",
    "地区获客类": "📍",
    "促销广告类": "🏷️",
    "商务高级类": "💼",
    "卡通活泼类": "🎨",
}


class TemplatePage(QWidget):
    template_selected = Signal(dict)

    def __init__(self):
        super().__init__()
        self._tm = TemplateManager()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Left: category filter
        left_panel = QWidget()
        left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("模板分类"))
        self._cat_list = QListWidget()
        self._cat_list.addItem("全部")
        for cat in self._tm.get_categories():
            icon = CATEGORY_ICONS.get(cat, "")
            self._cat_list.addItem(f"{icon} {cat}")
        self._cat_list.setCurrentRow(0)
        self._cat_list.currentTextChanged.connect(self._on_category_changed)
        left_layout.addWidget(self._cat_list)

        # Import/Export buttons
        left_layout.addWidget(QLabel("操作"))
        import_btn = QPushButton("导入模板 JSON")
        import_btn.clicked.connect(self._import_template)
        left_layout.addWidget(import_btn)
        export_btn = QPushButton("导出模板 JSON")
        export_btn.clicked.connect(self._export_template)
        left_layout.addWidget(export_btn)
        left_layout.addStretch()

        layout.addWidget(left_panel)

        # Right: template list
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("花字模板")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        right_layout.addWidget(title)

        self._tmpl_list = QListWidget()
        self._tmpl_list.setStyleSheet("""
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #ddd;
            }
            QListWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
            QListWidget::item:hover:!selected {
                background-color: #e8f0fe;
            }
        """)
        self._tmpl_list.itemClicked.connect(self._on_template_clicked)
        right_layout.addWidget(self._tmpl_list, 1)

        # Action buttons
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("套用到 GIF 编辑器")
        apply_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; padding: 8px 16px; "
            "border-radius: 4px; } QPushButton:hover { background-color: #219a52; }"
        )
        apply_btn.clicked.connect(self._apply_template)
        btn_row.addWidget(apply_btn)

        save_btn = QPushButton("保存为我的模板")
        save_btn.clicked.connect(self._save_as_custom)
        btn_row.addWidget(save_btn)

        delete_btn = QPushButton("删除我的模板")
        delete_btn.clicked.connect(self._delete_custom)
        delete_btn.setStyleSheet("QPushButton { color: #e74c3c; }")
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        layout.addWidget(right_panel, 1)

        self._refresh_list()

    def _on_category_changed(self, text: str):
        self._refresh_list()

    def _refresh_list(self):
        self._tmpl_list.clear()
        cat_text = self._cat_list.currentItem().text() if self._cat_list.currentItem() else "全部"
        # Strip icon prefix
        for icon, name in CATEGORY_ICONS.items():
            if cat_text.startswith(icon):
                cat_text = name
                break

        if cat_text == "全部":
            templates = self._tm.get_all_templates()
        else:
            templates = self._tm.get_by_category(cat_text)

        for tmpl in templates:
            prefix = "" if tmpl.built_in else "[自定义] "
            item = QListWidgetItem(f"{prefix}{tmpl.template_name}")
            item.setData(Qt.ItemDataRole.UserRole, tmpl.template_id)
            self._tmpl_list.addItem(item)

    def _on_template_clicked(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        tmpl = self._tm.get_template(tid)
        if tmpl is None:
            return

        # Show preview details
        s = tmpl.style
        detail = (
            f"模板: {tmpl.template_name}\n"
            f"分类: {tmpl.category}\n"
            f"字号: {s.get('font_size', '-')}\n"
            f"颜色: {s.get('fill_color', '-')}\n"
            f"描边: {'是' if s.get('stroke_enabled') else '否'} "
            f"({s.get('stroke_width', 0)}px {s.get('stroke_color', '')})\n"
            f"阴影: {'是' if s.get('shadow_enabled') else '否'}\n"
            f"渐变: {'是' if s.get('gradient_enabled') else '否'}\n"
            f"底色: {'是' if s.get('background_enabled') else '否'}"
        )
        QMessageBox.information(self, "模板详情", detail)

    def _apply_template(self):
        items = self._tmpl_list.selectedItems()
        if not items:
            QMessageBox.warning(self, "提示", "请先选择一个模板")
            return
        tid = items[0].data(Qt.ItemDataRole.UserRole)
        tmpl = self._tm.get_template(tid)
        if tmpl is None:
            return
        self.template_selected.emit(tmpl.style)

    def _save_as_custom(self):
        items = self._tmpl_list.selectedItems()
        if not items:
            QMessageBox.warning(self, "提示", "请先选择一个模板")
            return
        tid = items[0].data(Qt.ItemDataRole.UserRole)
        tmpl = self._tm.get_template(tid)
        if tmpl is None:
            return

        new_name, ok = QInputDialog.getText(
            self, "保存为自定义模板", "模板名称:", text=tmpl.template_name + " (自定义)"
        )
        if not ok or not new_name.strip():
            return

        new_id = f"custom_{len([t for t in self._tm.get_all_templates() if not t.built_in]) + 1:03d}"
        self._tm.save_custom_template(new_id, new_name.strip(), tmpl.category, dict(tmpl.style))
        self._refresh_list()
        logger.info(f"Saved custom template: {new_name}")

    def _delete_custom(self):
        items = self._tmpl_list.selectedItems()
        if not items:
            QMessageBox.warning(self, "提示", "请先选择一个自定义模板")
            return
        tid = items[0].data(Qt.ItemDataRole.UserRole)
        tmpl = self._tm.get_template(tid)
        if tmpl is None:
            return
        if tmpl.built_in:
            QMessageBox.warning(self, "提示", "内置模板不可删除")
            return

        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除模板 '{tmpl.template_name}' 吗？"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._tm.delete_custom_template(tid)
            self._refresh_list()

    def _import_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入模板", "", "JSON 文件 (*.json)"
        )
        if path:
            if self._tm.import_template(path):
                self._refresh_list()
                QMessageBox.information(self, "成功", "模板导入成功")
            else:
                QMessageBox.warning(self, "失败", "模板导入失败，请检查 JSON 格式")

    def _export_template(self):
        items = self._tmpl_list.selectedItems()
        if not items:
            QMessageBox.warning(self, "提示", "请先选择一个模板")
            return
        tid = items[0].data(Qt.ItemDataRole.UserRole)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出模板", f"{tid}.json", "JSON 文件 (*.json)"
        )
        if path:
            if self._tm.export_template(tid, path):
                QMessageBox.information(self, "成功", "模板导出成功")
            else:
                QMessageBox.warning(self, "失败", "模板导出失败")
