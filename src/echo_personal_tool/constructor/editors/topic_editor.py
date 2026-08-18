"""Left panel: anatomy topics list with drag-reorder and CRUD."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from echo_personal_tool.constructor.models import TopicModel
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_palette


class TopicEditor(BaseEditor):
    """Left panel: anatomy topics (ЛЖ, ЛП, МК, etc.)."""

    topic_selected = Signal(str)  # slug
    topics_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._topics: list[TopicModel] = []
        self._all_items: list[tuple[str, str]] = []  # (name, slug)
        self._build_ui()

    def _build_ui(self) -> None:
        p = get_theme_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QLabel(tr("constructor.topic.header"))
        header.setStyleSheet(
            f"color: {p['text']}; font-weight: bold; padding: 8px 12px; "
            f"background: {p['bg_control']}; border-bottom: 1px solid {p['border']};"
        )
        layout.addWidget(header)

        # List
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.setStyleSheet(
            f"QListWidget {{ border: none; color: {p['text']}; background: {p['bg_panel']}; }}"
            f"QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {p['border']}; }}"
            f"QListWidget::item:selected {{ background: {p['accent']}; color: white; }}"
            f"QListWidget::item:hover {{ background: {p['bg_button_hover']}; }}"
        )
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._list, 1)

    # ── Public API ──

    def set_topics(self, topics: list[TopicModel]) -> None:
        self._topics = topics
        self._all_items = [(t.name, t.slug) for t in topics]
        self._refresh_list()

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
            self.topic_selected.emit(slug)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        slug = item.data(Qt.ItemDataRole.UserRole)
        if slug:
            self._rename_topic(item, slug)

    def _context_menu(self, pos: Any) -> None:
        p = get_theme_palette()
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ color: {p['text']}; background: {p['bg_control']}; border: 1px solid {p['border']}; }}"
            f"QMenu::item:selected {{ background: {p['accent']}; }}"
        )
        item = self._list.currentItem()
        if item:
            slug = item.data(Qt.ItemDataRole.UserRole)
            if slug:
                menu.addAction(tr("constructor.topic.edit"), lambda: self._rename_topic(item, slug))
                menu.addSeparator()
        menu.addAction(tr("constructor.topic.add"), self._add_topic)
        menu.addAction(tr("constructor.topic.delete"), self._delete_selected)
        menu.addAction(tr("constructor.topic.duplicate"), self._duplicate_topic)
        menu.exec(self._list.mapToGlobal(pos))

    def _add_topic(self) -> None:
        # Find unique slug
        existing = {t.slug for t in self._topics}
        idx = 1
        while f"new_topic_{idx}" in existing:
            idx += 1
        slug = f"new_topic_{idx}"

        new_topic = TopicModel(name=tr("constructor.topic.new", idx=str(idx)), slug=slug)
        self._topics.append(new_topic)
        self._all_items.append((new_topic.name, new_topic.slug))
        self._refresh_list()
        self.topics_changed.emit()

    def _delete_selected(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        slug = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self,
            tr("constructor.topic.delete"),
            tr("constructor.topic.delete_confirm", name=item.text()),
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._topics[:] = [t for t in self._topics if t.slug != slug]
            self._all_items = [(t.name, t.slug) for t in self._topics]
            self._refresh_list()
            self.topics_changed.emit()

    def _duplicate_topic(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        slug = item.data(Qt.ItemDataRole.UserRole)
        topic = next((t for t in self._topics if t.slug == slug), None)
        if not topic:
            return

        import copy

        new_topic = copy.deepcopy(topic)
        existing = {t.slug for t in self._topics}
        idx = 1
        while f"{new_topic.slug}_copy_{idx}" in existing:
            idx += 1
        new_topic.slug = f"{new_topic.slug}_copy_{idx}"
        new_topic.name = f"{new_topic.name} {tr('constructor.topic.copy_suffix')}"

        self._topics.append(new_topic)
        self._all_items.append((new_topic.name, new_topic.slug))
        self._refresh_list()
        self.topics_changed.emit()

    def _rename_topic(self, item: QListWidgetItem, slug: str) -> None:
        topic = next((t for t in self._topics if t.slug == slug), None)
        if not topic:
            return

        # Inline rename via QLineEdit overlay
        edit = QLineEdit(item.text())
        edit.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {get_theme_palette()['accent']}; "
            f"color: {get_theme_palette()['text']}; padding: 4px; }}"
        )
        self._list.setItemWidget(item, edit)
        edit.setFocus()
        edit.selectAll()

        def finish():
            new_name = edit.text().strip()
            if new_name:
                topic.name = new_name
            self._list.setItemWidget(item, None)
            self._all_items = [(t.name, t.slug) for t in self._topics]
            self._refresh_list()
            self.topics_changed.emit()

        edit.editingFinished.connect(finish)
        edit.returnPressed.connect(finish)

    def delete_selected(self) -> None:
        self._delete_selected()
