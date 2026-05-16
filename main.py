import sys
import os
import ctypes

# Windows taskbar icon fix — must be before Qt import
if sys.platform == "win32":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RegionBatchVideoTool")

# High DPI — must be set before any Qt import
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon

from utils.logger import setup_logging
from utils.path_utils import resolve_path
from core.file_manager import init_app_dirs
from ui.main_window import MainWindow


def main():
    setup_logging()
    init_app_dirs()

    # Qt 6 high DPI — AA_EnableHighDpiScaling is deprecated (always on in Qt 6)
    # PassThrough keeps fractional scaling exact (no blur from rounding)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("矩量拓客：地区视频批量生成")

    # App icon (taskbar + window)
    import os as _os
    icon_path = resolve_path("assets", "icon.ico")
    if _os.path.isfile(icon_path):
        app_icon = QIcon(icon_path)
        app.setWindowIcon(app_icon)

    # System font for consistent rendering across DPI scales
    font = QFont("Microsoft YaHei", 9)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    # Global styles — prevent white-on-white on light-theme systems
    app.setStyleSheet("""
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
            background: #fff;
            color: #333;
        }
        QCheckBox {
            font-size: 13px;
            spacing: 10px;
            padding: 4px 0;
        }
        QCheckBox::indicator {
            width: 22px;
            height: 22px;
        }
        QCheckBox:checked {
            color: #1e8449;
            font-weight: bold;
        }
    """)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
