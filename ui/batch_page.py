import os
import sys
import time
import platform
import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QProgressBar, QMessageBox, QTextEdit,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer

from core.batch_task_manager import BatchTaskManager
from utils.logger import get_logger

logger = get_logger()


def _collect_system_info() -> dict:
    """Collect CPU/GPU/Memory info for display."""
    info = {"cpu": "", "gpu": "", "memory": ""}

    # CPU — try PowerShell first for short name
    cpu_name = ""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-CimInstance Win32_Processor).Name"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            cpu_name = result.stdout.strip().split("\n")[0].strip()
        except Exception:
            pass
    if not cpu_name:
        cpu_name = platform.processor() or "Unknown"
    # Clean up common prefixes
    import re
    cpu_name = re.sub(r'Intel\(R\)\s*Core\(TM\)\s*', '', cpu_name)
    cpu_name = re.sub(r'Intel\(R\)\s*', '', cpu_name)
    cpu_name = re.sub(r'\s+CPU\s*@.*', '', cpu_name)
    cpu_name = re.sub(r'\s+', ' ', cpu_name).strip()
    cores = os.cpu_count() or 1
    info["cpu"] = f"{cpu_name} ({cores} 核)" if cpu_name else f"{cores} 核 CPU"

    # Memory — PowerShell is more reliable than wmic
    mem_str = ""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            gb = result.stdout.strip()
            if gb.isdigit():
                mem_str = f"{gb} GB"
        except Exception:
            pass
    if not mem_str:
        try:
            import psutil
            mem = psutil.virtual_memory()
            mem_str = f"{mem.total / (1024**3):.0f} GB"
        except ImportError:
            mem_str = "未知"
    info["memory"] = mem_str

    # GPU: try multiple methods
    gpus = []
    if sys.platform == "win32":
        # Method 1: PowerShell (most reliable on Windows)
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-CimInstance Win32_VideoController).Name"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            gpus = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()
                    and "OrayIdd" not in l]  # skip virtual displays
        except Exception:
            pass
        # Method 2: nvidia-smi (try common paths)
        if not gpus:
            for nv_path in [r"C:\Windows\System32\nvidia-smi.exe",
                          r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"]:
                try:
                    result = subprocess.run(
                        [nv_path, "--query-gpu=name", "--format=csv,noheader"],
                        capture_output=True, text=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    gpus = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                    if gpus: break
                except Exception:
                    continue
    info["gpu"] = " + ".join(gpus[:2]) if gpus else "未检测到独立显卡"

    return info


class BatchWorker(QThread):
    progress = Signal(str, dict)
    mp4_log = Signal(str, str)  # region, status
    finished = Signal()

    def __init__(self, manager: BatchTaskManager, regions: list[dict]):
        super().__init__()
        self._manager = manager
        self._regions = regions

    def run(self):
        try:
            self._manager.run_full_pipeline(
                self._regions,
                on_progress=self._on_progress,
                on_mp4_done=self._on_mp4_done,
            )
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
        finally:
            self.finished.emit()

    def _on_progress(self, step: str, p: dict):
        self.progress.emit(step, p)

    def _on_mp4_done(self, region: str, status: str):
        self.mp4_log.emit(region, status)


class BatchPage(QWidget):
    generate_requested = Signal()

    def __init__(self):
        super().__init__()
        self._manager: BatchTaskManager | None = None
        self._worker: BatchWorker | None = None
        self._running = False
        self._output_dir: str = ""
        self._start_time: float = 0
        self._elapsed_timer: QTimer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Title + timer row
        header_row = QHBoxLayout()
        title = QLabel("批量生成")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        header_row.addWidget(title)
        header_row.addStretch()
        self._timer_label = QLabel("00:00")
        self._timer_label.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #e67e22; "
            "background: #2c3e50; padding: 4px 12px; border-radius: 4px;"
        )
        self._timer_label.setVisible(False)
        header_row.addWidget(self._timer_label)
        layout.addLayout(header_row)

        desc = QLabel("一键生成所有地区的 MP4 视频。结果保存到 output/ 目录。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #7f8c8d; font-size: 13px;")
        layout.addWidget(desc)

        # System info + generation scheme side by side
        info_row = QHBoxLayout()

        # 电脑配置
        sys_info = _collect_system_info()
        hw_group = QGroupBox("电脑配置")
        hw_layout = QVBoxLayout(hw_group)
        self._hw_cpu_label = QLabel(f"CPU: {sys_info['cpu']}")
        self._hw_gpu_label = QLabel(f"GPU: {sys_info['gpu']}")
        self._hw_mem_label = QLabel(f"内存: {sys_info['memory']}")
        for lbl in [self._hw_cpu_label, self._hw_gpu_label, self._hw_mem_label]:
            lbl.setStyleSheet("color: #2c3e50; font-size: 12px;")
            lbl.setWordWrap(True)
            hw_layout.addWidget(lbl)
        info_row.addWidget(hw_group)

        # 生成方案
        plan_group = QGroupBox("生成方案（速度排序）")
        plan_layout = QVBoxLayout(plan_group)
        # Hint showing all options
        hint = QLabel("① NVIDIA NVENC  >  ② AMD AMF  >  ③ Intel QSV  >  ④ CPU x264")
        hint.setStyleSheet("color: #888; font-size: 10px;")
        hint.setWordWrap(True)
        plan_layout.addWidget(hint)
        self._plan_encoder = QLabel("编码器: 等待初始化...")
        self._plan_workers = QLabel("并发数: -")
        self._plan_split = QLabel("视频分段: -")
        self._plan_tts = QLabel("语音合成: -")
        for lbl in [self._plan_encoder, self._plan_workers, self._plan_split, self._plan_tts]:
            lbl.setStyleSheet("color: #2c3e50; font-size: 12px;")
            lbl.setWordWrap(True)
            plan_layout.addWidget(lbl)
        info_row.addWidget(plan_group)

        layout.addLayout(info_row)

        # Status
        self._status_label = QLabel("点击「开始生成」启动批量处理")
        self._status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(self._status_label)

        # Progress bar (MP4 only)
        prog_group = QGroupBox("进度")
        prog_layout = QVBoxLayout(prog_group)

        mp4_row = QHBoxLayout()
        mp4_row.addWidget(QLabel("MP4:"))
        self._mp4_bar = QProgressBar()
        mp4_row.addWidget(self._mp4_bar, 1)
        prog_layout.addLayout(mp4_row)

        layout.addWidget(prog_group)

        # MP4 output log
        log_group = QGroupBox("MP4 生成记录")
        log_layout = QVBoxLayout(log_group)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(160)
        self._log_text.setStyleSheet(
            "font-family: Consolas, '微软雅黑'; font-size: 12px; "
            "background-color: #1a1a2e; color: #e0e0e0;"
        )
        log_layout.addWidget(self._log_text)
        layout.addWidget(log_group)

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

    def set_manager(self, manager: BatchTaskManager):
        self._manager = manager

    def update_scheme_info(self, encoder_desc: str, workers: int, use_split: bool, head_dur: float = 0, tts_desc: str = ""):
        """Update generation scheme display after initialization."""
        rank_map = {
            "NVIDIA NVENC GPU": "① 最快",
            "AMD AMF GPU": "② 快",
            "Intel QSV GPU": "③ 较快",
            "CPU x264": "④ 慢",
        }
        rank = rank_map.get(encoder_desc, "")
        self._plan_encoder.setText(f"编码器: {encoder_desc}  {rank}")
        self._plan_workers.setText(f"并发数: {workers} 线程")
        if use_split:
            self._plan_split.setText(f"视频分段: head({head_dur:.1f}s)+tail 复用模式")
        else:
            self._plan_split.setText("视频分段: 完整源编码模式")
        if tts_desc:
            self._plan_tts.setText(f"语音合成: {tts_desc}")

    def start_with_regions(self, regions: list[dict]):
        if self._manager is None:
            return
        self._start(regions)

    def _on_start(self):
        self.generate_requested.emit()

    def _start(self, regions: list[dict]):
        if self._manager is None:
            return
        self._running = True
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_label.setText("正在生成...")
        self._log_text.clear()

        # Start timer
        self._start_time = time.time()
        self._timer_label.setVisible(True)
        self._timer_label.setText("00:00")
        self._elapsed_timer = QTimer()
        self._elapsed_timer.timeout.connect(self._tick_timer)
        self._elapsed_timer.start(200)

        # Disconnect previous worker to avoid duplicate finished dialogs
        if self._worker:
            try:
                self._worker.progress.disconnect(self._on_progress)
                self._worker.mp4_log.disconnect(self._on_mp4_log)
                self._worker.finished.disconnect(self._on_finished)
            except RuntimeError:
                pass
        self._worker = BatchWorker(self._manager, regions)
        self._worker.progress.connect(self._on_progress)
        self._worker.mp4_log.connect(self._on_mp4_log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _tick_timer(self):
        elapsed = int(time.time() - self._start_time)
        self._timer_label.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")

    def _on_stop(self):
        if self._manager:
            self._manager.stop()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText("已停止")
        if self._elapsed_timer:
            self._elapsed_timer.stop()

    def _on_progress(self, step: str, p: dict):
        cur = p.get("current", 0)
        total = p.get("total", 1)
        if step == "mp4":
            self._mp4_bar.setMaximum(max(1, total))
            self._mp4_bar.setValue(cur)

    def _on_mp4_log(self, region: str, status: str):
        color = "#27ae60" if status == "ok" else "#e74c3c"
        icon = "OK" if status == "ok" else "FAIL"
        self._log_text.append(
            f'<span style="color:{color}">[{icon}] {region}.mp4</span>'
        )

    def _on_finished(self):
        self._running = False
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        if self._elapsed_timer:
            self._elapsed_timer.stop()
        self._tick_timer()
        elapsed = int(time.time() - self._start_time)

        # Count success and calculate per-video average
        ok_count = 0
        fail_count = 0
        for line in self._log_text.toPlainText().splitlines():
            if line.startswith("[OK]"):
                ok_count += 1
            elif line.startswith("[FAIL]"):
                fail_count += 1
        total_count = ok_count + fail_count
        avg_str = ""
        if ok_count > 0:
            avg_s = elapsed / ok_count
            avg_str = f"平均每个视频: {avg_s:.1f} 秒"

        self._status_label.setText(
            f"生成完成！耗时 {elapsed // 60}分{elapsed % 60}秒 | 报告: AA视频生成报告.txt"
        )
        QMessageBox.information(
            self, "完成",
            f"批量生成完成！\n\n"
            f"成功: {ok_count} 个  "
            f"失败: {fail_count} 个  "
            f"总耗时: {elapsed} 秒\n"
            f"{avg_str}\n"
            f"输出目录: 生成的视频/"
        )

    def set_output_dir(self, path: str):
        self._output_dir = path

    def _open_output(self):
        import subprocess, sys
        out_dir = self._output_dir or os.path.join(os.getcwd(), "output")
        if sys.platform == "win32" and os.path.isdir(out_dir):
            os.startfile(out_dir)
