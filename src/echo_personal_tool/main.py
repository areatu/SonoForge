"""Launch the desktop application."""

from __future__ import annotations

import logging
import os
import sys

# KDE Sonnet tries to load hspell (Hebrew) on some Linux desktops; ignore if missing.
# KDE sycoca warns about Cursor's custom MIME type when launched from Cursor terminal.
os.environ.setdefault(
    "QT_LOGGING_RULES",
    "kf.sonnet*=false;kf.sonnet.clients.hspell=false;kf.service.sycoca=false",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
for _logger_name in ("pylibjpeg", "pylibjpeg.utils", "pydicom"):
    logging.getLogger(_logger_name).setLevel(logging.WARNING)
if os.environ.get("ECHO_DEBUG"):
    logging.getLogger("echo_personal_tool").setLevel(logging.DEBUG)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pathlib import Path

from echo_personal_tool.infrastructure.user_preferences import load_user_preferences
from echo_personal_tool.resources.bundled_fonts import ensure_bundled_fonts_loaded, ui_font

from echo_personal_tool.presentation.main_window import MainWindow, apply_maximized_to_work_area
from echo_personal_tool.presentation.pyqtgraph_export import patch_pyqtgraph_export_dialog
from echo_personal_tool.infrastructure.profiler import print_summary, is_enabled


def main() -> int:
    patch_pyqtgraph_export_dialog()
    app = QApplication(sys.argv)
    app.setApplicationName("ECHO Personal Tool")
    ensure_bundled_fonts_loaded()
    preferences = load_user_preferences()
    app.setFont(ui_font(point_size=preferences.ui_font_size))
    window = MainWindow(user_preferences=preferences)
    if preferences.startup_mode == "last_folder" and preferences.last_opened_folder:
        last_folder = Path(preferences.last_opened_folder)
        if last_folder.is_dir():
            QTimer.singleShot(200, lambda: window.open_folder_path(last_folder))
    # Deferred maximize: reliable on Windows (showMaximized in __init__ often leaves a small window).
    QTimer.singleShot(0, lambda: apply_maximized_to_work_area(window))
    result = app.exec()
    if is_enabled():
        print_summary()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
