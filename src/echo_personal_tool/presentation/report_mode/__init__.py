"""Report mode (UI-4): the A4 preview page and its ``QPdfView`` geometry.

PR-1 ships the mode itself — the patient-line switch, the per-tab state and
this preview. The sections column (PR-2), the phrases (PR-3), the
«откуда значение» hover (PR-4, on :mod:`.view_map`) and print/finish (PR-5)
extend the same package.
"""

from __future__ import annotations

from echo_personal_tool.presentation.report_mode.page import ReportModePage
from echo_personal_tool.presentation.report_mode.preview import ReportPreview

__all__ = ["ReportModePage", "ReportPreview"]
