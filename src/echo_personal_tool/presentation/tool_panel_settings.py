"""Tools tab: customize the Measures tool panel per section.

Each group box mirrors a toolbar section; every tool is a checkable item and
items can be dragged between sections.  Sections are laid out in two columns
so the tab fits without nested scrolling.  The resulting layout is serialized
as JSON and persisted through ``UserPreferences.tool_panel_layout_json``.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.measures_menu import (
    _MenuButton,
    decode_tool_layout,
    default_tool_layout,
    encode_tool_layout,
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
    """Editor for the tool panel's sections, tools and visibility."""

    def __init__(self, layout_json: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = decode_tool_layout(layout_json) or default_tool_layout()
        self._lists: dict[str, _ToolListWidget] = {}
        self._build()

    def _build(self) -> None:
        catalog = tool_menu_catalog()
        spec_by_id = {spec.tool_id: spec for _key, buttons in catalog for spec in buttons}
        assigned = {entry["key"]: entry for entry in self._layout}
        known = {item["id"] for entry in self._layout for item in entry.get("items", [])}

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(4, 8, 4, 8)
        host_layout.setSpacing(8)

        hint = QLabel(tr("preferences.tools_hint"))
        hint.setWordWrap(True)
        host_layout.addWidget(hint)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        host_layout.addLayout(grid)
        host_layout.addStretch(1)
        self._grid = grid

        for index, (group_key, buttons) in enumerate(catalog):
            box = QGroupBox(tr(group_key))
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(6, 6, 6, 6)

            tool_list = _ToolListWidget(box)
            entry = assigned.get(group_key, {"items": []})
            for item in entry.get("items", []):
                spec = spec_by_id.get(item["id"])
                if spec is not None:
                    tool_list.addItem(self._make_item(spec, bool(item.get("enabled", True))))
            for spec in buttons:
                if spec.tool_id not in known:
                    tool_list.addItem(self._make_item(spec, True))

            tool_list.rows_changed.connect(self._reflow)
            self._lists[group_key] = tool_list
            box_layout.addWidget(tool_list)
            grid.addWidget(box, index // 2, index % 2, Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._reflow()

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
        """Serialize the current arrangement (order + visibility)."""
        layout: list[dict[str, object]] = []
        for group_key, _buttons in tool_menu_catalog():
            tool_list = self._lists[group_key]
            items: list[dict[str, object]] = []
            for index in range(tool_list.count()):
                item = tool_list.item(index)
                items.append(
                    {
                        "id": str(item.data(Qt.ItemDataRole.UserRole)),
                        "enabled": item.checkState() == Qt.CheckState.Checked,
                    }
                )
            layout.append({"key": group_key, "items": items})
        return encode_tool_layout(layout)
