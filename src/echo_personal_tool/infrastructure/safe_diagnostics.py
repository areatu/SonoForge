"""Small privacy-safe projection for known error boundaries, not a log sanitizer.

Only static operation/code tokens and a coarse exception category are emitted.
Never serialize exception messages, arguments, custom class names or tracebacks.
This does not change UI outcomes or make other/raw logging PHI-free.
"""

from __future__ import annotations

import logging
import re

_OPERATIONS = frozenset(
    {
        "measurement.task",
        "measurement.list",
        "measurement.load",
        "measurement.save",
        "measurement.reconcile",
        "measurement.delete_all",
        "measurement.delete",
        "measurement.export",
        "measurement.import",
        "measurement.import_preview",
        "measurement.close",
        "calibration.manual",
        "mp4.export",
        "orthanc.download",
        "onnx.submit",
        "onnx.result",
        "onnx.timeout",
        "onnx.cleanup",
        "crash.main",
        "crash.thread",
        "logging.qt_message",
        "logging.cleanup",
    }
)
_CODES = frozenset(
    {
        "io",
        "identity",
        "invalid",
        "limit",
        "source",
        "unaccepted",
        "version",
        "busy",
        "conflict",
        "quota",
        "unsafe_path",
        "blocked",
        "inference",
        "timeout",
        "cleanup",
        "cancelled",
        "no_adapter",
        "not_received",
        "move_destination",
        "all_sources_failed",
        "no_adapters",
        "unexpected",
    }
)
# Order matters: TimeoutError is an OSError subclass. Unknown/custom classes
# fall back to a built-in parent, never to their potentially identifying name.
_CATEGORIES = (TimeoutError, OSError, ValueError, TypeError, RuntimeError, MemoryError)
_SAFE_LOG_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} "
    r"\[(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\] [A-Za-z0-9_.-]+: "
    r"operation=(?P<operation>[a-z0-9_.]+) code=(?P<code>[a-z_]+) error_type=(?P<category>[A-Za-z]+)$"
)
_SAFE_CATEGORIES = frozenset(kind.__name__ for kind in _CATEGORIES) | {"Exception", "QtMessage"}


def project_safe_diagnostic_lines(text: str) -> str:
    """Project only complete, allowlisted boundary events into shareable logs.

    Raw session/crash logs are useful locally but contain untrusted tracebacks,
    Qt messages and exception text.  Support bundles may include only events
    written in the strict ``log_boundary_failure`` schema; the logger name,
    timestamp and all other producer text are discarded.
    """
    safe_lines: list[str] = []
    for line in text.splitlines():
        match = _SAFE_LOG_LINE.fullmatch(line)
        if match is None:
            continue
        operation = match.group("operation")
        code = match.group("code")
        category = match.group("category")
        if operation not in _OPERATIONS or code not in _CODES or category not in _SAFE_CATEGORIES:
            continue
        safe_lines.append(f"operation={operation} code={code} error_type={category}")
    return "\n".join(safe_lines)


def log_boundary_event(
    logger: logging.Logger,
    operation: str,
    code: str,
    category: str,
    *,
    level: int = logging.WARNING,
) -> None:
    """Emit a fully static allowlisted diagnostic event without an exception object."""
    operation = operation if type(operation) is str and operation in _OPERATIONS else "unknown"
    code = safe_failure_code(code)
    category = category if type(category) is str and category in _SAFE_CATEGORIES else "Exception"
    logger.log(
        level,
        "operation=%s code=%s error_type=%s",
        operation,
        code,
        category,
        exc_info=None,
        stack_info=False,
    )


def safe_failure_code(code: object, *, fallback: str = "unexpected") -> str:
    """Return only a stable, approved diagnostic/status code.

    Storage boundaries may receive a custom ``MeasurementStorageError.code``
    from an adapter or a fault-injection test.  It must not cross into a UI
    status or log line as arbitrary text, where it can carry a path, UID or
    payload fragment.
    """
    return code if type(code) is str and code in _CODES else fallback


def log_boundary_failure(
    logger: logging.Logger,
    operation: str,
    error: BaseException,
    *,
    code: str = "unexpected",
    level: int = logging.WARNING,
) -> None:
    """Record allowlisted context without formatting the untrusted exception."""
    category = next((kind.__name__ for kind in _CATEGORIES if isinstance(error, kind)), "Exception")
    log_boundary_event(logger, operation, code, category, level=level)
