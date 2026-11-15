"""«Ключевые кадры» — durable stills with an honest source status (issue 561).

The dialog lists references owned by the current study, not a second copy of
the images.  Adding stores the SOP/frame/measurement identity and the file's
stat identity; opening goes through the report coordinator's existing
«Открыть кадры» path, so the provenance card of issue 284 remains the one place
that explains where a value came from.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Protocol, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.composition import services_of
from echo_personal_tool.application.key_images import (
    key_image_status,
    measurement_id_at,
    new_key_image,
)
from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.key_image import (
    KEY_IMAGE_AVAILABLE,
    KEY_IMAGE_CHANGED,
    KEY_IMAGE_MISSING,
    KeyImage,
)
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState

if TYPE_CHECKING:
    from echo_personal_tool.application.key_images import KeyImageService
    from echo_personal_tool.domain.models.metadata import StudyMetadata

    class _StateSource(Protocol):
        @property
        def snapshot(self) -> ViewerState: ...

    class _ControllerView(Protocol):
        @property
        def studies(self) -> list[StudyMetadata]: ...

        @property
        def state_manager(self) -> _StateSource: ...

        def resolve_study_uid(self, instance: InstanceMetadata | None = None) -> str: ...

    class _Navigator(Protocol):
        def open_frames(self, sop_instance_uid: str, frame_index: int) -> None: ...

    class _KeyImagesHost(Protocol):
        _controller: _ControllerView
        report_coordinator: _Navigator


_STATUS_KEYS = {
    KEY_IMAGE_AVAILABLE: "key_images.status.available",
    KEY_IMAGE_MISSING: "key_images.status.missing",
    KEY_IMAGE_CHANGED: "key_images.status.changed",
}


def _status_text(status: str) -> str:
    return tr(_STATUS_KEYS.get(status, "key_images.status.changed"))


def _clip_text(image: KeyImage, instances: Mapping[str, InstanceMetadata]) -> str:
    instance = instances.get(image.sop_instance_uid)
    if instance is not None and instance.series_description:
        return instance.series_description
    if instance is not None:
        return instance.modality or image.sop_instance_uid[-8:]
    return image.sop_instance_uid[-8:]


class KeyImagesDialog(QDialog):
    """List of key images of one study, with add/delete/go actions."""

    def __init__(
        self,
        *,
        service: KeyImageService,
        study_uid: str,
        instances: Mapping[str, InstanceMetadata],
        snapshot: ViewerState | None,
        navigate: Callable[[str, int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._study_uid = study_uid
        self._instances = dict(instances)
        self._snapshot = snapshot
        self._navigate = navigate
        self._images: tuple[KeyImage, ...] = ()
        self.setObjectName("keyImagesDialog")
        self.setWindowTitle(tr("key_images.title"))
        self.setModal(True)
        self.resize(560, 380)

        self._list = QListWidget(self)
        self._list.setObjectName("keyImagesList")
        self._list.setAlternatingRowColors(True)
        self._list.currentItemChanged.connect(self._sync_actions)
        self._list.itemDoubleClicked.connect(lambda _item: self.open_selected())

        self._empty = QLabel(tr("key_images.empty"), self)
        self._empty.setObjectName("keyImagesEmpty")
        self._empty.setWordWrap(True)

        self._status = QLabel("", self)
        self._status.setObjectName("keyImagesStatus")
        self._status.setWordWrap(True)

        self._add = QPushButton(tr("key_images.add_current"), self)
        self._add.setObjectName("keyImagesAdd")
        self._add.clicked.connect(self.add_current)
        self._delete = QPushButton(tr("key_images.delete"), self)
        self._delete.setObjectName("keyImagesDelete")
        self._delete.clicked.connect(self.delete_selected)
        self._open = QPushButton(tr("key_images.open_selected"), self)
        self._open.setObjectName("keyImagesOpen")
        self._open.clicked.connect(self.open_selected)
        self._close = QPushButton(tr("button.close"), self)
        self._close.setObjectName("keyImagesClose")
        self._close.clicked.connect(self.accept)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self._add)
        actions.addWidget(self._delete)
        actions.addStretch(1)
        actions.addWidget(self._open)
        actions.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._empty)
        layout.addWidget(self._status)
        layout.addLayout(actions)

        self.refresh()

    @property
    def images(self) -> tuple[KeyImage, ...]:
        return self._images

    @property
    def status_text(self) -> str:
        return self._status.text()

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _sync_actions(self) -> None:
        has_selection = self._list.currentItem() is not None
        self._delete.setEnabled(has_selection)
        self._open.setEnabled(has_selection)
        self._add.setEnabled(self._snapshot is not None and self._snapshot.instance is not None)

    def refresh(self) -> None:
        self._list.clear()
        try:
            self._images = self._service.images(self._study_uid)
        except (OSError, ValueError):
            self._images = ()
            self._set_status(tr("key_images.status.read_failed"))
        for image in reversed(self._images):
            status = key_image_status(image, self._instances)
            item = QListWidgetItem(self._row_text(image, status))
            item.setData(Qt.ItemDataRole.UserRole, image)
            item.setToolTip(_status_text(status))
            self._list.addItem(item)
        self._empty.setVisible(not self._images)
        self._sync_actions()
        if self._images and self._list.currentItem() is None:
            self._list.setCurrentRow(0)

    def _row_text(self, image: KeyImage, status: str) -> str:
        frame = tr("key_images.frame", frame=image.frame_index + 1, total=image.frame_count)
        details = [frame]
        if image.measurement_id:
            details.append(tr("key_images.measurement", id=image.measurement_id[-8:]))
        return f"{_clip_text(image, self._instances)} · {' · '.join(details)}\n{_status_text(status)}"

    def _selected_image(self) -> KeyImage | None:
        item = self._list.currentItem()
        if item is None:
            return None
        image = item.data(Qt.ItemDataRole.UserRole)
        return image if isinstance(image, KeyImage) else None

    def add_current(self) -> None:
        snapshot = self._snapshot
        instance = snapshot.instance if snapshot is not None else None
        if snapshot is None or instance is None or instance.path is None:
            self._set_status(tr("key_images.status.no_source"))
            return
        frame = int(snapshot.current_frame_index or 0)
        if instance.number_of_frames < 1 or not 0 <= frame < instance.number_of_frames:
            self._set_status(tr("key_images.status.no_source"))
            return
        try:
            stat = instance.path.stat()
        except OSError:
            self._set_status(tr("key_images.status.missing"))
            return
        image = new_key_image(
            sop_instance_uid=instance.sop_instance_uid,
            series_uid=instance.series_uid,
            frame_index=frame,
            frame_count=instance.number_of_frames,
            measurement_id=measurement_id_at(snapshot, instance.sop_instance_uid, frame),
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
        )
        try:
            self._service.add(self._study_uid, image)
        except (OSError, ValueError):
            self._set_status(tr("key_images.status.save_failed"))
            return
        self.refresh()
        self._select(image.bookmark_id)
        self._set_status(tr("key_images.status.saved"))

    def _select(self, bookmark_id: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            image = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(image, KeyImage) and image.bookmark_id == bookmark_id:
                self._list.setCurrentItem(item)
                return

    def delete_selected(self) -> None:
        image = self._selected_image()
        if image is None:
            return
        try:
            self._service.remove(self._study_uid, image.bookmark_id)
        except (OSError, ValueError):
            self._set_status(tr("key_images.status.save_failed"))
            return
        self.refresh()
        self._set_status(tr("key_images.status.deleted"))

    def open_selected(self) -> None:
        image = self._selected_image()
        if image is None:
            return
        status = key_image_status(image, self._instances)
        if status != KEY_IMAGE_AVAILABLE:
            self._set_status(tr("key_images.status.cannot_open", status=_status_text(status)))
            return
        self._navigate(image.sop_instance_uid, image.frame_index)
        self.accept()


def show_key_images(window: object) -> None:
    """Open the study's key images; the window supplies status and navigation."""
    host = cast(_KeyImagesHost, window)
    services = services_of(host._controller)
    if services is None:
        return
    snapshot = host._controller.state_manager.snapshot
    instance = snapshot.instance
    if instance is None:
        QMessageBox.information(cast(QWidget, window), tr("key_images.title"), tr("key_images.status.no_study"))
        return
    study_uid = host._controller.resolve_study_uid(instance)
    if study_uid == "__default__":
        QMessageBox.information(cast(QWidget, window), tr("key_images.title"), tr("key_images.status.no_study"))
        return
    instances = {
        item.sop_instance_uid: item
        for study in host._controller.studies
        for series in study.series
        for item in series.instances
    }
    dialog = KeyImagesDialog(
        service=services.key_images,
        study_uid=study_uid,
        instances=instances,
        snapshot=snapshot,
        navigate=host.report_coordinator.open_frames,
        parent=cast(QWidget, window),
    )
    dialog.exec()
