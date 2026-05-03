from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
)
from PySide6.QtCore import Qt

from core.api_key_manager import ApiKeyManager
from utils.logger import get_logger

logger = get_logger()


class ApiKeyDialog(QDialog):
    def __init__(self, parent=None, edit_data: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("编辑 API Key 配置" if edit_data else "新增 API Key 配置")
        self.setMinimumWidth(500)

        layout = QFormLayout(self)

        self._config_id_edit = QLineEdit()
        if edit_data:
            self._config_id_edit.setText(edit_data.get("config_id", ""))
            self._config_id_edit.setReadOnly(True)
        else:
            self._config_id_edit.setPlaceholderText("如: my_tts_001")
        layout.addRow("配置ID:", self._config_id_edit)

        self._name_edit = QLineEdit()
        if edit_data:
            self._name_edit.setText(edit_data.get("display_name", ""))
        self._name_edit.setPlaceholderText("如: 我的TTS接口")
        layout.addRow("显示名称:", self._name_edit)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["custom_http", "volcengine", "aliyun", "tencent", "azure"])
        if edit_data:
            idx = self._provider_combo.findText(edit_data.get("provider", "custom_http"))
            if idx >= 0:
                self._provider_combo.setCurrentIndex(idx)
        layout.addRow("服务商:", self._provider_combo)

        self._endpoint_edit = QLineEdit()
        if edit_data:
            self._endpoint_edit.setText(edit_data.get("endpoint", ""))
        self._endpoint_edit.setPlaceholderText("https://api.example.com/tts")
        layout.addRow("Endpoint:", self._endpoint_edit)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("输入 API Key")
        layout.addRow("API Key:", self._api_key_edit)

        self._secret_key_edit = QLineEdit()
        self._secret_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._secret_key_edit.setPlaceholderText("可选")
        layout.addRow("Secret Key:", self._secret_key_edit)

        self._app_id_edit = QLineEdit()
        self._app_id_edit.setPlaceholderText("可选")
        layout.addRow("App ID:", self._app_id_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict:
        return {
            "config_id": self._config_id_edit.text().strip(),
            "display_name": self._name_edit.text().strip(),
            "provider": self._provider_combo.currentText(),
            "endpoint": self._endpoint_edit.text().strip(),
            "api_key": self._api_key_edit.text().strip(),
            "secret_key": self._secret_key_edit.text().strip(),
            "app_id": self._app_id_edit.text().strip(),
        }


class ApiKeyPage(QWidget):
    def __init__(self):
        super().__init__()
        self._mgr = ApiKeyManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("API Key 管理")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("API Key 使用加密存储，不会明文写入配置文件或日志。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #7f8c8d;")
        layout.addWidget(desc)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["配置ID", "名称", "服务商", "API Key", "状态"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        # Buttons
        btn_row = QHBoxLayout()
        add_btn = QPushButton("新增配置")
        add_btn.clicked.connect(self._add_config)
        btn_row.addWidget(add_btn)

        edit_btn = QPushButton("编辑配置")
        edit_btn.clicked.connect(self._edit_config)
        btn_row.addWidget(edit_btn)

        delete_btn = QPushButton("删除配置")
        delete_btn.clicked.connect(self._delete_config)
        delete_btn.setStyleSheet("QPushButton { color: #e74c3c; }")
        btn_row.addWidget(delete_btn)

        toggle_btn = QPushButton("启用 / 禁用")
        toggle_btn.clicked.connect(self._toggle_config)
        btn_row.addWidget(toggle_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._refresh_table()

    def _refresh_table(self):
        configs = self._mgr.list_configs()
        self._table.setRowCount(len(configs))
        for i, c in enumerate(configs):
            self._table.setItem(i, 0, QTableWidgetItem(c["config_id"]))
            self._table.setItem(i, 1, QTableWidgetItem(c["display_name"]))
            self._table.setItem(i, 2, QTableWidgetItem(c["provider"]))
            self._table.setItem(i, 3, QTableWidgetItem(c["masked_key"]))
            status = "启用" if c["enabled"] else "禁用"
            self._table.setItem(i, 4, QTableWidgetItem(status))

    def _add_config(self):
        dlg = ApiKeyDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            if not data["config_id"] or not data["api_key"]:
                QMessageBox.warning(self, "提示", "配置ID和API Key不能为空")
                return
            self._mgr.add_key(
                config_id=data["config_id"],
                api_key=data["api_key"],
                display_name=data["display_name"],
                secret_key=data["secret_key"],
                app_id=data["app_id"],
                endpoint=data["endpoint"],
                provider=data["provider"],
            )
            self._refresh_table()

    def _edit_config(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择一个配置")
            return
        cid = self._table.item(rows[0].row(), 0).text()
        entry = self._mgr.get_entry(cid)
        if not entry:
            return

        dlg = ApiKeyDialog(self, {
            "config_id": cid,
            "display_name": entry.get("display_name", ""),
            "provider": entry.get("provider", ""),
            "endpoint": entry.get("endpoint", ""),
        })
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            new_key = data["api_key"] or self._mgr.get_key(cid)
            self._mgr.add_key(
                config_id=cid,
                api_key=new_key,
                display_name=data["display_name"],
                secret_key=data["secret_key"] or self._mgr.get_secret_key(cid),
                app_id=data["app_id"] or self._mgr.get_app_id(cid),
                endpoint=data["endpoint"],
                provider=data["provider"],
            )
            self._refresh_table()

    def _delete_config(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择一个配置")
            return
        cid = self._table.item(rows[0].row(), 0).text()
        reply = QMessageBox.question(self, "确认删除", f"确定删除配置 '{cid}' 吗？")
        if reply == QMessageBox.StandardButton.Yes:
            self._mgr.delete_key(cid)
            self._refresh_table()

    def _toggle_config(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择一个配置")
            return
        cid = self._table.item(rows[0].row(), 0).text()
        entry = self._mgr.get_entry(cid)
        if entry:
            new_state = not entry.get("enabled", True)
            self._mgr.set_enabled(cid, new_state)
            self._refresh_table()
