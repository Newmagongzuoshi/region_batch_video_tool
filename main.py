import sys
import os

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from utils.logger import setup_logging
from core.file_manager import init_app_dirs
from ui.main_window import MainWindow


def main():
    setup_logging()
    init_app_dirs()

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setApplicationName("矩量拓客：地区视频批量生成")

    # Global checkbox style — enlarge indicator without breaking native checkmark
    app.setStyleSheet("""
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
