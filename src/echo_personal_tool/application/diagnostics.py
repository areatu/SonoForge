"""Application facade for the diagnostics port (S2-03, #307).

Presentation observes failures, sanitizes log text, builds support bundles and
prefills issue links through this Qt-free contract instead of importing the
infrastructure diagnostics helpers directly.  The adapters stay in
``infrastructure``; this module re-exports the public surface.

The import is module-level by design: every re-exported adapter is Qt-free at
import time (verified by ``test_application_io_facades_have_no_qt_imports``)
and ``log_boundary_failure`` runs on hot error paths.  The profile adapter is
pulled transitively via ``infrastructure.paths`` (portable-mode root) and is
equally Qt-free.
"""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.infrastructure.diagnostics import create_diagnostic_bundle
from echo_personal_tool.infrastructure.log_sanitizer import sanitize_log_text
from echo_personal_tool.infrastructure.profile import diag_log_dir
from echo_personal_tool.infrastructure.safe_diagnostics import (
    log_boundary_event,
    log_boundary_failure,
    safe_error_category,
)
from echo_personal_tool.infrastructure.support_report import (
    build_issue_url,
    environment_text,
)

__all__ = [
    "build_issue_url",
    "create_diagnostic_bundle",
    "diag_log_dir",
    "environment_text",
    "log_boundary_event",
    "log_boundary_failure",
    "safe_error_category",
    "sanitize_log_text",
]
