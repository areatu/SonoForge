"""Study tree browser widget."""

from __future__ import annotations

import inspect
from collections.abc import Callable

from PySide6.QtCore import QSize, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from echo_personal_tool.application.thumbnail_scheduler import ThumbnailPriority
from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
from echo_personal_tool.presentation.browser_item_delegate import (
    THUMB_ROW_HEIGHT,
    THUMB_WIDTH,
    InstanceThumbnailDelegate,
)

_ITEM_DATA_ROLE = 256
_VISIBLE_WINDOW_PADDING = 6
_SCROLL_REQUEST_DEBOUNCE_MS = 25

ThumbnailLoader = Callable[[InstanceMetadata], None] | Callable[
    [InstanceMetadata, ThumbnailPriority], None
]


def _instance_label(instance: InstanceMetadata) -> str:
    if instance.number_of_frames == 1:
        frame_label = "1 frame"
    else:
        frame_label = f"{instance.number_of_frames} frames"
    if instance.path is not None:
        filename = instance.path.name
    else:
        filename = f"{instance.sop_instance_uid[:12]}…"
    return f"{filename}\n({frame_label})"


class LocalBrowserWidget(QTreeWidget):
    """Tree: Study datetime → Series → Instance."""

    instance_selected = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIconSize(QSize(128, 128))
        self.setHeaderLabels(["Study / Series / Instance"])
        self.setItemDelegate(InstanceThumbnailDelegate(self))
        self.setUniformRowHeights(False)
        self.setMinimumWidth(220)
        self.itemClicked.connect(self._on_item_clicked)
        self.itemExpanded.connect(self._on_item_expanded)
        self._thumbnail_cache: dict[str, QIcon] = {}
        self._thumbnail_pixmaps: dict[str, QPixmap] = {}
        self._items_by_uid: dict[str, QTreeWidgetItem] = {}
        self._thumbnail_loader: ThumbnailLoader | None = None
        self._thumbnail_loader_accepts_priority = False
        self._building_tree = False
        self._scroll_request_timer = QTimer(self)
        self._scroll_request_timer.setSingleShot(True)
        self._scroll_request_timer.setInterval(_SCROLL_REQUEST_DEBOUNCE_MS)
        self._scroll_request_timer.timeout.connect(self.request_visible_previews)
        self.verticalScrollBar().valueChanged.connect(self._on_scrollbar_moved)

    def set_thumbnail_loader(self, loader: ThumbnailLoader) -> None:
        self._thumbnail_loader = loader
        self._thumbnail_loader_accepts_priority = self._accepts_priority(loader)

    def populate(self, studies: list[StudyMetadata]) -> None:
        self._building_tree = True
        self.clear()
        self._items_by_uid.clear()
        for study in studies:
            label = study.study_datetime.strftime("%Y-%m-%d %H:%M:%S")
            study_item = QTreeWidgetItem([label])
            study_item.setData(0, _ITEM_DATA_ROLE, study.study_uid)
            self.addTopLevelItem(study_item)

            for series in study.series:
                series_label = f"{series.modality} — {series.description or series.series_uid[:8]}"
                series_item = QTreeWidgetItem([series_label])
                series_item.setData(0, _ITEM_DATA_ROLE, series.series_uid)
                study_item.addChild(series_item)

                for instance in series.instances:
                    inst_label = _instance_label(instance)
                    inst_item = QTreeWidgetItem([inst_label])
                    inst_item.setData(0, _ITEM_DATA_ROLE, instance)
                    inst_item.setSizeHint(0, QSize(THUMB_WIDTH, THUMB_ROW_HEIGHT))
                    series_item.addChild(inst_item)
                    self._items_by_uid[instance.sop_instance_uid] = inst_item
                    cached = self._thumbnail_cache.get(instance.sop_instance_uid)
                    if cached is not None:
                        inst_item.setIcon(0, cached)

            study_item.setExpanded(True)
            for index in range(study_item.childCount()):
                series_item = study_item.child(index)
                series_item.setExpanded(True)
        self._building_tree = False

    def request_visible_previews(
        self, selected_instance: InstanceMetadata | None = None
    ) -> None:
        if self._building_tree:
            return
        visible_instances = self._collect_visible_instances()
        nearby_instances = self._collect_nearby_instances(padding=_VISIBLE_WINDOW_PADDING)
        selected_uid = (
            selected_instance.sop_instance_uid if selected_instance is not None else None
        )

        if selected_uid is None:
            current_item = self.currentItem()
            if current_item is not None:
                payload = current_item.data(0, _ITEM_DATA_ROLE)
                if isinstance(payload, InstanceMetadata):
                    selected_uid = payload.sop_instance_uid

        for instance in nearby_instances:
            self._request_thumbnail(instance, priority=ThumbnailPriority.P2_BACKGROUND)

        for instance in visible_instances:
            priority = ThumbnailPriority.P1_NEAR_VISIBLE
            if instance.sop_instance_uid == selected_uid:
                priority = ThumbnailPriority.P0_VISIBLE_SELECTED
            self._request_thumbnail(instance, priority=priority)

    def thumbnail_pixmap(self, sop_instance_uid: str) -> QPixmap | None:
        return self._thumbnail_pixmaps.get(sop_instance_uid)

    def set_thumbnail(self, sop_instance_uid: str, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            return
        self._thumbnail_pixmaps[sop_instance_uid] = pixmap
        icon = QIcon(pixmap)
        self._thumbnail_cache[sop_instance_uid] = icon
        item = self._items_by_uid.get(sop_instance_uid)
        if item is not None:
            item.setIcon(0, icon)
            item.setSizeHint(0, QSize(THUMB_WIDTH, THUMB_ROW_HEIGHT))
            index = self.indexFromItem(item, 0)
            if index.isValid():
                self.update(index)
            self.scheduleDelayedItemsLayout()
            self.viewport().update()

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if self._building_tree:
            return
        if item.childCount() == 0:
            return
        self.request_visible_previews()

    def _request_thumbnail(
        self,
        instance: InstanceMetadata,
        priority: ThumbnailPriority = ThumbnailPriority.P2_BACKGROUND,
    ) -> None:
        if instance.sop_instance_uid in self._thumbnail_cache:
            return
        if self._thumbnail_loader is None:
            return
        if self._thumbnail_loader_accepts_priority:
            self._thumbnail_loader(instance, priority)
            return
        self._thumbnail_loader(instance)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, _ITEM_DATA_ROLE)
        if isinstance(payload, InstanceMetadata):
            self.request_visible_previews(selected_instance=payload)
            self.instance_selected.emit(payload)

    def _on_scrollbar_moved(self, _value: int) -> None:
        if self._building_tree:
            return
        self._scroll_request_timer.start()

    def _collect_visible_instances(self) -> list[InstanceMetadata]:
        visible_items = self._collect_visible_instance_items()
        instances: list[InstanceMetadata] = []
        for item in visible_items:
            payload = item.data(0, _ITEM_DATA_ROLE)
            if isinstance(payload, InstanceMetadata):
                instances.append(payload)
        return instances

    def _collect_nearby_instances(self, padding: int = 20) -> list[InstanceMetadata]:
        visible_items = self._collect_visible_instance_items()
        nearby_items = self._collect_nearby_items(visible_items, padding=padding)
        instances: list[InstanceMetadata] = []
        for item in nearby_items:
            payload = item.data(0, _ITEM_DATA_ROLE)
            if isinstance(payload, InstanceMetadata):
                instances.append(payload)
        return instances

    def _collect_visible_instance_items(self) -> list[QTreeWidgetItem]:
        viewport_rect = self.viewport().rect()
        visible_items: list[QTreeWidgetItem] = []
        for item in self._iter_instance_items():
            rect = self.visualItemRect(item)
            if not rect.isValid():
                continue
            if viewport_rect.intersects(rect):
                visible_items.append(item)
        return visible_items

    def _collect_nearby_items(
        self, visible_items: list[QTreeWidgetItem], padding: int = _VISIBLE_WINDOW_PADDING
    ) -> list[QTreeWidgetItem]:
        ordered_items: list[QTreeWidgetItem] = []
        for item in self._iter_instance_items():
            rect = self.visualItemRect(item)
            if rect.isValid():
                ordered_items.append(item)
        if not ordered_items:
            return []
        if not visible_items:
            return ordered_items[: padding * 2]

        index_by_item = {item: idx for idx, item in enumerate(ordered_items)}
        visible_indexes = [
            index_by_item[item] for item in visible_items if item in index_by_item
        ]
        if not visible_indexes:
            return []

        start = max(0, min(visible_indexes) - padding)
        end = min(len(ordered_items), max(visible_indexes) + padding + 1)
        visible_set = set(visible_items)
        return [item for item in ordered_items[start:end] if item not in visible_set]

    def _iter_instance_items(self):
        for study_index in range(self.topLevelItemCount()):
            study_item = self.topLevelItem(study_index)
            for series_index in range(study_item.childCount()):
                series_item = study_item.child(series_index)
                for instance_index in range(series_item.childCount()):
                    yield series_item.child(instance_index)

    @staticmethod
    def _accepts_priority(loader: ThumbnailLoader) -> bool:
        try:
            signature = inspect.signature(loader)
        except (TypeError, ValueError):
            return False

        positional_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(positional_params) >= 2:
            return True
        return any(
            parameter.kind == inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
