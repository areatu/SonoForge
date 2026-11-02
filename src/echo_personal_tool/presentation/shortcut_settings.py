"""Editable application bindings, backed by the same registry as handlers and Help."""

from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.profile_settings import active_profile_name
from echo_personal_tool.domain.translation import tr
from echo_personal_tool.keyboard_shortcuts import SHORTCUTS, decode_shortcut_overrides, shortcut_conflicts
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

_PORTABLE = QKeySequence.SequenceFormat.PortableText


class ShortcutSettingsWidget(QWidget):
    """Edits are local until Done; aliases and disabled bindings round-trip intact."""

    changed = Signal()

    def __init__(self, encoded: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("shortcutSettings")
        self._original = decode_shortcut_overrides(encoded)
        profile = active_profile_name()
        self._profile = profile
        self._specs = [
            spec for spec in SHORTCUTS if spec.kind == "keyboard" and (not spec.profiles or profile in spec.profiles)
        ]
        self._editors: dict[str, list[QKeySequenceEdit]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("shortcuts.settings.search"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter_rows)
        layout.addWidget(self._search)
        hint = QLabel(tr("shortcuts.settings.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._table = QTableWidget(len(self._specs), 3)
        self._table.setObjectName("shortcutTable")
        self._table.setHorizontalHeaderLabels(
            [tr("shortcuts.help.action_column"), tr("shortcuts.help.key_column"), tr("shortcuts.settings.reset_column")]
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.verticalHeader().hide()
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 64)
        for row, spec in enumerate(self._specs):
            self._add_row(row, spec)
        self._table.setMinimumHeight(240)
        layout.addWidget(self._table, 1)
        self._error = QLabel()
        self._error.setObjectName("shortcutConflict")
        self._error.setWordWrap(True)
        self._error.setStyleSheet(f"color: {get_theme_tokens()['state.err']};")
        layout.addWidget(self._error)
        self._update_validation()

    def _add_row(self, row, spec) -> None:
        item = QTableWidgetItem(tr(spec.description_key))
        item.setToolTip(f"{tr(spec.description_key)}\n{tr(spec.group_key)} · {spec.context}")
        self._table.setItem(row, 0, item)
        host = QWidget(self._table)
        keys = QHBoxLayout(host)
        keys.setContentsMargins(2, 2, 2, 2)
        keys.setSpacing(4)
        sequences = self._original.get(spec.id, spec.sequences)
        editors = []
        for index in range(max(2, len(sequences), len(spec.sequences))):
            editor = QKeySequenceEdit(QKeySequence(sequences[index] if index < len(sequences) else ""), host)
            editor.setMaximumSequenceLength(1)
            editor.setFinishingKeyCombinations([])
            editor.setClearButtonEnabled(True)
            line = editor.findChild(QLineEdit)
            if line is not None:
                line.setPlaceholderText(tr("shortcuts.settings.capture"))
            editor.setMinimumWidth(0)
            editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            editor.setAccessibleName(f"{tr(spec.description_key)} · {index + 1}")
            editor.keySequenceChanged.connect(self._on_changed)
            keys.addWidget(editor, 1)
            editors.append(editor)
        self._editors[spec.id] = editors
        self._table.setCellWidget(row, 1, host)
        reset = QPushButton("↺")
        reset.setToolTip(tr("shortcuts.settings.reset"))
        reset.setAccessibleName(f"{tr('shortcuts.settings.reset')}: {tr(spec.description_key)}")
        reset.clicked.connect(lambda _checked=False, shortcut_id=spec.id: self.reset_binding(shortcut_id))
        self._table.setCellWidget(row, 2, reset)
        self._table.setRowHeight(row, max(40, host.sizeHint().height() + 4))

    def reset_binding(self, shortcut_id: str) -> None:
        spec = next(spec for spec in self._specs if spec.id == shortcut_id)
        for index, editor in enumerate(self._editors[shortcut_id]):
            editor.setKeySequence(QKeySequence(spec.sequences[index] if index < len(spec.sequences) else ""))
        self._on_changed()

    def overrides(self) -> dict[str, tuple[str, ...]]:
        result = dict(self._original)
        for spec in self._specs:
            keys = tuple(
                dict.fromkeys(
                    editor.keySequence().toString(_PORTABLE)
                    for editor in self._editors[spec.id]
                    if not editor.keySequence().isEmpty()
                )
            )
            defaults = tuple(QKeySequence(key).toString(_PORTABLE) for key in spec.sequences)
            if keys == defaults:
                result.pop(spec.id, None)
            else:
                result[spec.id] = keys
        return result

    def encoded_overrides(self) -> str:
        return json.dumps(self.overrides(), ensure_ascii=False, sort_keys=True)

    def validation_error(self) -> str:
        conflicts = shortcut_conflicts(self._profile, overrides=self.overrides())
        if not conflicts:
            return ""
        _context, key, first, second = conflicts[0]
        descriptions = {spec.id: tr(spec.description_key) for spec in SHORTCUTS}
        return tr("shortcuts.settings.conflict", binding=key, first=descriptions[first], second=descriptions[second])

    def _update_validation(self) -> None:
        self._error.setText(self.validation_error())

    def _on_changed(self, *_args) -> None:
        # Qt may deliver a polish signal before all rows have been built.
        if hasattr(self, "_error"):
            self._update_validation()
            self.changed.emit()

    def _filter_rows(self, text: str) -> None:
        query = text.strip().casefold()
        for row, spec in enumerate(self._specs):
            haystack = f"{tr(spec.description_key)} {tr(spec.group_key)} {spec.context}".casefold()
            self._table.setRowHidden(row, query not in haystack)
