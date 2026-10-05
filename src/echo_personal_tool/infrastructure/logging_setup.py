"""Session-scoped application logging and crash hooks.

This module is intentionally explicit: importing SonoForge does not create
files or install global exception handlers. :func:`configure_logging` is
called from ``main()`` once the application can write to its platform data
folder.
"""

from __future__ import annotations

import atexit
import faulthandler
import logging
import os
import platform
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

from echo_personal_tool import __version__
from echo_personal_tool.infrastructure.paths import logs_dir, migrate_legacy_paths

if TYPE_CHECKING:
    from PySide6.QtGui import QGuiApplication

_LOG = logging.getLogger(__name__)

# These modules emit detailed transfer progress that is useful in a support
# bundle, but is too noisy at DEBUG for the rest of the application.
_DIAGNOSTIC_LOGGERS = (
    "echo_personal_tool.infrastructure.dicom_session",
    "echo_personal_tool.application.workers.orthanc_download_worker",
    "echo_personal_tool.application.services.dicom_retrieve_service",
    "echo_personal_tool.application.dicom_query_service",
    "echo_personal_tool.infrastructure.orthanc_client",
    "echo_personal_tool.infrastructure.dimse_client",
    "echo_personal_tool.infrastructure.embedded_storage_scp",
    "echo_personal_tool.infrastructure.dicom_metadata_mapper",
    "echo_personal_tool.presentation.orthanc_study_dialog",
)

_FILE_FORMAT = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3
_active_session: LoggingSession | None = None


@dataclass
class LoggingSession:
    """Resources installed for one SonoForge process."""

    log_directory: Path
    session_id: str
    log_path: Path | None
    crash_path: Path | None
    _handler: logging.Handler | None
    _crash_stream: object | None
    _previous_sys_hook: object
    _previous_thread_hook: object | None
    _previous_qt_handler: object | None
    _qt_handler: object | None
    _thread_hook: object | None
    _sys_hook: object | None
    _previous_root_level: int
    _previous_logger_levels: dict[str, int]
    _faulthandler_enabled_by_session: bool

    def log_environment(self, app: QGuiApplication | None = None) -> str:
        """Write and return the non-PHI runtime header, including Qt screens."""
        text = system_info_text(app)
        logging.getLogger("echo_personal_tool").info("SonoForge session metadata:\n%s", text)
        return text


def system_info_text(app: QGuiApplication | None = None) -> str:
    """Return an allowlisted environment summary with no account or study data."""
    try:
        from PySide6.QtCore import qVersion

        qt_version = qVersion()
    except ImportError:
        qt_version = "unavailable"

    from echo_personal_tool.infrastructure.profile import profile

    lines = [
        f"SonoForge version: {__version__}",
        f"Profile: {profile()}",
        f"Operating system: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Python: {platform.python_version()}",
        f"Qt: {qt_version}",
    ]

    if app is None:
        try:
            from PySide6.QtGui import QGuiApplication

            app = QGuiApplication.instance()
        except ImportError:
            app = None

    screens = app.screens() if app is not None else []
    lines.append(f"Screen count: {len(screens)}")
    for index, screen in enumerate(screens, start=1):
        geometry = screen.geometry()
        scale = float(screen.devicePixelRatio())
        dpi_x = float(screen.logicalDotsPerInchX())
        dpi_y = float(screen.logicalDotsPerInchY())
        lines.append(
            f"Screen {index}: {geometry.width()}x{geometry.height()} at "
            f"({geometry.x()},{geometry.y()}), scale={scale:.2f}, "
            f"logical_dpi={dpi_x:.1f}x{dpi_y:.1f}"
        )
    if not screens:
        lines.append("Screen details: unavailable")

    scale_override = os.environ.get("QT_SCALE_FACTOR")
    if scale_override:
        lines.append(f"QT_SCALE_FACTOR: {scale_override}")
    return "\n".join(lines)


