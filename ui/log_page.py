import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt

from core.task_store import TaskStore
from utils.path_utils import resolve_data_path
from utils.logger import get_logger

logger = get_logger()


class LogPage(QWidget):
    def __init__(self):
        super().__init__()
        self._store = TaskStore()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("任务日志")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("筛选:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["全部", "失败的任务", "已完成的任务", "正在运行的任务"])
        self._filter_combo.currentTextChanged.connect(self._refresh_log)
        filter_row.addWidget(self._filter_combo)
        filter_row.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_log)
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        # Log display
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(
            "font-family: Consolas, '微软雅黑'; font-size: 12px; background-color: #1a1a2e; color: #e0e0e0;"
        )
        layout.addWidget(self._log_text, 1)

        # Export buttons
        btn_row = QHBoxLayout()

        export_failed_btn = QPushButton("导出失败任务 (JSON)")
        export_failed_btn.clicked.connect(self._export_failed)
        btn_row.addWidget(export_failed_btn)

        export_csv_btn = QPushButton("导出完整报告 (CSV)")
        export_csv_btn.clicked.connect(self._export_csv)
        btn_row.addWidget(export_csv_btn)

        open_log_btn = QPushButton("打开日志文件")
        open_log_btn.clicked.connect(self._open_log_file)
        btn_row.addWidget(open_log_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._refresh_log()

    def _refresh_log(self):
        self._log_text.clear()
        filter_text = self._filter_combo.currentText()

        tasks = self._store.get_all_tasks()
        if filter_text == "失败的任务":
            tasks = [t for t in tasks if "failed" in [
                t.get("gif_status", ""), t.get("mp3_status", ""), t.get("mp4_status", "")
            ]]
        elif filter_text == "已完成的任务":
            tasks = [
                t for t in tasks
                if t.get("gif_status") == "completed"
                and t.get("mp3_status") == "completed"
                and t.get("mp4_status") == "completed"
            ]

        if not tasks:
            self._log_text.append("暂无任务记录\n")
            return

        for t in tasks:
            status_line = (
                f"[{t.get('id', '?')}] {t.get('region', '?')} | "
                f"GIF:{t.get('gif_status', '?')} MP3:{t.get('mp3_status', '?')} MP4:{t.get('mp4_status', '?')}"
            )
            color = "#27ae60" if "failed" not in status_line else "#e74c3c"
            self._log_text.append(f'<span style="color:{color}">{status_line}</span>')
            if t.get("error_message"):
                self._log_text.append(
                    f'  <span style="color:#e74c3c">错误: {t["error_message"]}</span>'
                )
            self._log_text.append("")

    def _export_failed(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出失败任务", "failed_tasks.json", "JSON 文件 (*.json)"
        )
        if path:
            self._store.export_failed_json(path)
            QMessageBox.information(self, "成功", f"失败任务已导出到:\n{path}")

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出完整报告", "batch_report.csv", "CSV 文件 (*.csv)"
        )
        if path:
            self._store.export_batch_csv(path)
            QMessageBox.information(self, "成功", f"完整报告已导出到:\n{path}")

    def _open_log_file(self):
        import subprocess, sys
        log_path = resolve_data_path("logs", "app.log")
        if sys.platform == "win32":
            os.startfile(log_path)
        else:
            subprocess.run(["xdg-open", log_path])
