"""Launch the desktop application."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_LOG = logging.getLogger(__name__)


def _begin_winmm() -> None:
    """Request 1ms timer resolution for Qt PreciseTimer on Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(1)
    except (AttributeError, OSError) as exc:
        _LOG.debug("Could not request Windows 1ms timer resolution (%s)", type(exc).__name__)


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
        from echo_personal_tool.infrastructure.playback_diagnostics import (
            peak_rss_mb,
            process_rss_mb,
        )

        # `resource` does not exist on Windows: psutil covers both (see peak_rss_mb).
        rss_mb = process_rss_mb()
        peak_mb = peak_rss_mb()
        # Count live numpy arrays and their total size
        import numpy as _np

        np_arrays = [o for o in gc.get_objects() if isinstance(o, _np.ndarray)]
        np_bytes = sum(a.nbytes for a in np_arrays)
        _mem_log.warning(
            "[mem_top] RSS=%.0f MB peak_RSS=%.0f MB numpy_arrays=%d numpy_MB=%.0f GC_objects=%d",
            rss_mb,
            peak_mb,
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

# ── First-run environment check ──
# When running outside PyInstaller and outside a venv, check if deps/models
# are available.  The bash launcher (sonoforge) handles this for normal installs;
# this is a safety net for direct execution.  The Presenter profile has a
# reduced dependency set, so the full-profile check does not apply to it.
_is_frozen = getattr(sys, "frozen", False)
from echo_personal_tool.infrastructure.profile import is_presenter as _is_presenter

if not _is_frozen and not _is_presenter():
    try:
        from echo_personal_tool.infrastructure.runtime_setup import (
            check_deps,
        )

        if not check_deps():
            print(  # noqa: T201 - CLI dependency error is written to stderr
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
            _LOG.debug("Could not restore Windows timer resolution", exc_info=True)


def _schedule_reference_preload(window: MainWindow) -> None:
    """Warm up the web reference dialog during application idle time.

    QtWebEngine takes a few seconds to load, which delays the first open of the
    reference. We preload the dialog hidden once the event loop is idle so the
    cached dialog appears instantly when the user opens it.
    """

    def _preload_when_idle(attempt: int = 0) -> None:
        app = QApplication.instance()
        if app is not None and hasattr(app, "hasPendingEvents") and app.hasPendingEvents() and attempt < 120:
            # The app is busy (e.g. still handling startup or playback) — retry.
            QTimer.singleShot(1000, lambda: _preload_when_idle(attempt + 1))
            return
        from echo_personal_tool.presentation.ase_reference_dialog import (
            preload_reference_dialog,
        )

        preload_reference_dialog(window)

    QTimer.singleShot(1500, _preload_when_idle)


def main() -> int:
    from echo_personal_tool.infrastructure.profile import (
        display_name,
        has_ai_segmentation,
        has_reference_ui,
    )

    if "--version" in sys.argv or "-V" in sys.argv:
        from echo_personal_tool import __version__

        print(f"{display_name()} {__version__}")  # noqa: T201 - CLI output
        return 0

    # QtWebEngine (web reference viewer) and the pyqtgraph QOpenGLWidget must
    # share OpenGL contexts. This attribute has to be set before QApplication.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName(display_name())

    from echo_personal_tool.infrastructure.logging_setup import (
        configure_logging,
        shutdown_logging,
    )

    configure_logging(app)
    _begin_winmm()
    try:
        return _run_application(app, has_ai_segmentation, has_reference_ui)
    finally:
        _cleanup_winmm()
        # Deterministic teardown: flush/close the rotating session log and
        # restore root/logger levels. Relying on atexit alone leaves the active
        # logging session behind when main() returns in-process (e.g. in tests),
        # which corrupts logger levels for any code that runs afterwards.
        shutdown_logging()


def _run_application(app: QApplication, has_ai_segmentation, has_reference_ui) -> int:  # noqa: ANN001
    """Configure optional features and enter Qt's event loop."""
    patch_pyqtgraph_export_dialog()

    # OpenGL for the pyqtgraph viewport - only when a real GPU backs it. On software GL
    # (llvmpipe in a VM, WARP over RDP, GDI Generic without a driver) the GL viewport is
    # slower than Qt's raster paint engine for the 2D blits this viewer does, and in
    # pyqtgraph 0.13/0.14 `useOpenGL` only changes the viewport: ImageItem keeps going
    # through QImage + QPainter either way. ECHO_USE_OPENGL=0|1 overrides the probe.
    try:
        import pyqtgraph as pg

        from echo_personal_tool.infrastructure.system_profiler import (
            detect_opengl_capability,
        )

        use_opengl, _reason = detect_opengl_capability()
        pg.setConfigOptions(useOpenGL=use_opengl)
    except Exception:
        _LOG.warning("OpenGL capability probe failed; Qt's default renderer will be used", exc_info=True)

    # Set application icon (window icon + taskbar)
    from PySide6.QtGui import QIcon

    from echo_personal_tool.presentation.dark_theme import get_logo_path

    app.setWindowIcon(QIcon(str(get_logo_path())))

    # Check models after QApplication exists (can show Qt dialog).
    # In frozen (PyInstaller) builds, deps are bundled — only check models.
    # The Presenter profile ships without ONNX/models — nothing to download.
    if has_ai_segmentation():
        try:
            from echo_personal_tool.infrastructure.runtime_setup import (
                check_models,
                show_setup_dialog,
            )

            if not check_models():
                show_setup_dialog()
        except Exception:
            _LOG.exception("Could not check or prepare optional AI models; continuing without setup")
    ensure_bundled_fonts_loaded()
    preferences = load_user_preferences()
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language(preferences.language)
    app.setFont(ui_font(point_size=preferences.ui_font_size))
    window = MainWindow(user_preferences=preferences)
    if preferences.startup_mode == "last_folder" and preferences.last_opened_folder:
        last_folder = Path(preferences.last_opened_folder)
        if last_folder.is_dir():
            QTimer.singleShot(200, lambda: window.open_folder_path(last_folder))
    # Deferred maximize: reliable on Windows (showMaximized in __init__ often leaves a small window).
    QTimer.singleShot(0, lambda: apply_maximized_to_work_area(window))
    if has_reference_ui():
        _schedule_reference_preload(window)
    result = app.exec()
    if is_enabled():
        print_summary()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
