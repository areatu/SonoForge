"""Launch the desktop application."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.pyqtgraph_export import patch_pyqtgraph_export_dialog


def main() -> int:
    patch_pyqtgraph_export_dialog()
    app = QApplication(sys.argv)
    app.setApplicationName("ECHO Personal Tool")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
