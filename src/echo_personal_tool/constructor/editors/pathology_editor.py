"""Right-top panel: pathology list per topic with multi-select and CRUD."""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.constructor.editors.base_editor import BaseEditor
from echo_personal_tool.constructor.models import PathologyModel
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_palette


class PathologyEditor(BaseEditor):
    """Right-top panel: pathologies list with multi-select support."""

    pathology_selected = Signal(str)  # slug (single selection for display)
    pathologies_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pathologies: list[PathologyModel] = []
        self._all_items: list[tuple[str, str]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        p = get_theme_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QLabel(tr("constructor.pathology.header"))
        header.setStyleSheet(
            f"color: {p['text']}; font-weight: bold; padding: 8px 12px; "
            f"background: {p['bg_control']}; border-bottom: 1px solid {p['border']};"
        )
        layout.addWidget(header)

        # Multi-select checkbox
        self._multi_check = QCheckBox("Multi-select")
        self._multi_check.setStyleSheet(f"color: {p['text']}; padding: 4px 12px;")
        self._multi_check.toggled.connect(self._on_multi_toggled)
        layout.addWidget(self._multi_check)

        # List
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.setStyleSheet(
            f"QListWidget {{ border: none; color: {p['text']}; background: {p['bg_panel']}; }}"
            f"QListWidget::item {{ padding: 6px 12px; border-bottom: 1px solid {p['border']}; }}"
            f"QListWidget::item:selected {{ background: {p['accent']}; color: white; }}"
            f"QListWidget::item:hover {{ background: {p['bg_button_hover']}; }}"
        )
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._list, 1)

    # ── Public API ──

    def set_pathologies(self, pathologies: list[PathologyModel]) -> None:
        self._pathologies = pathologies
        self._all_items = [(p.name, p.slug) for p in pathologies]
        self._refresh_list()

    def get_selected_slugs(self) -> list[str]:
        """Return slugs of all selected items."""
        return [item.data(Qt.ItemDataRole.UserRole) for item in self._list.selectedItems()]

    def filter(self, query: str) -> None:
        self._list.clear()
        for name, slug in self._all_items:
            if query in name.lower() or query in slug.lower():
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, slug)
                self._list.addItem(item)

    def clear_filter(self) -> None:
        self._refresh_list()

    # ── Private ──

    def _refresh_list(self) -> None:
        self._list.clear()
        for name, slug in self._all_items:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, slug)
            self._list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        slug = item.data(Qt.ItemDataRole.UserRole)
        if slug:
            self.pathology_selected.emit(slug)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        slug = item.data(Qt.ItemDataRole.UserRole)
        if slug:
            self._rename_pathology(item, slug)

    def _on_multi_toggled(self, checked: bool) -> None:
        if checked:
            self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        else:
            self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def _context_menu(self, pos: Any) -> None:
        p = get_theme_palette()
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ color: {p['text']}; background: {p['bg_control']}; border: 1px solid {p['border']}; }}"
            f"QMenu::item:selected {{ background: {p['accent']}; }}"
        )
        menu.addAction(tr("constructor.pathology.add"), self._add_pathology)
        menu.addAction(tr("constructor.pathology.delete"), self.delete_selected)
        menu.addAction(tr("constructor.pathology.duplicate"), self._duplicate_pathology)
        menu.exec(self._list.mapToGlobal(pos))

    def _add_pathology(self) -> None:
        existing = {p.slug for p in self._pathologies}
        idx = 1
        while f"new_pathology_{idx}" in existing:
            idx += 1
        slug = f"new_pathology_{idx}"

        new_patho = PathologyModel(name=tr("constructor.pathology.new", idx=str(idx)), slug=slug)
        self._pathologies.append(new_patho)
        self._all_items.append((new_patho.name, new_patho.slug))
        self._refresh_list()
        self.pathologies_changed.emit()

    def delete_selected(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        names = [item.text() for item in selected]
        reply = QMessageBox.question(
            self,
            tr("constructor.pathology.delete_title"),
            tr(
                "constructor.pathology.delete_confirm",
                count=str(len(names)),
                names=", ".join(names[:5]) + ("..." if len(names) > 5 else ""),
            ),
        )
        if reply == QMessageBox.StandardButton.Yes:
            slugs_to_delete = {item.data(Qt.ItemDataRole.UserRole) for item in selected}
            self._pathologies[:] = [p for p in self._pathologies if p.slug not in slugs_to_delete]
            self._all_items = [(p.name, p.slug) for p in self._pathologies]
            self._refresh_list()
            self.pathologies_changed.emit()

    def _duplicate_pathology(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        slug = item.data(Qt.ItemDataRole.UserRole)
        patho = next((p for p in self._pathologies if p.slug == slug), None)
        if not patho:
            return

        new_patho = copy.deepcopy(patho)
        existing = {p.slug for p in self._pathologies}
        idx = 1
        while f"{new_patho.slug}_copy_{idx}" in existing:
            idx += 1
        new_patho.slug = f"{new_patho.slug}_copy_{idx}"
        new_patho.name = f"{new_patho.name} {tr('constructor.pathology.copy_suffix')}"

        self._pathologies.append(new_patho)
        self._all_items.append((new_patho.name, new_patho.slug))
        self._refresh_list()
        self.pathologies_changed.emit()

    def _rename_pathology(self, item: QListWidgetItem, slug: str) -> None:
        patho = next((p for p in self._pathologies if p.slug == slug), None)
        if not patho:
            return

        edit = QLineEdit(item.text())
        p = get_theme_palette()
        edit.setStyleSheet(f"QLineEdit {{ border: 1px solid {p['accent']}; color: {p['text']}; padding: 4px; }}")
        self._list.setItemWidget(item, edit)
        edit.setFocus()
        edit.selectAll()

        def finish():
            new_name = edit.text().strip()
            if new_name:
                patho.name = new_name
            try:
                self._list.setItemWidget(item, None)
            except RuntimeError:
                pass  # Item already deleted
            self._all_items = [(p.name, p.slug) for p in self._pathologies]
            self._refresh_list()
            self.pathologies_changed.emit()

        edit.editingFinished.connect(finish)
        edit.returnPressed.connect(finish)
