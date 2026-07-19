"""Launch the desktop application."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Memory diagnostics: log top allocations every 10s when ECHO_FREEZE_DIAG=1
if os.environ.get("ECHO_FREEZE_DIAG") == "1":
    import tracemalloc
    tracemalloc.start(25)  # 25 frames deep for useful traces
    import threading as _thr
    _mem_log = logging.getLogger("echo_freeze_diag")

    def _mem_dump() -> None:
        import gc
        gc.collect()
        snap = tracemalloc.take_snapshot()
        top = snap.statistics("lineno")
        _mem_log.warning("[mem_top] === Top 10 allocations ===")
        for stat in top[:10]:
            _mem_log.warning("[mem_top] %s", stat)
        import resource
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        # Count live numpy arrays and their total size
        import numpy as _np
        np_arrays = [o for o in gc.get_objects() if isinstance(o, _np.ndarray)]
        np_bytes = sum(a.nbytes for a in np_arrays)
        _mem_log.warning(
            "[mem_top] RSS=%.0f MB numpy_arrays=%d numpy_MB=%.0f GC_objects=%d",
            rss_mb, len(np_arrays), np_bytes / (1024 * 1024), len(gc.get_objects()),
        )
        _thr.Timer(10.0, _mem_dump).start()

    _thr.Timer(10.0, _mem_dump).start()

# KDE Sonnet tries to load hspell (Hebrew) on some Linux desktops; ignore if missing.
# KDE sycoca warns about Cursor's custom MIME type when launched from Cursor terminal.
os.environ.setdefault(
    "QT_LOGGING_RULES",
    "kf.sonnet*=false;kf.sonnet.clients.hspell=false;kf.service.sycoca=false",
)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
for _logger_name in ("pylibjpeg", "pylibjpeg.utils", "pydicom"):
    logging.getLogger(_logger_name).setLevel(logging.ERROR)
if os.environ.get("ECHO_DEBUG"):
    logging.getLogger("echo_personal_tool").setLevel(logging.DEBUG)

# ── First-run environment check ──
# When running outside PyInstaller and outside a venv, check if deps/models
# are available.  The bash launcher (sonoforge) handles this for normal installs;
# this is a safety net for direct execution.
_is_frozen = getattr(sys, "frozen", False)
if not _is_frozen:
    try:
        from echo_personal_tool.infrastructure.runtime_setup import (
            check_deps,
            check_models,
        )
        if not check_deps():
            print(
                "SonoForge: missing Python dependencies.\n"
                "Run the launcher: /opt/sonoforge/sonoforge\n"
                "Or install: pip install -e .",
                file=sys.stderr,
            )
            raise SystemExit(1)
    except ImportError:
        pass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from echo_personal_tool.infrastructure.user_preferences import load_user_preferences
from echo_personal_tool.resources.bundled_fonts import ensure_bundled_fonts_loaded, ui_font

from echo_personal_tool.presentation.main_window import MainWindow, apply_maximized_to_work_area
from echo_personal_tool.presentation.pyqtgraph_export import patch_pyqtgraph_export_dialog
from echo_personal_tool.infrastructure.profiler import print_summary, is_enabled


def main() -> int:
    patch_pyqtgraph_export_dialog()
    app = QApplication(sys.argv)
    app.setApplicationName("SonoForge")

    # Check models after QApplication exists (can show Qt dialog)
    if not _is_frozen:
        try:
            from echo_personal_tool.infrastructure.runtime_setup import (
                check_models,
                show_setup_dialog,
            )
            if not check_models():
                show_setup_dialog()
        except Exception:
            pass
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
