"""Small privacy-safe projection for known error boundaries, not a log sanitizer.

Only static operation/code tokens and a coarse exception category are emitted.
Never serialize exception messages, arguments, custom class names or tracebacks.
This does not change UI outcomes or make other/raw logging PHI-free.
"""

from __future__ import annotations

import logging

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
        "onnx.submit",
        "onnx.result",
        "onnx.timeout",
        "onnx.cleanup",
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
        "unexpected",
    }
)
# Order matters: TimeoutError is an OSError subclass. Unknown/custom classes
# fall back to a built-in parent, never to their potentially identifying name.
_CATEGORIES = (TimeoutError, OSError, ValueError, TypeError, RuntimeError, MemoryError)


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
    operation = operation if type(operation) is str and operation in _OPERATIONS else "unknown"
    code = safe_failure_code(code)
    category = next((kind.__name__ for kind in _CATEGORIES if isinstance(error, kind)), "Exception")
    logger.log(
        level,
        "operation=%s code=%s error_type=%s",
        operation,
        code,
        category,
        exc_info=None,
        stack_info=False,
    )
