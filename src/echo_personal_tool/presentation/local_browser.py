"""Study tree browser widget."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata

_ITEM_DATA_ROLE = 256


def _instance_label(instance: InstanceMetadata) -> str:
    if instance.number_of_frames == 1:
        frame_label = "1 frame"
    else:
        frame_label = f"{instance.number_of_frames} frames"
    if instance.path is not None:
        filename = instance.path.name
    else:
        filename = f"{instance.sop_instance_uid[:12]}…"
    return f"{filename} ({frame_label})"


class LocalBrowserWidget(QTreeWidget):
    """Tree: Study datetime → Series → Instance."""

    instance_selected = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIconSize(QSize(128, 128))
        self.setHeaderLabels(["Study / Series / Instance"])
        self.itemClicked.connect(self._on_item_clicked)
        self.itemExpanded.connect(self._on_item_expanded)
        self._thumbnail_cache: dict[str, QIcon] = {}
        self._items_by_uid: dict[str, QTreeWidgetItem] = {}
        self._thumbnail_loader: Callable[[InstanceMetadata], None] | None = None

    def set_thumbnail_loader(self, loader: Callable[[InstanceMetadata], None]) -> None:
        self._thumbnail_loader = loader

    def populate(self, studies: list[StudyMetadata]) -> None:
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
                    series_item.addChild(inst_item)
                    self._items_by_uid[instance.sop_instance_uid] = inst_item
                    cached = self._thumbnail_cache.get(instance.sop_instance_uid)
                    if cached is not None:
                        inst_item.setIcon(0, cached)

                if series_item.isExpanded():
                    self._request_series_thumbnails(series_item)

            study_item.setExpanded(True)

    def set_thumbnail(self, sop_instance_uid: str, image: QImage) -> None:
        # PySide6 QIcon rejects QImage directly; pixmap conversion is required.
        icon = QIcon(QPixmap.fromImage(image))
        self._thumbnail_cache[sop_instance_uid] = icon
        item = self._items_by_uid.get(sop_instance_uid)
        if item is not None:
            item.setIcon(0, icon)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 0:
            return
        payload = item.data(0, _ITEM_DATA_ROLE)
        if isinstance(payload, str):
            self._request_series_thumbnails(item)

    def _request_series_thumbnails(self, series_item: QTreeWidgetItem) -> None:
        for index in range(series_item.childCount()):
            child = series_item.child(index)
            payload = child.data(0, _ITEM_DATA_ROLE)
            if isinstance(payload, InstanceMetadata):
                self._request_thumbnail(payload)

    def _request_thumbnail(self, instance: InstanceMetadata) -> None:
        if instance.sop_instance_uid in self._thumbnail_cache:
            return
        if self._thumbnail_loader is None:
            return
        self._thumbnail_loader(instance)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, _ITEM_DATA_ROLE)
        if isinstance(payload, InstanceMetadata):
            self.instance_selected.emit(payload)
