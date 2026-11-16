"""Sections column of the report mode (UI-4 PR-2, spec §4.6).

The column is the pre-export completeness checklist of the study: section
status, the measurements the selected study type still expects, and the three
incomplete states — missing, stale and unreviewed.  «Измерить» asks the window
to switch back to «Изображения» and arm the protocol step (or the profile tool);
a missing item can be explicitly declared «неприменимо» / «не получено» with a
mandatory reason.  The decision is reversible and prints on the sheet, so an
incomplete export never looks complete.
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

from echo_personal_tool.application.localization import get_language, tr
from echo_personal_tool.domain.protocols import StudyProjection
from echo_personal_tool.domain.services.report_sections import (
    CHECK_DECISION_KINDS,
    ChecklistDecision,
    ChecklistSummary,
    ReportSection,
    ReportSectionItem,
    SectionStatus,
    build_report_sections,
    checklist_summary,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.report_mode.checklist_decision import ChecklistDecisionDialog

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
    #: A profile-tool recommendation without a TP step (organ studies).
    tool_requested = Signal(str)
    #: The explicit «не оценивалось» marks changed (they print, PR-5).
    not_evaluated_changed = Signal()
    #: The physician asked to bring a hidden row of the sheet back (item 9 of
    #: the 2026-11-06 list).  The key addresses the row in the document.
    restore_value_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportSections")
        self.setFixedWidth(_SECTIONS_WIDTH)
        self._projection: StudyProjection | None = None
        self._sections: tuple[ReportSection, ...] = ()
        self._decisions: dict[str, ChecklistDecision] = {}
        self._profile_id = ""
        self._unreviewed = 0
        #: ``(key, label)`` of the rows hidden in the sheet, in document order.
        self._hidden_values: tuple[tuple[str, str], ...] = ()
        self._frozen = False

        self._title = QLabel()
        self._title.setObjectName("reportSectionsTitle")
        self._counter = QLabel()
        self._counter.setObjectName("reportSectionsCounter")
        self._summary = QLabel()
        self._summary.setObjectName("reportChecklistSummary")
        self._summary.setWordWrap(True)
        self._summary.setVisible(False)

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
        layout.addWidget(self._summary)
        layout.addWidget(scroll, 1)

        self._retranslate()
        self.apply_theme()

    # ── Content ─────────────────────────────────────────────────────────
    def set_projection(
        self,
        projection: StudyProjection | None,
        *,
        profile_id: str | None = None,
        unreviewed: int | None = None,
    ) -> None:
        """Rebuild from the study projection (``None`` = nothing measured).

        ``profile_id``/``unreviewed`` are contextual state of the same refresh:
        the study type decides which recommendations are relevant, and the
        unreviewed contour count is the third incomplete state next to missing
        and stale values.
        """
        self._projection = projection
        if profile_id is not None:
            self._profile_id = profile_id
        if unreviewed is not None:
            self._unreviewed = max(int(unreviewed), 0)
        self._refresh()

    def set_profile(self, profile_id: str) -> None:
        """Use the checklist of another study type."""
        if profile_id == self._profile_id:
            return
        self._profile_id = profile_id
        self._refresh()

    def set_unreviewed(self, count: int) -> None:
        """Update the number of contours waiting for a human review."""
        count = max(int(count), 0)
        if count == self._unreviewed:
            return
        self._unreviewed = count
        self._refresh()

    def _refresh(self) -> None:
        self._sections = build_report_sections(
            self._projection,
            get_language(),
            profile_id=self._profile_id,
            decisions=self._decisions,
        )
        known = {item.key for section in self._sections for item in section.items}
        self._decisions = {key: value for key, value in self._decisions.items() if key in known}
        self._rebuild()

    @property
    def sections(self) -> tuple[ReportSection, ...]:
        return self._sections

    def decisions(self) -> dict[str, ChecklistDecision]:
        """Explicit physician decisions by measurement key (a copy)."""
        return dict(self._decisions)

    def marked_not_evaluated(self) -> frozenset[str]:
        """Keys with an explicit decision, kept as the historical API."""
        return frozenset(self._decisions)

    def set_decision(self, key: str, kind: str, reason: str) -> None:
        """Record an explicit decision; a reason is mandatory."""
        if kind not in CHECK_DECISION_KINDS:
            raise ValueError(f"unknown checklist decision: {kind!r}")
        reason = reason.strip()
        if not reason:
            raise ValueError("a checklist decision needs a reason")
        known = {item.key for section in self._sections for item in section.items}
        if key not in known:
            return
        self._decisions[key] = ChecklistDecision(kind=kind, reason=reason)
        self._refresh()
        self.not_evaluated_changed.emit()

    def clear_decision(self, key: str) -> None:
        """Undo the decision: the item returns to the missing list."""
        if self._decisions.pop(key, None) is None:
            return
        self._refresh()
        self.not_evaluated_changed.emit()

    def checklist_summary(self) -> ChecklistSummary:
        """Counts of missing / stale / unreviewed and explicit decisions."""
        return checklist_summary(self._sections, unreviewed=self._unreviewed)

    def set_hidden_values(self, entries: tuple[tuple[str, str], ...]) -> None:
        """Show «Скрытые: N» with a «вернуть» action per row (item 9)."""
        entries = tuple(entries)
        if entries == self._hidden_values:
            return
        self._hidden_values = entries
        self._rebuild()

    @property
    def hidden_values(self) -> tuple[tuple[str, str], ...]:
        return self._hidden_values

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
        self._refresh()
        self._retranslate()

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

        summary = self.checklist_summary()
        self._summary.setText(
            tr(
                "report.checklist.summary",
                missing=summary.missing,
                stale=summary.stale,
                unreviewed=summary.unreviewed,
            )
        )
        self._summary.setToolTip(tr("report.checklist.summary_hint"))
        self._summary.setVisible(bool(self._sections))

        for section in self._sections:
            self._list.insertWidget(self._list.count() - 1, self._section_row(section))

        missing = [
            item
            for section in self._sections
            for item in section.items
            if not item.filled and not item.stale and not item.decision
        ]
        stale = [item for section in self._sections for item in section.items if item.stale]
        marked = [item for section in self._sections for item in section.items if item.decision]

        if missing:
            self._list.insertWidget(self._list.count() - 1, self._subheader(tr("report.not_filled")))
            for row_item in missing:
                self._list.insertWidget(self._list.count() - 1, self._checklist_row(row_item, state="missing"))

        if stale:
            self._list.insertWidget(self._list.count() - 1, self._subheader(tr("report.checklist.stale")))
            for row_item in stale:
                self._list.insertWidget(self._list.count() - 1, self._checklist_row(row_item, state="stale"))

        if marked:
            self._list.insertWidget(self._list.count() - 1, self._subheader(tr("report.not_evaluated")))
            for row_item in marked:
                self._list.insertWidget(self._list.count() - 1, self._checklist_row(row_item, state="decided"))

        if self._unreviewed:
            self._list.insertWidget(self._list.count() - 1, self._subheader(tr("report.checklist.unreviewed")))
            unreviewed = QLabel(tr("report.checklist.unreviewed_count", count=self._unreviewed))
            unreviewed.setObjectName("reportChecklistUnreviewed")
            unreviewed.setWordWrap(True)
            self._list.insertWidget(self._list.count() - 1, unreviewed)

        if self._hidden_values:
            self._list.insertWidget(
                self._list.count() - 1,
                self._subheader(tr("report.hidden_values", count=len(self._hidden_values))),
            )
            for key, label in self._hidden_values:
                self._list.insertWidget(self._list.count() - 1, self._hidden_row(key, label))

        done = sum(section.status is SectionStatus.DONE for section in self._sections)
        self._counter.setText(tr("report.sections_counter", done=done, total=len(self._sections)))

    def _hidden_row(self, key: str, label: str) -> QWidget:
        """One hidden row: its label and «вернуть» — both paths are reversible."""
        row = QWidget()
        row.setObjectName("reportHiddenRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        text = QLabel(label)
        text.setObjectName("reportHiddenLabel")
        text.setWordWrap(True)
        layout.addWidget(text, 1)

        restore = QPushButton(tr("report.restore_value"))
        restore.setObjectName("reportRestoreValue")
        restore.setFlat(True)
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.setProperty("key", key)
        restore.setEnabled(not self._frozen)
        restore.setToolTip(tr("report.restore_value_hint"))
        restore.clicked.connect(lambda _checked=False, row_key=key: self.restore_value_requested.emit(row_key))
        layout.addWidget(restore)
        return row

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

    def _checklist_row(self, item: ReportSectionItem, *, state: str) -> QWidget:
        """One pre-export checklist row: missing, stale or explicitly decided."""
        row = QWidget()
        row.setObjectName("reportMissingRow")
        row.setProperty("state", state)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        if state == "stale":
            glyph = QLabel("⟳")
            glyph.setObjectName("reportChecklistGlyph")
            glyph.setToolTip(tr("report.checklist.stale_hint"))
            layout.addWidget(glyph)

        label = QLabel(item.label)
        label.setObjectName("reportMissingLabel")
        label.setProperty("marked", state == "decided")
        label.setProperty("stale", state == "stale")
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        hint = self._context_hint(item)
        if hint:
            context = QLabel(hint)
            context.setObjectName("reportChecklistHint")
            context.setToolTip(tr("report.checklist.context_hint"))
            layout.addWidget(context)

        if state in ("missing", "stale") and (item.protocol_id or item.tool_id):
            measure = QPushButton(tr("report.measure"))
            measure.setObjectName("reportMeasureLink")
            measure.setEnabled(not self._frozen)
            measure.setFlat(True)
            measure.setCursor(Qt.CursorShape.PointingHandCursor)
            measure.setProperty("key", item.key)
            measure.setToolTip(tr("report.measure_hint"))
            if item.protocol_id:
                measure.clicked.connect(
                    lambda _checked=False, p=item.protocol_id, s=item.step_index: self.measure_requested.emit(p, s)
                )
            else:
                measure.clicked.connect(lambda _checked=False, tool_id=item.tool_id: self.tool_requested.emit(tool_id))
            layout.addWidget(measure)

        if state == "decided":
            decision = QLabel(
                tr("report.checklist.decision", kind=tr(self._decision_key(item.decision)), reason=item.reason)
            )
            decision.setObjectName("reportChecklistDecision")
            decision.setWordWrap(True)
            layout.addWidget(decision)
            undo = QPushButton("✓")
            undo.setObjectName("reportNotEvaluated")
            undo.setFlat(True)
            undo.setCheckable(True)
            undo.setChecked(True)
            undo.setCursor(Qt.CursorShape.PointingHandCursor)
            undo.setProperty("key", item.key)
            undo.setEnabled(not self._frozen)
            undo.setToolTip(tr("report.not_evaluated_undo"))
            undo.clicked.connect(lambda _checked=False, key=item.key: self.clear_decision(key))
            layout.addWidget(undo)
        elif state == "missing":
            toggle = QPushButton("○")
            toggle.setObjectName("reportNotEvaluated")
            toggle.setFlat(True)
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle.setProperty("key", item.key)
            toggle.setEnabled(not self._frozen)
            toggle.setToolTip(tr("report.checklist.decision_hint"))
            toggle.clicked.connect(lambda _checked=False, key=item.key: self._toggle_not_evaluated(key))
            layout.addWidget(toggle)
        else:
            toggle = QPushButton("✓")
            toggle.setObjectName("reportNotEvaluated")
            toggle.setFlat(True)
            toggle.setCheckable(True)
            toggle.setChecked(True)
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle.setProperty("key", item.key)
            toggle.setEnabled(not self._frozen)
            toggle.setToolTip(tr("report.not_evaluated_undo"))
            toggle.clicked.connect(lambda _checked=False, key=item.key: self.clear_decision(key))
            layout.addWidget(toggle)
        return row

    def _context_hint(self, item: ReportSectionItem) -> str:
        """«A4C · ED» — where the missing measurement is taken."""
        frame_key = {"ed": "protocol.frame_ed", "es": "protocol.frame_es"}.get(item.frame_hint)
        frame = tr(frame_key) if frame_key else item.frame_hint
        return " · ".join(part for part in (item.view, frame) if part)

    @staticmethod
    def _decision_key(kind: str) -> str:
        return "report.checklist.not_applicable" if kind == "not_applicable" else "report.checklist.not_obtained"

    def _toggle_not_evaluated(self, key: str) -> None:
        if self._frozen:
            return
        if key in self._decisions:
            self.clear_decision(key)
            return
        item = next((item for section in self._sections for item in section.items if item.key == key), None)
        if item is None:
            return
        decision = ChecklistDecisionDialog.ask(self, item.label, current=self._decisions.get(key))
        if decision is None:
            return
        self.set_decision(key, decision.kind, decision.reason)

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
            #reportChecklistSummary {{
                color: {tokens["text.3"]};
                padding: 0 10px 4px 10px;
            }}
            #reportChecklistHint {{
                color: {tokens["text.3"]};
            }}
            #reportChecklistGlyph {{
                color: {tokens["state.warn"]};
            }}
            #reportChecklistDecision {{
                color: {tokens["text.disabled"]};
                font-style: italic;
            }}
            #reportChecklistUnreviewed {{
                color: {tokens["state.warn"]};
                padding: 0 2px;
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
            #reportMissingLabel[stale="true"] {{
                color: {tokens["state.warn"]};
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
