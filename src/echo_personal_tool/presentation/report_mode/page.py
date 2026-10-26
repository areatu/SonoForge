"""The report mode page of the main window (UI-4 PR-1…PR-5, spec §4.6).

One surface per window, shown instead of the images content while the active
tab is in «Отчёт» mode.  The row grew slice by slice: PR-1 put the A4 preview
in the middle, PR-2 added the sections column on the left, PR-3 the phrases
column with the conclusion draft, PR-4 the «откуда значение» hover and PR-5 the
export block (PDF, print, finish) under the phrases.

The page owns no study state: the document provider comes from the window, the
projection provider from the controller, and the conclusion draft and the
finished version from the active tab.  That keeps the sheet, the sections and
the conclusion in one place (S-11) and lets the tab switch restore each study's
own text and its own frozen version.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from echo_personal_tool.application.report_phrases import ReportPhraseStore
from echo_personal_tool.domain.protocols import StudyProjection
from echo_personal_tool.domain.services.report_builder import ReportDocument
from echo_personal_tool.presentation.report_mode.export import ReportExportPanel
from echo_personal_tool.presentation.report_mode.patient import ReportPatientEditor
from echo_personal_tool.presentation.report_mode.phrases import PANEL_WIDTH, ReportPhrasesPanel
from echo_personal_tool.presentation.report_mode.preview import ReportPreview
from echo_personal_tool.presentation.report_mode.provenance import ClipLabelProvider
from echo_personal_tool.presentation.report_mode.sections import ReportSectionsPanel


class ReportModePage(QWidget):
    """Container of the report mode: sections, sheet, phrases and export."""

    patient_field_changed = Signal(str, str)
    measure_requested = Signal(str, int)  # protocol_id, step_index
    conclusion_changed = Signal(str)
    #: «Открыть кадры» of the «откуда значение» card (PR-4).
    open_frames_requested = Signal(str, int)  # sop_instance_uid, frame_index
    #: Export block intents (PR-5); the window owns dialogs and the filesystem.
    export_requested = Signal()
    print_requested = Signal()
    finish_requested = Signal()
    draft_requested = Signal()

    def __init__(
        self,
        document_provider: Callable[[], ReportDocument] | None = None,
        *,
        projection_provider: Callable[[], StudyProjection] | None = None,
        phrase_store: ReportPhraseStore | None = None,
        font_size: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reportModePage")
        self._projection_provider = projection_provider
        self._finished = False
        self._sections = ReportSectionsPanel(parent=self)
        self._sections.measure_requested.connect(self.measure_requested)
        self._preview = ReportPreview(document_provider, font_size=font_size, parent=self)
        self._preview.open_frames_requested.connect(self.open_frames_requested)
        self._phrases = ReportPhrasesPanel(phrase_store, parent=self)
        self._phrases.conclusion_changed.connect(self.conclusion_changed)
        self._export = ReportExportPanel(parent=self)
        self._export.export_requested.connect(self.export_requested)
        self._export.print_requested.connect(self.print_requested)
        self._export.finish_requested.connect(self.finish_requested)
        self._export.draft_requested.connect(self.draft_requested)

        right = QWidget()
        right.setObjectName("reportRightColumn")
        right.setFixedWidth(PANEL_WIDTH)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._phrases, 1)
        right_layout.addWidget(self._export, 0)

        self.patient_editor = ReportPatientEditor()
        self.patient_editor.field_changed.connect(self.patient_field_changed)
        left_content = QWidget()
        left_layout = QVBoxLayout(left_content)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.patient_editor)
        left_layout.addWidget(self._sections, 1)
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setFrameShape(QScrollArea.Shape.NoFrame)
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left.setFixedWidth(self._sections.width() + 20)
        left.setWidget(left_content)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(left)
        layout.addWidget(self._preview, 1)
        layout.addWidget(right)

    @property
    def preview(self) -> ReportPreview:
        return self._preview

    @property
    def sections(self) -> ReportSectionsPanel:
        return self._sections

    @property
    def phrases(self) -> ReportPhrasesPanel:
        return self._phrases

    @property
    def export(self) -> ReportExportPanel:
        return self._export

    @property
    def conclusion(self) -> str:
        """The conclusion draft as shown in the right column."""
        return self._phrases.conclusion

    @property
    def is_finished(self) -> bool:
        """Whether the page shows a finished (read-only) version (UQ-07)."""
        return self._finished

    @property
    def pdf_bytes(self) -> bytes:
        """The exact bytes of the sheet — what export and print use (§8.4)."""
        return self._preview.pdf_bytes

    @property
    def document(self) -> ReportDocument | None:
        return self._preview.document

    def marked_not_evaluated(self) -> frozenset[str]:
        """Explicit «не оценивалось» marks of the session (they print, PR-5)."""
        return self._sections.marked_not_evaluated()

    def set_conclusion(self, text: str) -> None:
        """Show the draft of the active tab without emitting an edit."""
        self._phrases.set_conclusion(text)

    def set_clip_label_provider(self, provider: ClipLabelProvider | None) -> None:
        """Name clips the way the gallery does inside the hover card."""
        self._preview.set_clip_label_provider(provider)

    def set_finished(self, finished: bool) -> None:
        """Freeze or unfreeze the whole page (UQ-07).

        A finished version keeps its bytes: the sheet, the sections marks and
        the conclusion become read-only and no refresh follows the study.
        «Новый черновик» unfreezes everything and rebuilds from the study.
        """
        self._finished = bool(finished)
        self.patient_editor.setEnabled(not self._finished)
        self._preview.set_frozen(self._finished)
        self._sections.set_frozen(self._finished)
        self._phrases.set_read_only(self._finished)
        self._export.set_finished(self._finished)

    def set_status(self, text: str) -> None:
        """Outcome line of the export block (PDF saved, printed, failure)."""
        self._export.set_status(text)

    def _refresh_sections(self) -> None:
        projection = self._projection_provider() if self._projection_provider is not None else None
        self._sections.set_projection(projection)

    def request_refresh(self) -> None:
        if self._finished:
            return
        self._refresh_sections()
        self._preview.request_refresh()

    def refresh_now(self) -> bool:
        if self._finished:
            return False
        self._refresh_sections()
        return self._preview.refresh_now()

    def set_font_size(self, font_size: int) -> None:
        self._preview.set_font_size(font_size)

    def reload_text(self) -> None:
        self.patient_editor.reload_text()
        self._sections.reload_text()
        self._phrases.reload_text()
        self._export.reload_text()
        self._preview.reload_text()

    def apply_theme(self) -> None:
        self._sections.apply_theme()
        self._phrases.apply_theme()
        self._export.apply_theme()
        self._preview.apply_theme()
