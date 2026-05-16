import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QTextEdit, QFileDialog, QMessageBox,
    QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QThread

from core.region_reader import RegionReader
from core.ffmpeg_service import FFmpegService
from utils.logger import get_logger

logger = get_logger()


class MaterialCheckThread(QThread):
    result_ready = Signal(dict)

    def __init__(self, ffmpeg_service, video_path, gif_path, txt_path, output_dir):
        super().__init__()
        self._ffmpeg = ffmpeg_service
        self._video_path = video_path
        self._gif_path = gif_path
        self._txt_path = txt_path
        self._output_dir = output_dir

    def run(self):
        result = {"ok": True, "errors": [], "warnings": [], "info": {}}

        # Check video
        if not os.path.isfile(self._video_path):
            result["ok"] = False
            result["errors"].append("元视频文件不存在")
        else:
            video_info = self._ffmpeg.probe_video(self._video_path)
            if video_info.width == 0:
                result["ok"] = False
                result["errors"].append("无法读取视频信息，请确认文件为有效 MP4")
            else:
                result["info"]["video"] = {
                    "width": video_info.width,
                    "height": video_info.height,
                    "fps": round(video_info.fps, 2),
                    "duration": round(video_info.duration, 2),
                    "has_audio": video_info.has_audio,
                }

        # Check GIF
        if not os.path.isfile(self._gif_path):
            result["ok"] = False
            result["errors"].append("元 GIF 文件不存在")
        else:
            try:
                from PIL import Image
                img = Image.open(self._gif_path)
                frames = getattr(img, "n_frames", 0)
                result["info"]["gif"] = {
                    "width": img.width,
                    "height": img.height,
                    "frames": frames,
                    "is_animated": frames > 1,
                }
                img.close()
            except Exception as e:
                result["ok"] = False
                result["errors"].append(f"无法解析 GIF: {e}")

        # Check region txt
        if not os.path.isfile(self._txt_path):
            result["ok"] = False
            result["errors"].append("地区.txt 文件不存在")
        else:
            reader = RegionReader()
            regions = reader.load(self._txt_path)
            result["info"]["regions"] = {"count": len(regions)}
            if len(regions) == 0:
                result["ok"] = False
                result["errors"].append("地区.txt 为空或无有效行")

        # Check output dir
        try:
            os.makedirs(self._output_dir, exist_ok=True)
            test_file = os.path.join(self._output_dir, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except Exception as e:
            result["ok"] = False
            result["errors"].append(f"输出目录不可写: {e}")

        # Check disk space
        try:
            import shutil
            usage = shutil.disk_usage(self._output_dir)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < 1:
                result["warnings"].append(f"磁盘空间不足 1GB (剩余 {free_gb:.1f}GB)")
            result["info"]["disk"] = {"free_gb": round(free_gb, 1)}
        except Exception:
            pass

        self.result_ready.emit(result)


class ImportPage(QWidget):
    import_done = Signal(dict)

    def __init__(self):
        super().__init__()
        self._ffmpeg = FFmpegService()
        self._check_result: dict | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("素材导入")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("导入元视频、元 GIF 图片和地区文本文件，系统将根据这些素材批量生成地区化短视频。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #7f8c8d; font-size: 13px;")
        layout.addWidget(desc)

        # Video
        video_group = QGroupBox("元视频 (MP4)")
        video_layout = QHBoxLayout(video_group)
        self.video_path_edit = QLineEdit()
        self.video_path_edit.setPlaceholderText("选择元视频.mp4...")
        video_btn = QPushButton("选择视频")
        video_btn.clicked.connect(self._select_video)
        video_layout.addWidget(self.video_path_edit, 1)
        video_layout.addWidget(video_btn)
        layout.addWidget(video_group)

        # GIF
        gif_group = QGroupBox("元 GIF 图片 (透明动图)")
        gif_layout = QHBoxLayout(gif_group)
        self.gif_path_edit = QLineEdit()
        self.gif_path_edit.setPlaceholderText("选择元gif图片.gif...")
        gif_btn = QPushButton("选择 GIF")
        gif_btn.clicked.connect(self._select_gif)
        gif_layout.addWidget(self.gif_path_edit, 1)
        gif_layout.addWidget(gif_btn)
        layout.addWidget(gif_group)

        # Region txt
        txt_group = QGroupBox("地区列表 (TXT)")
        txt_layout = QHBoxLayout(txt_group)
        self.txt_path_edit = QLineEdit()
        self.txt_path_edit.setPlaceholderText("选择地区.txt...")
        txt_btn = QPushButton("选择 TXT")
        txt_btn.clicked.connect(self._select_txt)
        txt_layout.addWidget(self.txt_path_edit, 1)
        txt_layout.addWidget(txt_btn)
        layout.addWidget(txt_group)

        # Output dir
        out_group = QGroupBox("输出目录")
        out_layout = QHBoxLayout(out_group)
        self.out_dir_edit = QLineEdit()
        self.out_dir_edit.setPlaceholderText("默认: output/")
        out_btn = QPushButton("选择输出目录")
        out_btn.clicked.connect(self._select_output_dir)
        out_layout.addWidget(self.out_dir_edit, 1)
        out_layout.addWidget(out_btn)
        layout.addWidget(out_group)

        # Check button
        self.check_btn = QPushButton("检查素材")
        self.check_btn.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white; font-size: 14px; "
            "padding: 10px 20px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2980b9; }"
        )
        self.check_btn.clicked.connect(self._check_materials)
        layout.addWidget(self.check_btn)

        # Progress
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Result area
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(200)
        self.result_text.setStyleSheet("font-family: Consolas, '微软雅黑'; font-size: 12px;")
        layout.addWidget(self.result_text)

        # FFmpeg status
        ffmpeg_status = "FFmpeg: 已检测到" if self._ffmpeg.is_available else "FFmpeg: 未检测到 (视频合成不可用)"
        ffmpeg_label = QLabel(ffmpeg_status)
        ffmpeg_label.setStyleSheet(
            f"color: {'#27ae60' if self._ffmpeg.is_available else '#e74c3c'}; font-size: 12px;"
        )
        layout.addWidget(ffmpeg_label)

        layout.addStretch()

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择元视频", "", "MP4 视频 (*.mp4);;所有文件 (*.*)"
        )
        if path:
            self.video_path_edit.setText(path)

    def _select_gif(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择元 GIF", "", "GIF 图片 (*.gif);;所有文件 (*.*)"
        )
        if path:
            self.gif_path_edit.setText(path)

    def _select_txt(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择地区 TXT", "", "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if path:
            self.txt_path_edit.setText(path)

    def _select_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.out_dir_edit.setText(path)

    def _check_materials(self):
        video_path = self.video_path_edit.text().strip()
        gif_path = self.gif_path_edit.text().strip()
        txt_path = self.txt_path_edit.text().strip()
        out_dir = self.out_dir_edit.text().strip() or "output"

        if not video_path or not gif_path or not txt_path:
            QMessageBox.warning(self, "提示", "请先选择元视频、元 GIF 和地区 TXT 文件")
            return

        self.check_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.result_text.clear()

        self._check_thread = MaterialCheckThread(
            self._ffmpeg, video_path, gif_path, txt_path, out_dir
        )
        self._check_thread.result_ready.connect(self._on_check_done)
        self._check_thread.start()

    def _on_check_done(self, result: dict):
        self.check_btn.setEnabled(True)
        self.progress.setVisible(False)

        self._check_result = result
        text_parts = []

        if result["errors"]:
            text_parts.append("【错误】")
            for e in result["errors"]:
                text_parts.append(f"  ✗ {e}")
            text_parts.append("")

        if result["warnings"]:
            text_parts.append("【警告】")
            for w in result["warnings"]:
                text_parts.append(f"  ⚠ {w}")
            text_parts.append("")

        info = result.get("info", {})
        if "video" in info:
            v = info["video"]
            text_parts.append(f"【视频】{v['width']}x{v['height']}, {v['fps']}fps, {v['duration']}s, "
                            f"音频: {'有' if v['has_audio'] else '无'}")

        if "gif" in info:
            g = info["gif"]
            text_parts.append(f"【GIF】{g['width']}x{g['height']}, {g['frames']}帧, "
                            f"动图: {'是' if g['is_animated'] else '否'}")

        if "regions" in info:
            r = info["regions"]
            text_parts.append(f"【地区】{r['count']} 个地区")

        if "disk" in info:
            text_parts.append(f"【磁盘】剩余 {info['disk']['free_gb']}GB")

        if result["ok"]:
            text_parts.append("")
            text_parts.append("✓ 素材检查通过！可以进入下一步。")
            self.result_text.setStyleSheet(
                "font-family: Consolas, '微软雅黑'; font-size: 12px; color: #27ae60;"
            )
        else:
            self.result_text.setStyleSheet(
                "font-family: Consolas, '微软雅黑'; font-size: 12px; color: #e74c3c;"
            )

        self.result_text.setText("\n".join(text_parts))

        if result["ok"]:
            gif_path = self.gif_path_edit.text().strip()
            result["paths"] = {
                "video": self.video_path_edit.text().strip(),
                "gif": gif_path,
                "txt": self.txt_path_edit.text().strip(),
                "output": self.out_dir_edit.text().strip() or "output",
            }
            # Extract text colors from GIF for auto-styling
            try:
                from PIL import Image
                from core.font_style_analyzer import quick_sample_colors
                gif_img = Image.open(gif_path)
                gif_img.seek(0)
                frame = gif_img.copy().convert('RGBA')
                colors = quick_sample_colors(frame)
                result["colors"] = colors
                gif_img.close()
            except Exception:
                result["colors"] = None
            self.import_done.emit(result)

    def get_check_result(self) -> dict | None:
        return self._check_result
