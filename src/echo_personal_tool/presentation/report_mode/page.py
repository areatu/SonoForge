"""The report mode page of the main window (UI-4 PR-1, spec §4.6).

One surface per window, shown instead of the images content while the active
tab is in «Отчёт» mode.  PR-1 puts the A4 preview in the middle; PR-2 adds the
sections column on the left.  The phrases/export column on the right (PR-3/
PR-5) joins this same row later, so the window assembly does not change again.
The old :class:`ReportDialog` keeps its entry points until those slices land —
the mode is additive, not a replacement yet.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from echo_personal_tool.domain.protocols import StudyProjection
from echo_personal_tool.domain.services.report_builder import ReportDocument
from echo_personal_tool.presentation.report_mode.preview import ReportPreview
from echo_personal_tool.presentation.report_mode.sections import ReportSectionsPanel


class ReportModePage(QWidget):
    """Container of the report mode: sections, preview, and later the phrases."""

    measure_requested = Signal(str, int)  # protocol_id, step_index

    def __init__(
        self,
        document_provider: Callable[[], ReportDocument] | None = None,
        *,
        projection_provider: Callable[[], StudyProjection] | None = None,
        font_size: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reportModePage")
        self._projection_provider = projection_provider
        self._sections = ReportSectionsPanel(parent=self)
        self._sections.measure_requested.connect(self.measure_requested)
        self._preview = ReportPreview(document_provider, font_size=font_size, parent=self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sections)
        layout.addWidget(self._preview, 1)

    @property
    def preview(self) -> ReportPreview:
        return self._preview

    @property
    def sections(self) -> ReportSectionsPanel:
        return self._sections

    def _refresh_sections(self) -> None:
        projection = self._projection_provider() if self._projection_provider is not None else None
        self._sections.set_projection(projection)

    def request_refresh(self) -> None:
        self._refresh_sections()
        self._preview.request_refresh()

    def refresh_now(self) -> bool:
        self._refresh_sections()
        return self._preview.refresh_now()

    def set_font_size(self, font_size: int) -> None:
        self._preview.set_font_size(font_size)

    def reload_text(self) -> None:
        self._sections.reload_text()
        self._preview.reload_text()

    def apply_theme(self) -> None:
        self._sections.apply_theme()
        self._preview.apply_theme()
