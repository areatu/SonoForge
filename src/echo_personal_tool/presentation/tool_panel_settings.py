"""Tools tab: customize the Measures tool panel per section.

Each group box mirrors a toolbar section; every tool is a checkable item and
items can be dragged between sections.  Sections are reordered with ↑/↓ and
users can add, rename and delete their own sections.  Sections flow into two
independent columns (masonry style, balanced by row count) so a tall section
never leaves an empty gap under its shorter neighbour.  The resulting layout
is serialized as JSON and persisted through
``UserPreferences.tool_panel_layout_json``.
"""

from __future__ import annotations

import uuid

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.measures_menu import (
    CUSTOM_SECTION_PREFIX,
    MAX_CUSTOM_SECTION_TITLE,
    MAX_CUSTOM_SECTIONS,
    _MenuButton,
    _mnemonic_safe,
    decode_tool_layout,
    encode_tool_layout,
    is_custom_section_key,
    normalize_tool_layout,
    tool_menu_catalog,
)

_TOOL_MIME = "application/x-sonoforge-tool"


class _ToolListWidget(QListWidget):
    """Checkable tool list that accepts items dropped from sibling sections."""

    rows_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDropIndicatorShown(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    # ── drag & drop ─────────────────────────────────────────────────

    def mimeTypes(self) -> list[str]:  # noqa: N802 - Qt override
        return [_TOOL_MIME]

    def mimeData(self, items) -> QMimeData:  # noqa: N802 - Qt override
        data = QMimeData()
        ids = [str(item.data(Qt.ItemDataRole.UserRole)) for item in items if item is not None]
        data.setData(_TOOL_MIME, "\n".join(ids).encode("utf-8"))
        return data

    def startDrag(self, supported_actions) -> None:  # noqa: N802 - Qt override
        item = self.currentItem()
        if item is None:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData([item]))
        # Removal is done by the drop target; keep Qt from re-running its own
        # internal move bookkeeping on the source.
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasFormat(_TOOL_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasFormat(_TOOL_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not event.mimeData().hasFormat(_TOOL_MIME):
            super().dropEvent(event)
            self.rows_changed.emit()
            return
        source = event.source()
        if not isinstance(source, _ToolListWidget):
            event.ignore()
            return
        tool_id = bytes(event.mimeData().data(_TOOL_MIME)).decode("utf-8")
        target_row = self.indexAt(event.position().toPoint()).row()
        if self._relocate(source, self, tool_id, target_row):
            event.acceptProposedAction()
            self.rows_changed.emit()
            if source is not self:
                source.rows_changed.emit()
        else:
            event.ignore()

    @staticmethod
    def _relocate(source: QListWidget, target: QListWidget, tool_id: str, target_row: int) -> bool:
        src_row = -1
        for index in range(source.count()):
            if str(source.item(index).data(Qt.ItemDataRole.UserRole)) == tool_id:
                src_row = index
                break
        if src_row < 0:
            return False
        item = source.takeItem(src_row)
        if item is None:
            return False
        if target_row < 0 or target_row > target.count():
            target.addItem(item)
        else:
            if source is target and target_row > src_row:
                target_row -= 1
            target.insertItem(target_row, item)
        target.setCurrentItem(item)
        return True


class ToolPanelSettingsWidget(QWidget):
    """Editor for the tool panel's sections, their order, tools and visibility.

    Sections are ordered explicitly with the ↑/↓ buttons in each header.  User
    sections can be added (up to ``MAX_CUSTOM_SECTIONS``), renamed and deleted;
    deleting one returns its tools to their default sections.
    """

    def __init__(self, layout_json: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = tool_menu_catalog()
        self._spec_by_id = {spec.tool_id: spec for _key, buttons in self._catalog for spec in buttons}
        self._default_section_of = {spec.tool_id: key for key, buttons in self._catalog for spec in buttons}
        self._order: list[str] = []
        self._lists: dict[str, _ToolListWidget] = {}
        self._section_boxes: dict[str, QGroupBox] = {}
        self._move_buttons: dict[str, tuple[QPushButton, QPushButton]] = {}
        self._titles: dict[str, str] = {}
        self._build(layout_json)

    def _build(self, layout_json: str) -> None:
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(4, 8, 4, 8)
        host_layout.setSpacing(8)

        hint = QLabel(tr("preferences.tools_hint"))
        hint.setWordWrap(True)
        host_layout.addWidget(hint)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        self._add_button = QPushButton(tr("tools.add_section"))
        self._add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_button.clicked.connect(self._on_add_section)
        toolbar.addWidget(self._add_button)
        toolbar.addStretch(1)
        host_layout.addLayout(toolbar)

        grid_host = QWidget()
        columns_row = QHBoxLayout(grid_host)
        columns_row.setContentsMargins(0, 0, 0, 0)
        columns_row.setSpacing(8)
        self._columns: list[QVBoxLayout] = []
        for _ in range(2):
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(8)
            columns_row.addLayout(column, stretch=1)
            self._columns.append(column)
        host_layout.addWidget(grid_host)
        host_layout.addStretch(1)

        for section in normalize_tool_layout(self._catalog, decode_tool_layout(layout_json)):
            self._create_section(
                str(section["key"]),
                section["title"] if isinstance(section["title"], str) else None,
                section["items"],  # type: ignore[arg-type]
            )
        self._rebuild_columns()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._refresh_controls()

    def _create_section(self, key: str, title: str | None, items: list[dict[str, object]]) -> None:
        """Create one section (box, header, tool list) and append it to the order."""
        custom = is_custom_section_key(key)
        label = title if custom and title is not None else tr(key)
        box = QGroupBox(_mnemonic_safe(label))
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        header.addStretch(1)
        up = QPushButton("↑")
        up.setToolTip(tr("tools.section_move_up"))
        up.clicked.connect(lambda _checked=False, k=key: self._move_section(k, -1))
        down = QPushButton("↓")
        down.setToolTip(tr("tools.section_move_down"))
        down.clicked.connect(lambda _checked=False, k=key: self._move_section(k, 1))
        for button in (up, down):
            button.setMinimumWidth(28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            header.addWidget(button)
        self._move_buttons[key] = (up, down)
        if custom:
            rename = QPushButton(tr("tools.section_rename"))
            rename.clicked.connect(lambda _checked=False, k=key: self._on_rename_section(k))
            delete = QPushButton(tr("tools.section_delete"))
            delete.setToolTip(tr("tools.section_delete_tip"))
            delete.clicked.connect(lambda _checked=False, k=key: self._on_delete_section(k))
            header.addWidget(rename)
            header.addWidget(delete)
            self._titles[key] = label
        box_layout.addLayout(header)

        tool_list = _ToolListWidget(box)
        for item in items:
            spec = self._spec_by_id.get(str(item.get("id")))
            if spec is not None:
                tool_list.addItem(self._make_item(spec, bool(item.get("enabled", True))))
        tool_list.rows_changed.connect(self._reflow)
        box_layout.addWidget(tool_list)

        self._lists[key] = tool_list
        self._section_boxes[key] = box
        self._order.append(key)

    def _rebuild_columns(self) -> None:
        """Place the boxes in display order, balancing the two columns by row count."""
        for column in self._columns:
            while column.count():
                column.takeAt(0)
        column_rows = [0, 0]
        for key in self._order:
            rows = max(1, self._lists[key].count())
            column = 0 if column_rows[0] <= column_rows[1] else 1
            column_rows[column] += rows
            self._columns[column].addWidget(self._section_boxes[key], alignment=Qt.AlignmentFlag.AlignTop)
        for column in self._columns:
            column.addStretch(1)
        self._reflow()

    def _refresh_controls(self) -> None:
        """Enable/disable move buttons at the ends and the add button at the limit."""
        last = len(self._order) - 1
        for index, key in enumerate(self._order):
            up, down = self._move_buttons[key]
            up.setEnabled(index > 0)
            down.setEnabled(index < last)
        at_limit = self._custom_section_count() >= MAX_CUSTOM_SECTIONS
        self._add_button.setEnabled(not at_limit)
        self._add_button.setToolTip(tr("tools.section_limit", max=MAX_CUSTOM_SECTIONS) if at_limit else "")

    def _custom_section_count(self) -> int:
        return sum(1 for key in self._order if is_custom_section_key(key))

    def _move_section(self, key: str, delta: int) -> None:
        index = self._order.index(key)
        target = index + delta
        if not 0 <= target < len(self._order):
            return
        self._order[index], self._order[target] = self._order[target], self._order[index]
        self._rebuild_columns()
        self._refresh_controls()

    def _prompt_title(self, dialog_title: str, current: str) -> str | None:
        """Ask for a section name; ``None`` when cancelled or left blank."""
        text, accepted = QInputDialog.getText(
            self,
            dialog_title,
            tr("tools.section_name_prompt", max=MAX_CUSTOM_SECTION_TITLE),
            text=current,
        )
        if not accepted:
            return None
        return text.strip()[:MAX_CUSTOM_SECTION_TITLE] or None

    def _on_add_section(self) -> None:
        if self._custom_section_count() >= MAX_CUSTOM_SECTIONS:
            return
        title = self._prompt_title(tr("tools.add_section_title"), "")
        if title is None:
            return
        key = f"{CUSTOM_SECTION_PREFIX}{uuid.uuid4().hex[:8]}"
        self._create_section(key, title, [])
        self._rebuild_columns()
        self._refresh_controls()

    def _on_rename_section(self, key: str) -> None:
        if not is_custom_section_key(key):
            return
        title = self._prompt_title(tr("tools.section_rename_title"), self._titles.get(key, ""))
        if title is None:
            return
        self._titles[key] = title
        self._section_boxes[key].setTitle(_mnemonic_safe(title))

    def _on_delete_section(self, key: str) -> None:
        """Remove a user section; its tools go back to their default sections."""
        if not is_custom_section_key(key):
            return
        tool_list = self._lists.pop(key)
        while tool_list.count():
            item = tool_list.takeItem(0)
            tool_id = str(item.data(Qt.ItemDataRole.UserRole))
            self._lists[self._default_section_of[tool_id]].addItem(item)

        box = self._section_boxes.pop(key)
        self._move_buttons.pop(key, None)
        self._titles.pop(key, None)
        self._order.remove(key)
        box.hide()
        box.deleteLater()
        self._rebuild_columns()
        self._refresh_controls()

    @staticmethod
    def _make_item(spec: _MenuButton, enabled: bool) -> QListWidgetItem:
        item = QListWidgetItem(spec.label)
        item.setData(Qt.ItemDataRole.UserRole, spec.tool_id)
        item.setFlags(
            item.flags()
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        return item

    def _reflow(self) -> None:
        """Grow each section to fit its rows (no inner scrolling)."""
        for tool_list in self._lists.values():
            rows = max(1, tool_list.count())
            row_h = tool_list.sizeHintForRow(0)
            if row_h <= 0:
                row_h = tool_list.fontMetrics().height() + 6
            height = row_h * rows + 4
            if tool_list.height() != height:
                tool_list.setFixedHeight(height)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._reflow()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._reflow()

    def encoded_layout(self) -> str:
        """Serialize the current arrangement (section order, titles, tools, visibility)."""
        sections: list[dict[str, object]] = []
        for key in self._order:
            tool_list = self._lists[key]
            items: list[dict[str, object]] = []
            for index in range(tool_list.count()):
                item = tool_list.item(index)
                items.append(
                    {
                        "id": str(item.data(Qt.ItemDataRole.UserRole)),
                        "enabled": item.checkState() == Qt.CheckState.Checked,
                    }
                )
            sections.append({"key": key, "title": self._titles.get(key), "items": items})
        return encode_tool_layout(sections)
