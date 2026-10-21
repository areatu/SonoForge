"""Sections column of the report mode (UI-4 PR-2, spec §4.6).

Shows the report sections with ✓ / ◐ / ○ and a counter, then the measurements
the TP protocols still expect.  «измерить» asks the window to switch back to
«Изображения» and arm the protocol step; «не оценивалось» is an explicit,
reversible mark kept in memory for this UI session.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.protocols import StudyProjection
from echo_personal_tool.domain.services.report_sections import (
    ReportSection,
    ReportSectionItem,
    SectionStatus,
    build_report_sections,
)
from echo_personal_tool.infrastructure.i18n import get_language, tr
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

#: Spec §4.6: the sections column is 284 px wide.
_SECTIONS_WIDTH = 284

_STATUS_GLYPH: dict[SectionStatus, str] = {
    SectionStatus.DONE: "✓",
    SectionStatus.PARTIAL: "◐",
    SectionStatus.EMPTY: "○",
}


class ReportSectionsPanel(QFrame):
    """«Разделы» and «Не заполнено» beside the A4 sheet."""

    measure_requested = Signal(str, int)  # protocol_id, step_index
    #: The explicit «не оценивалось» marks changed (they print, PR-5).
    not_evaluated_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportSections")
        self.setFixedWidth(_SECTIONS_WIDTH)
        self._projection: StudyProjection | None = None
        self._sections: tuple[ReportSection, ...] = ()
        self._not_evaluated: set[str] = set()
        self._frozen = False

        self._title = QLabel()
        self._title.setObjectName("reportSectionsTitle")
        self._counter = QLabel()
        self._counter.setObjectName("reportSectionsCounter")

        header = QHBoxLayout()
        header.setContentsMargins(10, 8, 10, 4)
        header.setSpacing(6)
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._counter)

        self._host = QWidget()
        self._host.setObjectName("reportSectionsHost")
        self._list = QVBoxLayout(self._host)
        self._list.setContentsMargins(8, 0, 8, 8)
        self._list.setSpacing(2)
        self._list.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("reportSectionsScroll")
        scroll.viewport().setObjectName("reportSectionsViewport")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._host)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)

        self._retranslate()
        self.apply_theme()

    # ── Content ─────────────────────────────────────────────────────────
    def set_projection(self, projection: StudyProjection | None) -> None:
        """Rebuild from the study projection (``None`` = nothing measured)."""
        self._projection = projection
        self._sections = build_report_sections(projection, get_language())
        known = {item.key for section in self._sections for item in section.items}
        self._not_evaluated &= known
        self._rebuild()

    @property
    def sections(self) -> tuple[ReportSection, ...]:
        return self._sections

    def marked_not_evaluated(self) -> frozenset[str]:
        return frozenset(self._not_evaluated)

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def set_frozen(self, frozen: bool) -> None:
        """A finished version is read-only: no new marks and no «измерить».

        The marks themselves stay on screen — they are part of the frozen
        version, they are not editable in it (UQ-07).
        """
        frozen = bool(frozen)
        if frozen == self._frozen:
            return
        self._frozen = frozen
        self._rebuild()

    def reload_text(self) -> None:
        """Re-localize section and measurement labels in place."""
        self._sections = build_report_sections(self._projection, get_language())
        self._retranslate()
        self._rebuild()

    # ── View ────────────────────────────────────────────────────────────
    def _retranslate(self) -> None:
        self._title.setText(tr("report.sections"))
        done = sum(section.status is SectionStatus.DONE for section in self._sections)
        self._counter.setText(tr("report.sections_counter", done=done, total=len(self._sections)))
        self._counter.setToolTip(tr("report.sections_counter_hint"))

    def _rebuild(self) -> None:
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for section in self._sections:
            self._list.insertWidget(self._list.count() - 1, self._section_row(section))

        missing = [
            item
            for section in self._sections
            for item in section.items
            if not item.filled and item.key not in self._not_evaluated
        ]
        marked = [item for section in self._sections for item in section.items if item.key in self._not_evaluated]

        if missing:
            self._list.insertWidget(self._list.count() - 1, self._subheader(tr("report.not_filled")))
            for item in missing:
                self._list.insertWidget(self._list.count() - 1, self._missing_row(item, marked=False))

        if marked:
            self._list.insertWidget(self._list.count() - 1, self._subheader(tr("report.not_evaluated")))
            for item in marked:
                self._list.insertWidget(self._list.count() - 1, self._missing_row(item, marked=True))

        done = sum(section.status is SectionStatus.DONE for section in self._sections)
        self._counter.setText(tr("report.sections_counter", done=done, total=len(self._sections)))

    def _section_row(self, section: ReportSection) -> QWidget:
        row = QWidget()
        row.setObjectName("reportSectionRow")
        row.setProperty("status", section.status.value)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)

        glyph = QLabel(_STATUS_GLYPH[section.status])
        glyph.setObjectName("reportSectionGlyph")
        glyph.setProperty("status", section.status.value)
        glyph.setFixedWidth(16)
        glyph.setToolTip(tr(f"report.section_{section.status.value}"))
        layout.addWidget(glyph)

        title = QLabel(section.title)
        title.setObjectName("reportSectionTitle")
        title.setToolTip(tr(f"report.section_{section.status.value}"))
        layout.addWidget(title, 1)

        count = QLabel(f"{section.filled}/{section.total}")
        count.setObjectName("reportSectionCounter")
        layout.addWidget(count)
        return row

    def _subheader(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("reportSectionsSubheader")
        return label

    def _missing_row(self, item: ReportSectionItem, *, marked: bool) -> QWidget:
        row = QWidget()
        row.setObjectName("reportMissingRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        label = QLabel(item.label)
        label.setObjectName("reportMissingLabel")
        label.setProperty("marked", marked)
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        if not marked:
            measure = QPushButton(tr("report.measure"))
            measure.setObjectName("reportMeasureLink")
            measure.setEnabled(not self._frozen)
            measure.setFlat(True)
            measure.setCursor(Qt.CursorShape.PointingHandCursor)
            measure.setProperty("key", item.key)
            measure.setToolTip(tr("report.measure_hint"))
            measure.clicked.connect(
                lambda _checked=False, p=item.protocol_id, s=item.step_index: self.measure_requested.emit(p, s)
            )
            layout.addWidget(measure)

        toggle = QPushButton("✓" if marked else "○")
        toggle.setObjectName("reportNotEvaluated")
        toggle.setFlat(True)
        toggle.setCheckable(True)
        toggle.setChecked(marked)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setProperty("key", item.key)
        toggle.setEnabled(not self._frozen)
        toggle.setToolTip(tr("report.not_evaluated_undo") if marked else tr("report.not_evaluated_hint"))
        toggle.clicked.connect(lambda _checked=False, key=item.key: self._toggle_not_evaluated(key))
        layout.addWidget(toggle)
        return row

    def _toggle_not_evaluated(self, key: str) -> None:
        if self._frozen:
            return
        if key in self._not_evaluated:
            self._not_evaluated.discard(key)
        else:
            self._not_evaluated.add(key)
        self._rebuild()
        self.not_evaluated_changed.emit()

    # ── Styling ─────────────────────────────────────────────────────────
    def apply_theme(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #reportSections {{
                background: {tokens["surface.2"]};
                border-right: 1px solid {tokens["line.1"]};
            }}
            #reportSectionsTitle {{
                color: {tokens["text.3"]};
                font-weight: 600;
            }}
            #reportSectionsCounter {{
                color: {tokens["accent.text"]};
            }}
            #reportSectionsHost, #reportSectionsScroll, #reportSectionsViewport {{
                background: {tokens["surface.2"]};
            }}
            #reportSectionGlyph[status="done"] {{
                color: {tokens["state.ok"]};
            }}
            #reportSectionGlyph[status="partial"] {{
                color: {tokens["state.warn"]};
            }}
            #reportSectionGlyph[status="empty"] {{
                color: {tokens["text.3"]};
            }}
            #reportSectionTitle {{
                color: {tokens["text.2"]};
            }}
            #reportSectionCounter {{
                color: {tokens["text.3"]};
            }}
            #reportSectionsSubheader {{
                color: {tokens["text.3"]};
                font-weight: 600;
                padding: 6px 2px 2px 2px;
            }}
            #reportMissingLabel {{
                color: {tokens["text.2"]};
            }}
            #reportMissingLabel[marked="true"] {{
                color: {tokens["text.disabled"]};
                font-style: italic;
            }}
            #reportMeasureLink {{
                color: {tokens["accent.text"]};
                border: none;
                padding: 0 2px;
            }}
            #reportMeasureLink:hover {{
                text-decoration: underline;
            }}
            #reportNotEvaluated {{
                color: {tokens["text.3"]};
                border: none;
                padding: 0 2px;
            }}
            #reportNotEvaluated:checked {{
                color: {tokens["accent.text"]};
            }}
            """
        )
