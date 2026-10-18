"""Keyboard-first command palette for the main window (TP-6 PR-1)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from echo_personal_tool.presentation.command_catalog import (
    Command,
    command_label,
    commands_for_profile,
    match_commands,
)

_RECENTS_KEY = "command_palette/recent"
_GROUPS = {
    "open_folder": "actions",
    "load_server": "actions",
    "new_tab": "actions",
    "settings": "actions",
    "layout": "actions",
    "calculators": "calculations",
    "references": "actions",
    "help": "actions",
    "guide": "actions",
    "about": "actions",
    "quit": "actions",
    "caliper": "measurements",
    "heart_rate": "measurements",
    "calibration_bmode": "measurements",
    "calibration_doppler": "measurements",
    "spline_area": "measurements",
    "spline_volume": "measurements",
    "manual_contour": "measurements",
    "model_contour": "measurements",
    "vti_trace": "measurements",
    "doppler_interval": "measurements",
    "auto_segment": "measurements",
    "reset": "actions",
    "multiview": "actions",
    "presenter": "actions",
}


class CommandPalette(QDialog):
    """Compact searchable palette; selection resolves to a catalogue entry."""

    def __init__(self, profile: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setWindowTitle("Команды" if _language() == "ru" else "Commands")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self._profile = profile
        self._commands = {c.id: c for c in commands_for_profile(profile)}
        self._settings = QSettings()
        self._query = QLineEdit(self)
        self._query.setObjectName("commandPaletteSearch")
        self._query.setPlaceholderText("Найти команду…" if _language() == "ru" else "Search commands…")
        self._results = QListWidget(self)
        self._results.setObjectName("commandPaletteResults")
        self._results.setUniformItemSizes(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._query)
        layout.addWidget(self._results)
        self.resize(520, 420)
        self._query.textChanged.connect(self._populate)
        self._query.installEventFilter(self)
        self._results.itemActivated.connect(self._activate)
        self._query.returnPressed.connect(self._activate_current)
        self._populate("")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._query.setFocus(Qt.FocusReason.PopupFocusReason)

    @property
    def selected_command(self) -> Command | None:
        item = self._results.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001 - Qt event
        if watched is self._query and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Down:
            if self._results.count():
                self._results.setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def _populate(self, query: str) -> None:
        self._results.clear()
        if query.strip():
            commands = match_commands(query, profile=self._profile)
            groups: dict[str, list[Command]] = {}
            for command in commands:
                groups.setdefault(_GROUPS.get(command.id, "actions"), []).append(command)
            show_groups = True
        else:
            recent_ids = self._settings.value(_RECENTS_KEY, [], type=list)
            recents = [self._commands[cid] for cid in recent_ids if cid in self._commands][:5]
            if recents:
                self._header("recent")
                for command in recents:
                    self._add(command)
                groups = {}
                show_groups = False
            else:
                groups = {}
                for command in self._commands.values():
                    groups.setdefault(_GROUPS.get(command.id, "actions"), []).append(command)
                show_groups = True
        for group, items in groups.items():
            if show_groups:
                self._header(group)
            for command in items:
                self._add(command)
        for index in range(self._results.count()):
            if self._results.item(index).flags() & Qt.ItemFlag.ItemIsSelectable:
                self._results.setCurrentRow(index)
                break

    def _header(self, group: str) -> None:
        labels = {
            "recent": ("Недавние", "Recent"),
            "protocols": ("Протоколы", "Protocols"),
            "measurements": ("Измерения", "Measurements"),
            "calculations": ("Расчёты", "Calculations"),
            "actions": ("Действия", "Actions"),
        }
        label = labels.get(group, labels["actions"])[0 if _language() == "ru" else 1]
        item = QListWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self._results.addItem(item)

    def _add(self, command: Command) -> None:
        item = QListWidgetItem(command_label(command))
        item.setData(Qt.ItemDataRole.UserRole, command)
        self._results.addItem(item)

    def _activate_current(self) -> None:
        command = self.selected_command
        if command is not None:
            previous = self._settings.value(_RECENTS_KEY, [], type=list)
            recent = [command.id] + [item_id for item_id in previous if item_id != command.id][:4]
            self._settings.setValue(_RECENTS_KEY, recent)
            self.accept()

    def _activate(self, _item: QListWidgetItem) -> None:
        self._activate_current()


def _language() -> str:
    from echo_personal_tool.infrastructure.i18n import get_language

    return get_language()