def configure_logging(
    app: QGuiApplication | None = None,
    *,
    directory: Path | None = None,
    max_bytes: int = _MAX_LOG_BYTES,
    backup_count: int = _BACKUP_COUNT,
) -> LoggingSession:
    """Start a rotating log file for this process and install crash hooks.

    A unique filename is created for every run; rotation is bounded within
    that session. Failure to create the log folder never prevents the GUI from
    starting: logging falls back to the existing stderr handler, if any.
    """
    global _active_session
    if _active_session is not None:
        _shutdown_logging()

    target_dir = Path(directory) if directory is not None else logs_dir()
    session_id = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    log_path: Path | None = None
    crash_path: Path | None = None
    file_handler: logging.Handler | None = None
    crash_stream: object | None = None
    faulthandler_was_enabled = faulthandler.is_enabled()
    migration_warnings = migrate_legacy_paths() if directory is None else ()

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        log_path = target_dir / f"session-{session_id}.log"
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(_FILE_FORMAT)
    except OSError as exc:
        log_path = None
        file_handler = None
        logging.getLogger(__name__).warning(
            "File logging is unavailable; continuing with stderr logging (%s)",
            type(exc).__name__,
        )

    root = logging.getLogger()
    previous_root_level = root.level
    root.setLevel(logging.DEBUG)
    if file_handler is not None:
        root.addHandler(file_handler)

    previous_logger_levels: dict[str, int] = {}
    package_logger = logging.getLogger("echo_personal_tool")
    previous_logger_levels["echo_personal_tool"] = package_logger.level
    package_logger.setLevel(logging.DEBUG if os.environ.get("ECHO_DEBUG") else logging.INFO)
    for name in _DIAGNOSTIC_LOGGERS:
        logger = logging.getLogger(name)
        previous_logger_levels[name] = logger.level
    for name in ("pylibjpeg", "pylibjpeg.utils", "pydicom"):
        logger = logging.getLogger(name)
        previous_logger_levels.setdefault(name, logger.level)
        logger.setLevel(logging.ERROR)

    if file_handler is not None and not faulthandler_was_enabled:
        try:
            crash_path = target_dir / f"crash-{session_id}.log"
            crash_stream = crash_path.open("a", encoding="utf-8", buffering=1)
            faulthandler.enable(file=crash_stream, all_threads=True)
        except (OSError, RuntimeError, ValueError) as exc:
            crash_path = None
            if crash_stream is not None:
                crash_stream.close()  # type: ignore[attr-defined]
                crash_stream = None
            logging.getLogger(__name__).warning(
                "faulthandler could not be enabled (%s)",
                type(exc).__name__,
            )

    session = LoggingSession(
        log_directory=target_dir,
        session_id=session_id,
        log_path=log_path,
        crash_path=crash_path,
        _handler=file_handler,
        _crash_stream=crash_stream,
        _previous_sys_hook=sys.excepthook,
        _previous_thread_hook=getattr(threading, "excepthook", None),
        _previous_qt_handler=None,
        _qt_handler=None,
        _thread_hook=None,
        _sys_hook=None,
        _previous_root_level=previous_root_level,
        _previous_logger_levels=previous_logger_levels,
        _faulthandler_enabled_by_session=not faulthandler_was_enabled and crash_stream is not None,
    )
    _active_session = session
    _install_exception_hooks(session)
    _install_qt_message_handler(session)

    _LOG.info("Logging configured for session %s", session_id)
    if log_path is not None:
        _LOG.info("Session log: %s", log_path.name)
    for warning in migration_warnings:
        _LOG.warning("Legacy application data migration: %s", warning)
    session.log_environment(app)
    # Some platform-specific imports above may configure Python loggers; apply
    # the targeted DEBUG overrides last so DICOM diagnostics remain available.
    for name in _DIAGNOSTIC_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)

    # Keep the handler alive through later-registered session/resource atexit
    # cleanup callbacks so their best-effort failures remain in the log.
    atexit.register(shutdown_logging)
    return session


def _install_exception_hooks(session: LoggingSession) -> None:
    def _sys_exception_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            session._previous_sys_hook(exc_type, exc_value, exc_traceback)  # type: ignore[operator]
            return
        logging.getLogger("echo_personal_tool.crash").critical(
            "Uncaught main-thread exception (%s)",
            exc_type.__name__,
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    session._sys_hook = _sys_exception_hook
    sys.excepthook = _sys_exception_hook

    if hasattr(threading, "excepthook"):
        previous = session._previous_thread_hook

        def _thread_exception_hook(args: threading.ExceptHookArgs) -> None:
            logging.getLogger("echo_personal_tool.crash").critical(
                "Uncaught worker-thread exception (%s)",
                args.exc_type.__name__,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            if previous is not None:
                previous(args)  # type: ignore[operator]

        session._thread_hook = _thread_exception_hook
        threading.excepthook = _thread_exception_hook


def _install_qt_message_handler(session: LoggingSession) -> None:
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        logging.getLogger(__name__).warning("Qt message handler is unavailable")
        return

    level_by_type = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def _qt_message_handler(message_type, context, message) -> None:  # noqa: ANN001
        level = level_by_type.get(message_type, logging.WARNING)
        category = getattr(context, "category", None) or "default"
        line = getattr(context, "line", 0) or 0
        logging.getLogger(f"qt.{category}").log(level, "Qt message (line %s): %s", line, message)

    session._previous_qt_handler = qInstallMessageHandler(_qt_message_handler)
    session._qt_handler = _qt_message_handler


def shutdown_logging() -> None:
    """Restore process hooks and close files created by :func:`configure_logging`."""
    _shutdown_logging()


def _shutdown_logging() -> None:
    global _active_session
    session = _active_session
    if session is None:
        return

    if session._sys_hook is not None and sys.excepthook is session._sys_hook:
        sys.excepthook = session._previous_sys_hook  # type: ignore[assignment]
    if session._thread_hook is not None and getattr(threading, "excepthook", None) is session._thread_hook:
        threading.excepthook = session._previous_thread_hook  # type: ignore[assignment]

    try:
        from PySide6.QtCore import qInstallMessageHandler

        if session._qt_handler is not None:
            qInstallMessageHandler(session._previous_qt_handler)
    except (ImportError, RuntimeError):
        logging.getLogger(__name__).debug("Qt message handler could not be restored", exc_info=True)

    if session._faulthandler_enabled_by_session:
        try:
            faulthandler.disable()
        except (RuntimeError, ValueError):
            logging.getLogger(__name__).debug("faulthandler could not be disabled", exc_info=True)

    root = logging.getLogger()
    if session._handler is not None:
        root.removeHandler(session._handler)
        session._handler.flush()
        session._handler.close()
    root.setLevel(session._previous_root_level)
    for name, level in session._previous_logger_levels.items():
        logging.getLogger(name).setLevel(level)
    if session._crash_stream is not None:
        try:
            session._crash_stream.close()  # type: ignore[attr-defined]
        except (OSError, ValueError):
            logging.getLogger(__name__).debug("Crash log stream could not be closed", exc_info=True)

    _active_session = None
