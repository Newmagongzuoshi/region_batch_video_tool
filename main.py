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
    app.setApplicationName("RegionBatchVideoTool")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
























    


if __name__ == "__main__":
    main()
