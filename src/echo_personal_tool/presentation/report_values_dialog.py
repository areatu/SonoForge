"""Edit the report layout and choose an acquisition without editing the PDF."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.report_repeat import ReportCandidate, ReportRepeat
from echo_personal_tool.domain.services.report_document import ReportGroup


@dataclass(frozen=True)
class ReportValueEdits:
    included: frozenset[str]
    excluded: frozenset[str]
    reordered_groups: tuple[tuple[str, ...], ...]  # only groups in which a row actually moved
    choices: dict[str, str]  # only families edited in this dialog


def _candidate_text(candidate: ReportCandidate, clip_label: Callable[[str], str]) -> str:
    parts = []
    for description, source in candidate.parts:
        name = clip_label(source.sop_instance_uid) or source.sop_instance_uid or tr("report.origin.clip_unnamed")
        if source.frame_index is not None:
            name = tr("report.origin.clip_frame", name=name, frame=source.frame_index + 1)
        parts.append(f"{description} — {name}")
    return " / ".join(parts)


class ReportValuesDialog(QDialog):
    """Only keyed measurements can be edited; checklist statements are not rows to hide."""

    def __init__(
        self,
        groups: tuple[ReportGroup, ...],
        hidden: Collection[str],
        *,
        focus_key: str = "",
        clip_label: Callable[[str], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("report.values.title"))
        self.resize(640, 480)
        self._clip_label = clip_label
        self._hidden = frozenset(hidden)
        self._repeats: dict[str, ReportRepeat] = {}
        self._choices: dict[str, str] = {}
        self._tree = QTreeWidget()
        self._tree.setObjectName("reportValuesTree")
        self._tree.setAccessibleName(tr("report.values.title"))
        self._tree.setHeaderLabels([tr("report.values.parameter"), tr("report.values.value")])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        focus: QTreeWidgetItem | None = None
        for group in groups:
            rows = [value for value in group.values if value.key]
            if not rows:
                continue
            section = QTreeWidgetItem(self._tree, [group.title])
            for value in rows:
                shown = f"{value.display_value} {value.unit}".strip()
                if value.repeat:
                    self._repeats[value.key] = value.repeat
                    shown = tr("report.values.repeated", value=shown, count=len(value.repeat.candidates))
                row = QTreeWidgetItem(section, [value.label, shown])
                row.setData(0, Qt.ItemDataRole.UserRole, value.key)
                row.setCheckState(0, Qt.CheckState.Unchecked if value.key in hidden else Qt.CheckState.Checked)
                if focus is None or focus_key == value.key:
                    focus = row
        self._initial_order = self._group_keys()
        self._tree.expandAll()
        self._up = QPushButton(tr("report.values.up"))
        self._down = QPushButton(tr("report.values.down"))
        self._up.clicked.connect(lambda: self._move(-1))
        self._down.clicked.connect(lambda: self._move(1))
        move = QHBoxLayout()
        move.addWidget(self._up)
        move.addWidget(self._down)
        move.addStretch()

        self._source = QComboBox()
        self._source.setObjectName("reportMeasurementSource")
        self._source.setAccessibleName(tr("report.values.source"))
        self._source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._source.currentIndexChanged.connect(self._choose)
        form = QFormLayout()
        form.addRow(tr("report.values.source"), self._source)
        self._tree.currentItemChanged.connect(self._sync_controls)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        for role, caption in (
            (QDialogButtonBox.StandardButton.Ok, "button.ok"),
            (QDialogButtonBox.StandardButton.Cancel, "button.cancel"),
        ):
            if (button := buttons.button(role)) is not None:
                button.setText(tr(caption))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        hint = QLabel(tr("report.values.hint") if focus is not None else tr("report.values.empty"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self._tree, 1)
        layout.addLayout(move)
        layout.addLayout(form)
        layout.addWidget(buttons)
        if focus is not None:
            self._tree.setCurrentItem(focus)
        self._sync_controls()

    def _repeat(self) -> ReportRepeat | None:
        row = self._tree.currentItem()
        return self._repeats.get(row.data(0, Qt.ItemDataRole.UserRole)) if row is not None else None

    def _sync_controls(self) -> None:
        row = self._tree.currentItem()
        section = row.parent() if row is not None else None
        index = section.indexOfChild(row) if section is not None and row is not None else -1
        self._up.setEnabled(index > 0)
        self._down.setEnabled(section is not None and 0 <= index < section.childCount() - 1)
        repeat = self._repeat()
        self._source.blockSignals(True)
        self._source.clear()
        if repeat is not None:
            labels = {item.id: _candidate_text(item, self._clip_label) for item in repeat.candidates}
            self._source.addItem(tr("report.values.latest", value=labels[repeat.default_id]), "")
            for key, text in labels.items():
                self._source.addItem(text, key)
            self._source.setCurrentIndex(self._source.findData(self._choices.get(repeat.key, repeat.override)))
        self._source.blockSignals(False)
        self._source.setEnabled(repeat is not None)
        self._source.setToolTip(self._source.currentText())

    def _choose(self) -> None:
        repeat = self._repeat()
        if repeat is not None:
            self._choices[repeat.key] = str(self._source.currentData() or "")
            self._source.setToolTip(self._source.currentText())

    def _move(self, delta: int) -> None:
        row = self._tree.currentItem()
        section = row.parent() if row is not None else None
        if row is None or section is None:
            return
        index = section.indexOfChild(row)
        if 0 <= index + delta < section.childCount():
            section.takeChild(index)
            section.insertChild(index + delta, row)
            self._tree.setCurrentItem(row)

    def _groups(self) -> Iterator[list[QTreeWidgetItem]]:
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            section = root.child(i)
            assert section is not None  # bounded by childCount
            yield [row for j in range(section.childCount()) if (row := section.child(j)) is not None]

    def _group_keys(self) -> list[tuple[str, ...]]:
        return [tuple(row.data(0, Qt.ItemDataRole.UserRole) for row in rows) for rows in self._groups()]

    def edits(self) -> ReportValueEdits:
        included: set[str] = set()
        excluded: set[str] = set()
        for rows in self._groups():
            for row in rows:
                keys = included if row.checkState(0) == Qt.CheckState.Checked else excluded
                keys.add(row.data(0, Qt.ItemDataRole.UserRole))
        moved = tuple(now for before, now in zip(self._initial_order, self._group_keys()) if before != now)
        # Choosing a source or moving a row must not promote a different
        # row's tab-only quick hide into a preference for every future study.
        return ReportValueEdits(self._hidden & included, frozenset(excluded) - self._hidden, moved, dict(self._choices))
