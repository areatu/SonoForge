"""Tools settings 2.0 (TP-5 PR-2): profiles × contexts, keys, import/export.

The editor renders and edits the pure model of
:mod:`echo_personal_tool.domain.tool_settings`.  It keeps the current
:class:`Layout` in memory until the preferences dialog is accepted, so a
cancelled dialog changes nothing.  Every successful edit is pushed to an undo
history; a failed JSON import leaves the model untouched.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain import tool_settings as settings
from echo_personal_tool.domain.measurement_catalog import CATALOG, SECTIONS, ToolSpec
from echo_personal_tool.domain.tool_layout_v3 import (
    CONTEXT_COMMON,
    CUSTOM_SECTION_PREFIX,
    Layout,
    Section,
    default_layout,
)
from echo_personal_tool.domain.tool_panel_view import panel_view, resolve_layout_context
from echo_personal_tool.infrastructure.i18n import get_language, tr
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

_ROLE_KIND = int(Qt.ItemDataRole.UserRole)
_ROLE_ID = _ROLE_KIND + 1

_CONTEXT_LABEL_KEYS = {
    CONTEXT_COMMON: "panel.context_common",
    "2d": "panel.context_2d",
    "m": "panel.context_m",
    "doppler": "panel.context_doppler",
}

_FILTER_KEYS = (
    ("all", "settings.filter_all"),
    ("not_on_panel", "settings.filter_not_on_panel"),
    ("hidden", "settings.filter_hidden"),
    ("ai", "settings.filter_ai"),
    ("beta", "settings.filter_beta"),
)


class _KeyCapture(QLineEdit):
    """Read-only field that turns the next key press into a Qt sequence."""

    sequence_recorded = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText(tr("settings.record_key_hint"))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        key = event.key()
        if key in (
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        ):
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.sequence_recorded.emit("")
            return
        sequence = QKeySequence(event.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText)
        if not sequence:
            text = event.text().strip()
            if text:
                sequence = text.upper()
        if sequence:
            self.sequence_recorded.emit(sequence)


class ToolSettings2Widget(QWidget):
    """Editor for profiles, contexts, panel contents and per-tool keys."""

    def __init__(self, layout_json: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        loaded = settings.import_layout(layout_json) if layout_json.strip() else default_layout()
        self._layout: Layout = loaded
        self._history = settings.UndoStack(self._layout)
        self._context = CONTEXT_COMMON
        self._selected_tool: str | None = None
        self._refreshing = False
        self._loading_props = False
        self._external = _registered_bindings()
        self._build()

    # ── Public API ─────────────────────────────────────────────────

    def encoded_layout(self) -> str:
        """The current version-3 document (the value of the new preference key)."""
        return settings.export_layout(self._layout)

    def current_layout(self) -> Layout:
        return self._layout

    def import_text(self, text: str) -> bool:
        """Replace the model from JSON; keep everything on a failed import."""
        try:
            imported = settings.import_layout(text)
        except settings.LayoutImportError as error:
            self._show_import_error(error)
            return False
        self._apply(imported)
        return True

    def export_to(self, path: str | Path) -> bool:
        try:
            Path(path).write_text(settings.export_layout(self._layout), encoding="utf-8")
        except OSError as error:
            self._status(f"{type(error).__name__}: {error}")
            return False
        self._status(tr("settings.export_done", path=str(path)))
        return True

    def assign_key(self, tool_id: str, sequence: str, *, force: bool = False) -> bool:
        """Assign a tool key; a conflict is rejected unless *force* is set."""
        try:
            updated = settings.set_tool_key(
                self._layout,
                tool_id,
                sequence,
                force=force,
                external=self._external,
            )
        except settings.KeyConflictError:
            return False
        self._apply(updated)
        return True

    def find_conflict(self, tool_id: str, sequence: str) -> settings.KeyConflict | None:
        return settings.find_key_conflict(self._layout, tool_id, sequence, external=self._external)

    def duplicate_profile(self, name: str | None = None) -> str:
        updated = settings.duplicate_profile(self._layout, name=name)
        self._apply(updated)
        return updated.active_profile

    def ensure_editable_profile(self) -> bool:
        """Make the page editable on first open by copying the built-in profile.

        Settings opens on the read-only built-in profile, so every field of the
        Tools page came up greyed until the user found «Дублировать».  The
        dialog calls this once: when the built-in profile is the only one an
        editable copy becomes active immediately (2026-10-25).  A layout that
        already has user profiles is left untouched.
        """
        if self._editable:
            return False
        if len(self._layout.profiles) != 1:
            return False
        self.duplicate_profile()
        return True

    def add_custom_section(self, title: str) -> str | None:
        try:
            updated, key = settings.add_custom_section(self._layout, self._context, title)
        except (KeyError, ValueError):
            return None
        self._apply(updated)
        return key

    def reset_context(self) -> None:
        if not self._editable:
            return
        self._apply(settings.reset_context(self._layout, self._context))

    def undo(self) -> bool:
        state = self._history.undo()
        if state is None:
            return False
        self._layout = state
        self._refresh_all()
        return True

    def redo(self) -> bool:
        state = self._history.redo()
        if state is None:
            return False
        self._layout = state
        self._refresh_all()
        return True

    # ── Build ──────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addLayout(self._build_profile_row())
        outer.addLayout(self._build_context_row())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_catalog())
        splitter.addWidget(self._build_preview())
        splitter.addWidget(self._build_properties())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        outer.addWidget(splitter, stretch=1)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        outer.addWidget(self._status_label)
        self._refresh_all()

    def _build_profile_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("settings.profile")))
        self._profile_combo = QComboBox()
        # Long profile names must not decide the width of the whole page: the
        # popup still shows them in full (2026-10-25).
        self._profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._profile_combo.setMinimumContentsLength(8)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        row.addWidget(self._profile_combo, stretch=1)
        self._duplicate_button = QPushButton(tr("settings.duplicate"))
        self._duplicate_button.clicked.connect(self._on_duplicate_profile)
        self._rename_button = QPushButton(tr("settings.rename"))
        self._rename_button.clicked.connect(self._on_rename_profile)
        self._reset_profile_button = QPushButton(tr("settings.reset_profile"))
        self._reset_profile_button.clicked.connect(self._on_reset_profile)
        for button in (self._duplicate_button, self._rename_button, self._reset_profile_button):
            row.addWidget(button)
        self._undo_button = QPushButton(tr("settings.undo"))
        self._undo_button.clicked.connect(self.undo)
        self._redo_button = QPushButton(tr("settings.redo"))
        self._redo_button.clicked.connect(self.redo)
        row.addWidget(self._undo_button)
        row.addWidget(self._redo_button)
        return row

    def _build_context_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("settings.context")))
        self._context_combo = QComboBox()
        self._context_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._context_combo.setMinimumContentsLength(8)
        for name in settings.SETTINGS_CONTEXTS:
            self._context_combo.addItem(tr(_CONTEXT_LABEL_KEYS[name]), name)
        self._context_combo.currentIndexChanged.connect(self._on_context_changed)
        row.addWidget(self._context_combo, stretch=1)
        self._import_button = QPushButton(tr("settings.import"))
        self._import_button.clicked.connect(self._on_import)
        self._export_button = QPushButton(tr("settings.export"))
        self._export_button.clicked.connect(self._on_export)
        self._reset_tab_button = QPushButton(tr("settings.reset_tab"))
        self._reset_tab_button.clicked.connect(self.reset_context)
        for button in (self._import_button, self._export_button, self._reset_tab_button):
            row.addWidget(button)
        return row

    def _build_catalog(self) -> QWidget:
        box = QGroupBox(tr("settings.catalog"))
        layout = QVBoxLayout(box)
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("settings.search_placeholder"))
        self._search.textChanged.connect(self._refresh_catalog)
        layout.addWidget(self._search)
        self._filter = QComboBox()
        for name, key in _FILTER_KEYS:
            self._filter.addItem(tr(key), name)
        self._filter.currentIndexChanged.connect(self._refresh_catalog)
        layout.addWidget(self._filter)
        self._catalog = QListWidget()
        self._catalog.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._catalog.currentItemChanged.connect(self._on_catalog_selected)
        self._catalog.itemDoubleClicked.connect(lambda _item: self._add_selected("section"))
        layout.addWidget(self._catalog, stretch=1)
        buttons = QGridLayout()
        buttons.setHorizontalSpacing(6)
        buttons.setVerticalSpacing(6)
        for index, (target, key) in enumerate(
            (
                ("quick", "settings.add_quick"),
                ("favorites", "settings.add_favorite"),
                ("section", "settings.add_section_item"),
            )
        ):
            button = QPushButton(tr(key))
            button.clicked.connect(lambda _checked=False, target=target: self._add_selected(target))
            # Two columns keep the catalog pane narrow enough for the whole
            # three-pane editor to fit the Settings window (2026-10-25).
            buttons.addWidget(button, index // 2, index % 2)
        layout.addLayout(buttons)
        return box

    def _build_preview(self) -> QWidget:
        box = QGroupBox(tr("settings.preview"))
        layout = QVBoxLayout(box)
        layout.addWidget(self._preview_title(tr("panel.quick")))
        self._quick_list = QListWidget()
        self._quick_list.currentItemChanged.connect(self._on_quick_selected)
        layout.addWidget(self._quick_list)
        layout.addWidget(self._preview_title(tr("panel.favorites")))
        self._favorites_list = QListWidget()
        self._favorites_list.currentItemChanged.connect(self._on_favorite_selected)
        layout.addWidget(self._favorites_list)
        layout.addWidget(self._preview_title(tr("settings.preview_sections")))
        self._sections = QTreeWidget()
        self._sections.setHeaderHidden(True)
        self._sections.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._sections.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self._sections.itemChanged.connect(self._on_section_item_changed)
        self._sections.currentItemChanged.connect(self._on_tree_selected)
        layout.addWidget(self._sections, stretch=1)
        row = QGridLayout()
        row.setHorizontalSpacing(6)
        row.setVerticalSpacing(6)
        for index, (key, slot) in enumerate(
            (
                ("settings.remove", self._remove_selected),
                ("tools.section_move_up", lambda: self._move_section(-1)),
                ("tools.section_move_down", lambda: self._move_section(1)),
                ("tools.add_section", self._on_add_section),
                ("tools.section_rename", self._on_rename_section),
                ("tools.section_delete", self._on_delete_section),
            )
        ):
            button = QPushButton(tr(key))
            button.clicked.connect(slot)
            # Two columns: six buttons on one line needed ~560 px of minimum
            # width and pushed the pane out of the Settings window.
            row.addWidget(button, index // 2, index % 2)
        layout.addLayout(row)
        return box

    def _build_properties(self) -> QWidget:
        box = QGroupBox(tr("settings.properties"))
        layout = QVBoxLayout(box)
        self._tool_title = QLabel(tr("settings.no_tool_selected"))
        self._tool_title.setWordWrap(True)
        layout.addWidget(self._tool_title)
        form = QFormLayout()
        self._catalog_ru = QLabel("")
        self._catalog_en = QLabel("")
        self._label_ru = QLineEdit()
        self._label_en = QLineEdit()
        self._label_ru.editingFinished.connect(self._on_labels_changed)
        self._label_en.editingFinished.connect(self._on_labels_changed)
        form.addRow(tr("settings.labels_ru"), self._catalog_ru)
        form.addRow(tr("settings.custom_ru"), self._label_ru)
        form.addRow(tr("settings.labels_en"), self._catalog_en)
        form.addRow(tr("settings.custom_en"), self._label_en)
        key_row = QHBoxLayout()
        self._key_edit = _KeyCapture()
        self._key_edit.sequence_recorded.connect(self._on_key_recorded)
        self._key_clear = QPushButton(tr("settings.clear"))
        self._key_clear.clicked.connect(lambda: self._on_key_recorded(""))
        key_row.addWidget(self._key_edit, stretch=1)
        key_row.addWidget(self._key_clear)
        form.addRow(tr("settings.shortcut"), key_row)
        self._conflict_label = QLabel("")
        self._conflict_label.setWordWrap(True)
        form.addRow("", self._conflict_label)
        self._after_combo = QComboBox()
        self._after_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._after_combo.setMinimumContentsLength(8)
        self._after_combo.addItem(tr("settings.after_return"), settings.AFTER_RETURN)
        self._after_combo.addItem(tr("settings.after_stay"), settings.AFTER_STAY)
        self._after_combo.currentIndexChanged.connect(self._on_after_changed)
        form.addRow(tr("settings.after"), self._after_combo)
        self._show_panel = QCheckBox(tr("settings.show_panel"))
        self._show_quick = QCheckBox(tr("settings.show_quick"))
        self._show_radial = QCheckBox(tr("settings.show_radial"))
        self._show_palette = QCheckBox(tr("settings.show_palette"))
        for check in (self._show_panel, self._show_quick, self._show_radial, self._show_palette):
            check.stateChanged.connect(self._on_show_in_changed)
        form.addRow(tr("settings.show_in"), self._show_panel)
        form.addRow("", self._show_quick)
        form.addRow("", self._show_radial)
        form.addRow("", self._show_palette)
        self._hint_edit = QLineEdit()
        self._hint_edit.editingFinished.connect(self._on_hint_changed)
        form.addRow(tr("settings.hint"), self._hint_edit)
        layout.addLayout(form)
        layout.addStretch(1)
        return box

    @staticmethod
    def _preview_title(text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    # ── State helpers ──────────────────────────────────────────────

    @property
    def _profile(self):
        return self._layout.profile()

    @property
    def _editable(self) -> bool:
        profile = self._profile
        return profile is not None and not settings.is_builtin_profile(profile)

    def _apply(self, layout: Layout) -> None:
        if layout == self._layout:
            return
        self._layout = layout
        self._history.push(layout)
        self._refresh_all()

    def _status(self, text: str) -> None:
        if hasattr(self, "_status_label"):
            self._status_label.setText(text)

    def _refresh_all(self) -> None:
        self._refreshing = True
        try:
            self._refresh_profiles()
            self._refresh_edit_enabled()
            self._refresh_context()
            self._undo_button.setEnabled(self._history.can_undo)
            self._redo_button.setEnabled(self._history.can_redo)
            if not self._editable:
                self._status(tr("settings.read_only"))
            elif self._status_label.text() == tr("settings.read_only"):
                self._status("")
        finally:
            self._refreshing = False

    def _refresh_profiles(self) -> None:
        self._profile_combo.blockSignals(True)
        try:
            self._profile_combo.clear()
            for profile in self._layout.profiles:
                self._profile_combo.addItem(profile.name, profile.id)
            index = self._profile_combo.findData(self._layout.active_profile)
            self._profile_combo.setCurrentIndex(max(0, index))
        finally:
            self._profile_combo.blockSignals(False)

    def _refresh_edit_enabled(self) -> None:
        editable = self._editable
        for widget in (
            self._search,
            self._filter,
            self._catalog,
            self._quick_list,
            self._favorites_list,
            self._sections,
            self._reset_tab_button,
            self._rename_button,
            self._reset_profile_button,
        ):
            widget.setEnabled(editable)
        self._duplicate_button.setEnabled(True)
        self._rename_button.setEnabled(editable)
        self._reset_profile_button.setEnabled(editable)
        self._import_button.setEnabled(True)
        self._export_button.setEnabled(True)

    def _refresh_context(self) -> None:
        index = self._context_combo.findData(self._context)
        if index >= 0 and self._context_combo.currentIndex() != index:
            self._context_combo.blockSignals(True)
            self._context_combo.setCurrentIndex(index)
            self._context_combo.blockSignals(False)
        self._refresh_catalog()
        self._refresh_preview()
        self._show_properties(self._selected_tool)

    def _resolved_sections(self) -> tuple[Section, ...]:
        context = resolve_layout_context(self._layout, self._context)
        return context.sections if context is not None else ()

    def _refresh_preview(self) -> None:
        self._refreshing = True
        try:
            view = panel_view(self._layout, self._context, language=get_language())
            self._fill_tool_list(self._quick_list, [tool.id for tool in view.quick[: settings.MAX_QUICK]])
            self._fill_tool_list(self._favorites_list, [tool.id for tool in view.favorites])
            self._sections.clear()
            for block in self._resolved_sections():
                section_item = QTreeWidgetItem([self._section_title(block)])
                section_item.setData(0, _ROLE_KIND, "section")
                section_item.setData(0, _ROLE_ID, block.key)
                section_item.setFlags(section_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                section_item.setCheckState(0, Qt.CheckState.Checked if block.visible else Qt.CheckState.Unchecked)
                self._sections.addTopLevelItem(section_item)
                for item in block.items:
                    tool = CATALOG.get(item.id)
                    if tool is None:
                        continue
                    child = QTreeWidgetItem([self._tool_title_text(tool)])
                    child.setData(0, _ROLE_KIND, "tool")
                    child.setData(0, _ROLE_ID, item.id)
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.CheckState.Checked if item.visible else Qt.CheckState.Unchecked)
                    section_item.addChild(child)
        finally:
            self._refreshing = False

    @staticmethod
    def _fill_tool_list(widget: QListWidget, ids: Iterable[str]) -> None:
        widget.clear()
        for tool_id in ids:
            tool = CATALOG.get(tool_id)
            if tool is None:
                continue
            item = QListWidgetItem(ToolSettings2Widget._tool_title_text(tool))
            item.setData(_ROLE_ID, tool_id)
            item.setToolTip(tool.label(get_language()).full)
            widget.addItem(item)

    def _refresh_catalog(self, *_args: object) -> None:
        if not hasattr(self, "_catalog"):
            return
        query = self._search.text().strip().casefold()
        mode = str(self._filter.currentData())
        context = resolve_layout_context(self._layout, self._context)
        placed = {
            item.id: item.visible for block in (context.sections if context is not None else ()) for item in block.items
        }
        self._catalog.clear()
        for tool in sorted(CATALOG.values(), key=lambda value: value.label(get_language()).short):
            if query and not _matches(tool, query):
                continue
            if mode == "not_on_panel" and tool.id in placed:
                continue
            if mode == "hidden" and placed.get(tool.id, True):
                continue
            if mode == "ai" and "ai" not in tool.flags:
                continue
            if mode == "beta" and "experimental" not in tool.flags:
                continue
            item = QListWidgetItem(self._tool_title_text(tool))
            item.setData(_ROLE_ID, tool.id)
            item.setToolTip(tool.label(get_language()).full)
            if tool.id not in placed:
                item.setForeground(Qt.GlobalColor.gray)
            self._catalog.addItem(item)

    def _section_title(self, block: Section) -> str:
        spec = SECTIONS.get(block.key)
        if spec is not None:
            return spec.label(get_language()).short
        if block.key.startswith(CUSTOM_SECTION_PREFIX):
            return block.title or tr("settings.custom_section")
        return block.title or block.key

    @staticmethod
    def _tool_title_text(tool: ToolSpec) -> str:
        label = tool.label(get_language())
        return label.short or label.full

    # ── Selection ──────────────────────────────────────────────────

    def _on_catalog_selected(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        self._show_properties(str(current.data(_ROLE_ID)))

    def _on_quick_selected(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is not None:
            self._show_properties(str(current.data(_ROLE_ID)))

    def _on_favorite_selected(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is not None:
            self._show_properties(str(current.data(_ROLE_ID)))

    def _on_tree_selected(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        if current.data(0, _ROLE_KIND) == "tool":
            self._show_properties(str(current.data(0, _ROLE_ID)))

    def _show_properties(self, tool_id: str | None) -> None:
        tool = CATALOG.get(tool_id) if tool_id else None
        self._loading_props = True
        try:
            self._selected_tool = tool.id if tool is not None else None
            if tool is None:
                self._tool_title.setText(tr("settings.no_tool_selected"))
                for widget in (
                    self._label_ru,
                    self._label_en,
                    self._key_edit,
                    self._hint_edit,
                ):
                    widget.clear()
                self._catalog_ru.clear()
                self._catalog_en.clear()
                self._conflict_label.clear()
                self._set_props_enabled(False)
                return
            props = settings.tool_props(self._layout, tool.id)
            label = tool.label(get_language())
            self._tool_title.setText(tool.id)
            self._catalog_ru.setText(tool.labels.get("ru", label).full)
            self._catalog_en.setText(tool.labels.get("en", label).full)
            self._label_ru.setText(props.label_ru or "")
            self._label_en.setText(props.label_en or "")
            self._key_edit.setText(props.key or "")
            self._hint_edit.setText(props.hint or "")
            self._after_combo.setCurrentIndex(max(0, self._after_combo.findData(props.after or settings.AFTER_RETURN)))
            shown = set(props.show_in or settings.SHOW_IN_OPTIONS)
            for name, check in (
                ("panel", self._show_panel),
                ("quick", self._show_quick),
                ("radial", self._show_radial),
                ("palette", self._show_palette),
            ):
                check.setChecked(name in shown)
            self._update_conflict_label(tool.id, props.key)
            self._set_props_enabled(self._editable)
        finally:
            self._loading_props = False

    def _set_props_enabled(self, enabled: bool) -> None:
        for widget in (
            self._label_ru,
            self._label_en,
            self._key_edit,
            self._key_clear,
            self._after_combo,
            self._show_panel,
            self._show_quick,
            self._show_radial,
            self._show_palette,
            self._hint_edit,
        ):
            widget.setEnabled(enabled)

    def _update_conflict_label(self, tool_id: str, sequence: str | None) -> None:
        if not sequence:
            self._conflict_label.clear()
            return
        conflict = self.find_conflict(tool_id, sequence)
        if conflict is None:
            self._conflict_label.clear()
            self._conflict_label.setStyleSheet("")
            return
        self._conflict_label.setText(tr("settings.shortcut_conflict_text", key=sequence, owner=conflict.owner_label))
        self._conflict_label.setStyleSheet(f"color: {get_theme_tokens()['state.err']};")

    # ── Edits ──────────────────────────────────────────────────────

    def _on_profile_changed(self) -> None:
        if self._refreshing:
            return
        profile_id = str(self._profile_combo.currentData())
        if not profile_id:
            return
        self._apply(settings.use_profile(self._layout, profile_id))

    def _on_duplicate_profile(self) -> None:
        self.duplicate_profile()

    def _on_rename_profile(self) -> None:
        if not self._editable:
            return
        name, accepted = QInputDialog.getText(
            self, tr("settings.rename"), tr("settings.profile_name"), text=self._profile.name
        )
        if not accepted or not name.strip():
            return
        try:
            self._apply(settings.rename_profile(self._layout, name))
        except (KeyError, ValueError) as error:
            self._status(str(error))

    def _on_reset_profile(self) -> None:
        if not self._editable:
            return
        self._apply(settings.reset_profile(self._layout))

    def _on_context_changed(self) -> None:
        self._context = str(self._context_combo.currentData())
        self._selected_tool = None
        self._refresh_all()

    def _on_section_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._refreshing or column != 0 or not self._editable:
            return
        kind = item.data(0, _ROLE_KIND)
        identifier = str(item.data(0, _ROLE_ID))
        visible = item.checkState(0) == Qt.CheckState.Checked
        try:
            if kind == "section":
                updated = settings.set_section_visible(self._layout, self._context, identifier, visible)
            elif kind == "tool":
                updated = settings.set_tool_visible(self._layout, self._context, identifier, visible)
            else:
                return
        except (KeyError, ValueError):
            self._refresh_preview()
            return
        self._apply(updated)

    def _selected_section_key(self) -> str | None:
        current = self._sections.currentItem()
        if current is None:
            return None
        if current.data(0, _ROLE_KIND) == "section":
            return str(current.data(0, _ROLE_ID))
        parent = current.parent()
        return str(parent.data(0, _ROLE_ID)) if parent is not None else None

    def _add_selected(self, target: str) -> None:
        if not self._editable:
            return
        current = self._catalog.currentItem()
        if current is None:
            return
        tool_id = str(current.data(_ROLE_ID))
        try:
            if target == "quick":
                current_quick = self._current_ids(self._quick_list)
                updated = settings.set_context_quick(self._layout, self._context, (*current_quick, tool_id))
            elif target == "favorites":
                current_favorites = self._current_ids(self._favorites_list)
                updated = settings.set_context_favorites(self._layout, self._context, (*current_favorites, tool_id))
            else:
                updated = settings.add_tool(
                    self._layout,
                    self._context,
                    tool_id,
                    section_key=self._selected_section_key(),
                )
        except (KeyError, ValueError) as error:
            self._status(str(error))
            return
        self._apply(updated)

    @staticmethod
    def _current_ids(widget: QListWidget) -> tuple[str, ...]:
        return tuple(str(widget.item(index).data(_ROLE_ID)) for index in range(widget.count()))

    def _remove_selected(self) -> None:
        if not self._editable:
            return
        if self._sections.hasFocus() or self._sections.currentItem() is not None:
            item = self._sections.currentItem()
            if item is not None and item.data(0, _ROLE_KIND) == "tool":
                self._apply(settings.set_tool_visible(self._layout, self._context, str(item.data(0, _ROLE_ID)), False))
                return
        for widget, setter in (
            (self._quick_list, settings.set_context_quick),
            (self._favorites_list, settings.set_context_favorites),
        ):
            current = widget.currentItem()
            if current is not None:
                remaining = tuple(tool_id for tool_id in self._current_ids(widget) if tool_id != current.data(_ROLE_ID))
                self._apply(setter(self._layout, self._context, remaining))
                return

    def _move_section(self, delta: int) -> None:
        if not self._editable:
            return
        key = self._selected_section_key()
        if key is None:
            return
        try:
            self._apply(settings.move_section(self._layout, self._context, key, delta))
        except (KeyError, ValueError):
            return

    def _on_add_section(self) -> None:
        if not self._editable:
            return
        title, accepted = QInputDialog.getText(
            self,
            tr("tools.add_section_title"),
            tr("tools.section_name_prompt", max=40),
        )
        if accepted and title.strip():
            self.add_custom_section(title)

    def _on_rename_section(self) -> None:
        if not self._editable:
            return
        key = self._selected_section_key()
        if key is None or not key.startswith(CUSTOM_SECTION_PREFIX):
            return
        title, accepted = QInputDialog.getText(self, tr("tools.section_rename_title"), tr("tools.section_rename"))
        if not accepted:
            return
        try:
            self._apply(settings.rename_section(self._layout, self._context, key, title))
        except (KeyError, ValueError) as error:
            self._status(str(error))

    def _on_delete_section(self) -> None:
        if not self._editable:
            return
        key = self._selected_section_key()
        if key is None or not key.startswith(CUSTOM_SECTION_PREFIX):
            return
        try:
            self._apply(settings.delete_section(self._layout, self._context, key))
        except (KeyError, ValueError) as error:
            self._status(str(error))

    def _on_labels_changed(self) -> None:
        if self._loading_props or not self._editable or self._selected_tool is None:
            return
        self._apply(
            settings.set_tool_labels(
                self._layout,
                self._selected_tool,
                label_ru=self._label_ru.text(),
                label_en=self._label_en.text(),
            )
        )

    def _on_hint_changed(self) -> None:
        if self._loading_props or not self._editable or self._selected_tool is None:
            return
        self._apply(settings.set_tool_hint(self._layout, self._selected_tool, self._hint_edit.text()))

    def _on_after_changed(self) -> None:
        if self._loading_props or not self._editable or self._selected_tool is None:
            return
        self._apply(settings.set_tool_after(self._layout, self._selected_tool, str(self._after_combo.currentData())))

    def _on_show_in_changed(self) -> None:
        if self._loading_props or not self._editable or self._selected_tool is None:
            return
        selected = []
        for name, check in (
            ("panel", self._show_panel),
            ("quick", self._show_quick),
            ("radial", self._show_radial),
            ("palette", self._show_palette),
        ):
            if check.isChecked():
                selected.append(name)
        self._apply(settings.set_tool_show_in(self._layout, self._selected_tool, selected))

    def _on_key_recorded(self, sequence: str) -> None:
        if not self._editable or self._selected_tool is None:
            return
        tool_id = self._selected_tool
        conflict = self.find_conflict(tool_id, sequence)
        if conflict is not None and not self._confirm_conflict(conflict, sequence):
            self._key_edit.setText(settings.tool_props(self._layout, tool_id).key or "")
            return
        self.assign_key(tool_id, sequence, force=conflict is not None)

    def _confirm_conflict(self, conflict: settings.KeyConflict, sequence: str) -> bool:
        """«Оставить» / «Назначить» — the only way to save a conflict."""
        box = QMessageBox(self)
        box.setWindowTitle(tr("settings.shortcut_conflict"))
        box.setText(tr("settings.shortcut_conflict_text", key=sequence, owner=conflict.owner_label))
        keep = box.addButton(tr("settings.shortcut_conflict_keep"), QMessageBox.ButtonRole.RejectRole)
        assign = box.addButton(tr("settings.shortcut_conflict_assign"), QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(keep)
        box.exec()
        return box.clickedButton() is assign

    # ── Import / export ────────────────────────────────────────────

    def _on_export(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self, tr("settings.export"), "sonoforge-tools.json", "JSON (*.json)"
        )
        if path:
            self.export_to(path)

    def _on_import(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(self, tr("settings.import"), "", "JSON (*.json)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            self._status(f"{type(error).__name__}: {error}")
            return
        self.import_text(text)

    def _show_import_error(self, error: settings.LayoutImportError) -> None:
        detail = tr(f"settings.import_error.{error.reason}")
        if detail == f"settings.import_error.{error.reason}":
            detail = tr("settings.import_error.generic")
        if error.detail:
            detail = f"{detail} ({error.detail})"
        QMessageBox.warning(self, tr("settings.import_error_title"), detail)
        self._status(detail)


def _registered_bindings() -> tuple[settings.KeyBinding, ...]:
    from echo_personal_tool.keyboard_shortcuts import main_window_shortcuts, shortcut_label

    bindings: list[settings.KeyBinding] = []
    for spec in main_window_shortcuts():
        for sequence in spec.sequences:
            bindings.append(
                settings.KeyBinding(
                    owner=spec.id,
                    label=shortcut_label(spec.id),
                    sequence=sequence,
                )
            )
    return tuple(bindings)


def _matches(tool: ToolSpec, query: str) -> bool:
    fields = [tool.id]
    for language in ("ru", "en"):
        label = tool.labels.get(language)
        if label is not None:
            fields.extend((label.short, label.full))
    fields.extend(tool.synonyms)
    return any(query in field.casefold() for field in fields if field)
