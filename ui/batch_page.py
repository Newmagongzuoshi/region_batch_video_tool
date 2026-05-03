import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QProgressBar, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal

from core.batch_task_manager import BatchTaskManager
from utils.logger import get_logger

logger = get_logger()


class BatchWorker(QThread):
    progress = Signal(str, dict)
    finished = Signal()

    def __init__(self, manager: BatchTaskManager, regions: list[dict]):
        super().__init__()
        self._manager = manager
        self._regions = regions

    def run(self):
        try:
            self._manager.run_full_pipeline(self._regions, on_progress=self._on_progress)
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
        finally:
            self.finished.emit()

    def _on_progress(self, step: str, p: dict):
        self.progress.emit(step, p)


class BatchPage(QWidget):
    generate_requested = Signal()

    def __init__(self):
        super().__init__()
        self._manager: BatchTaskManager | None = None
        self._worker: BatchWorker | None = None
        self._running = False
        self._output_dir: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("批量生成")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("一键生成所有地区的 GIF、MP3 和 MP4。结果保存到 output/ 目录。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #7f8c8d; font-size: 13px;")
        layout.addWidget(desc)

        # Status
        self._status_label = QLabel("点击「开始生成」启动批量处理")
        self._status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(self._status_label)

        # Progress bars
        prog_group = QGroupBox("进度")
        prog_layout = QVBoxLayout(prog_group)

        gif_row = QHBoxLayout()
        gif_row.addWidget(QLabel("GIF:"))
        self._gif_bar = QProgressBar()
        gif_row.addWidget(self._gif_bar, 1)
        prog_layout.addLayout(gif_row)

        mp3_row = QHBoxLayout()
        mp3_row.addWidget(QLabel("MP3:"))
        self._mp3_bar = QProgressBar()
        mp3_row.addWidget(self._mp3_bar, 1)
        prog_layout.addLayout(mp3_row)

        mp4_row = QHBoxLayout()
        mp4_row.addWidget(QLabel("MP4:"))
        self._mp4_bar = QProgressBar()
        mp4_row.addWidget(self._mp4_bar, 1)
        prog_layout.addLayout(mp4_row)

        layout.addWidget(prog_group)

        # Buttons
        btn_row = QHBoxLayout()

        self._start_btn = QPushButton("开始生成")
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; font-size: 14px; "
            "font-weight: bold; padding: 10px 24px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #219a52; }"
        )
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(
            "QPushButton { color: #e74c3c; font-size: 14px; padding: 10px 24px; }"
        )
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch()

        open_btn = QPushButton("打开输出目录")
        open_btn.clicked.connect(self._open_output)
        btn_row.addWidget(open_btn)

        layout.addLayout(btn_row)
        layout.addStretch()

    def set_manager(self, manager: BatchTaskManager):
        self._manager = manager

    def start_with_regions(self, regions: list[dict]):
        """Called by MainWindow to start generation immediately."""
        if self._manager is None:
            return
        self._start(regions)

    def _on_start(self):
        """Button click: request MainWindow to prepare and start."""
        self.generate_requested.emit()

    def _start(self, regions: list[dict]):
        if self._manager is None:
            return
        self._running = True
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_label.setText("正在生成...")

        self._worker = BatchWorker(self._manager, regions)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_stop(self):
        if self._manager:
            self._manager.stop()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText("已停止")

    def _on_progress(self, step: str, p: dict):
        cur = p.get("current", 0)
        total = p.get("total", 1)
        if step == "gif":
            self._gif_bar.setMaximum(max(1, total))
            self._gif_bar.setValue(cur)
        elif step == "mp3":
            self._mp3_bar.setMaximum(max(1, total))
            self._mp3_bar.setValue(cur)
        elif step == "mp4":
            self._mp4_bar.setMaximum(max(1, total))
            self._mp4_bar.setValue(cur)

    def _on_finished(self):
        self._running = False
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText("生成完成！请查看 output/报告/ 目录")
        QMessageBox.information(
            self, "完成",
            "批量生成完成！\n\n"
            "输出文件:\n"
            "  output/材料库/  — GIF 和 MP3\n"
            "  output/生成的视频/  — 最终 MP4\n"
            "  output/报告/  — 成功/失败清单"
        )

    def set_output_dir(self, path: str):
        self._output_dir = path

    def _open_output(self):
        import subprocess, sys
        out_dir = self._output_dir or os.path.join(os.getcwd(), "output")
        if sys.platform == "win32" and os.path.isdir(out_dir):
            os.startfile(out_dir)
