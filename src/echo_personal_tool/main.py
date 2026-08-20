"""Launch the desktop application."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Windows timer resolution: request 1ms granularity for PreciseTimer.
# Cleaned up on app exit to allow OS idle states.
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

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
            rss_mb,
            len(np_arrays),
            np_bytes / (1024 * 1024),
            len(gc.get_objects()),
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

# ── Diagnostic file logging for the server download pipeline ──
# Writes DEBUG-level logs from download/query modules to diag.log so partial
# study loads (e.g. "15 of 85 instances") can be diagnosed without console capture.
_DIAG_LOGGERS = (
    "echo_personal_tool.application.workers.orthanc_download_worker",
    "echo_personal_tool.application.services.dicom_retrieve_service",
    "echo_personal_tool.application.dicom_query_service",
    "echo_personal_tool.infrastructure.orthanc_client",
    "echo_personal_tool.infrastructure.dimse_client",
    "echo_personal_tool.infrastructure.embedded_storage_scp",
    "echo_personal_tool.infrastructure.dicom_metadata_mapper",
    "echo_personal_tool.presentation.orthanc_study_dialog",
)
_diag_log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SonoForge" / "logs"
try:
    _diag_log_dir.mkdir(parents=True, exist_ok=True)
    _diag_handler = logging.FileHandler(str(_diag_log_dir / "diag.log"), mode="w", encoding="utf-8")
    _diag_handler.setLevel(logging.DEBUG)
    _diag_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    for _logger_name in _DIAG_LOGGERS:
        logging.getLogger(_logger_name).setLevel(logging.DEBUG)
        logging.getLogger(_logger_name).addHandler(_diag_handler)
except OSError:
    pass

# ── First-run environment check ──
# When running outside PyInstaller and outside a venv, check if deps/models
# are available.  The bash launcher (sonoforge) handles this for normal installs;
# this is a safety net for direct execution.
_is_frozen = getattr(sys, "frozen", False)
if not _is_frozen:
    try:
        from echo_personal_tool.infrastructure.runtime_setup import (
            check_deps,
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

from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtWidgets import QApplication

from echo_personal_tool.infrastructure.profiler import is_enabled, print_summary
from echo_personal_tool.infrastructure.user_preferences import load_user_preferences
from echo_personal_tool.presentation.main_window import MainWindow, apply_maximized_to_work_area
from echo_personal_tool.presentation.pyqtgraph_export import patch_pyqtgraph_export_dialog
from echo_personal_tool.resources.bundled_fonts import ensure_bundled_fonts_loaded, ui_font


def _cleanup_winmm() -> None:
    """Restore Windows timer resolution to default on exit."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass


def _schedule_reference_preload(window: MainWindow) -> None:
    """Warm up the web reference dialog during application idle time.

    QtWebEngine takes a few seconds to load, which delays the first open of the
    reference. We preload the dialog hidden once the event loop is idle so the
    cached dialog appears instantly when the user opens it.
    """

    def _preload_when_idle(attempt: int = 0) -> None:
        app = QApplication.instance()
        if app is not None and app.hasPendingEvents() and attempt < 120:
            # The app is busy (e.g. still handling startup or playback) — retry.
            QTimer.singleShot(1000, lambda: _preload_when_idle(attempt + 1))
            return
        from echo_personal_tool.presentation.ase_reference_dialog import (
            preload_reference_dialog,
        )

        preload_reference_dialog(window)

    QTimer.singleShot(1500, _preload_when_idle)


def main() -> int:
    if "--version" in sys.argv or "-V" in sys.argv:
        from echo_personal_tool import __version__

        print(f"SonoForge {__version__}")
        return 0

    patch_pyqtgraph_export_dialog()
    # QtWebEngine (web reference viewer) and the pyqtgraph QOpenGLWidget must
    # share OpenGL contexts. Without this, on Windows the web view's context
    # (ANGLE/D3D) and the viewer's desktop-GL context fight over the default
    # framebuffer and the viewer ends up showing a live, horizontally-mirrored,
    # color-inverted copy of the main window. Must be set before QApplication.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("SonoForge")

    # Enable OpenGL hardware acceleration for pyqtgraph texture uploads.
    # On Windows with ANGLE this ensures GPU texture upload instead of software rendering.
    try:
        import pyqtgraph as pg

        pg.setConfigOptions(useOpenGL=True)
    except Exception:
        pass

    # Set application icon (window icon + taskbar)
    from PySide6.QtGui import QIcon

    from echo_personal_tool.presentation.dark_theme import get_logo_path

    app.setWindowIcon(QIcon(str(get_logo_path())))

    # Check models after QApplication exists (can show Qt dialog).
    # In frozen (PyInstaller) builds, deps are bundled — only check models.
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
    _schedule_reference_preload(window)
    result = app.exec()
    _cleanup_winmm()
    if is_enabled():
        print_summary()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
