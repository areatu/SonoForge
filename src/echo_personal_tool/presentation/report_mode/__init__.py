"""Report mode (UI-4): the A4 preview page, its sections and geometry.

PR-1 ships the mode itself — the patient-line switch, the per-tab state and
this preview. PR-2 adds the sections column, PR-3 the phrases column with the
conclusion draft, PR-4 the «откуда значение» card (on :mod:`.view_map` and the
lineage stored in the document) and PR-5 the export block: PDF, print and the
per-tab finished version.
"""

from __future__ import annotations

from echo_personal_tool.presentation.report_mode.export import ReportExportPanel
from echo_personal_tool.presentation.report_mode.page import ReportModePage
from echo_personal_tool.presentation.report_mode.phrases import PhraseEditorDialog, ReportPhrasesPanel
from echo_personal_tool.presentation.report_mode.preview import ReportPreview, SheetVersion
from echo_personal_tool.presentation.report_mode.provenance import ReportValueCard
from echo_personal_tool.presentation.report_mode.sections import ReportSectionsPanel

__all__ = [
    "PhraseEditorDialog",
    "ReportExportPanel",
    "ReportModePage",
    "ReportPhrasesPanel",
    "ReportPreview",
    "ReportSectionsPanel",
    "ReportValueCard",
    "SheetVersion",
]
