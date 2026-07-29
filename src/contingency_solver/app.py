import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from contingency_solver.constants import APP_NAME
from contingency_solver.gui.main_window import MainWindow
from contingency_solver.utilities.logging_config import configure_logging


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    configure_logging()
    logger = logging.getLogger(__name__)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    logger.info("Qt event loop starting.")
    return app.exec()
