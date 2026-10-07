"""Clinical-style 2-column thumbnail gallery (index, cine, DICOM badges)."""

from __future__ import annotations

import inspect
import shutil
from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from echo_personal_tool.application.thumbnail_scheduler import ThumbnailPriority
from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.instance_sort import sort_instances_by
from echo_personal_tool.presentation.dark_theme import ACCENT_BRIGHT, BG_DARK, TEXT

_ITEM_ROLE = Qt.ItemDataRole.UserRole
_VISIBLE_PADDING = 8
_SCROLL_DEBOUNCE_MS = 25
_THUMBNAIL_PIXMAP_MAX = 200

_THUMBNAIL_SCALES: dict[str, dict[str, tuple[int, int]]] = {
    "small": {"thumb": (72, 54), "cell": (84, 66)},
    "medium": {"thumb": (96, 72), "cell": (108, 84)},
    "large": {"thumb": (176, 132), "cell": (192, 148)},
}
_COLUMN_COUNT = 2
_CELL_SPACING = 2
_SCROLLBAR_GUTTER = 24

ThumbnailLoader = Callable[[InstanceMetadata], None] | Callable[[InstanceMetadata, ThumbnailPriority], None]


class ThumbnailGalleryDelegate(QStyledItemDelegate):
    """Paint thumbnail with index (TL), cine (BL), DICOM (BR)."""

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # type: ignore[override]
        widget = option.widget
        if isinstance(widget, ThumbnailGalleryWidget):
            return QSize(widget.cell_width(), widget.cell_height())
        return QSize(108, 84)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        instance = index.data(_ITEM_ROLE)
        display_index = index.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(instance, InstanceMetadata):
            super().paint(painter, option, index)
            return

        painter.save()
        rect = option.rect
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QColor_from(ACCENT_BRIGHT))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))
        else:
            painter.fillRect(rect, QColor_from(BG_DARK))

        thumb_rect = rect.adjusted(4, 4, -4, -4)
        list_widget = option.widget
        pixmap: QPixmap | None = None
        if isinstance(list_widget, ThumbnailGalleryWidget):
            pixmap = list_widget.thumbnail_pixmap(instance.sop_instance_uid)

        if pixmap is not None and not pixmap.isNull():
            # Scale in device pixels and draw with an explicit DPR: the painter
            # then maps the pixmap onto logical coordinates without upscaling.
            dpr = max(1.0, float(list_widget.devicePixelRatioF())) if isinstance(list_widget, QWidget) else 1.0
            scaled = pixmap.scaled(
                int(round(thumb_rect.width() * dpr)),
                int(round(thumb_rect.height() * dpr)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            x = thumb_rect.x() + (thumb_rect.width() - scaled.width() / dpr) / 2
            y = thumb_rect.y() + (thumb_rect.height() - scaled.height() / dpr) / 2
            painter.drawPixmap(QPointF(x, y), scaled)
        else:
            painter.setPen(QColor_from("#4a5564"))
            painter.drawRect(thumb_rect)

        # Index top-left
        if display_index is not None:
            painter.setPen(QColor_from(TEXT))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(11)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(6, 4, 0, 0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                str(display_index),
            )

        # Cine bottom-left / single-frame
        is_cine = instance.number_of_frames > 1
        badge = "▶" if is_cine else "●"
        painter.setPen(QColor_from("#7ec8ff" if is_cine else "#6a7a8a"))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(
            rect.adjusted(6, 0, 0, -4),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
            badge,
        )

        # DICOM bottom-right
        if _has_dicom_tags(instance):
            painter.setPen(QColor_from("#ffd54f"))
            font.setBold(True)
            font.setPointSize(11)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(0, 0, -6, -4),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom),
                "D",
            )

        painter.restore()


def QColor_from(hex_color: str):  # noqa: N802
    from PySide6.QtGui import QColor

    return QColor(hex_color)


def _has_dicom_tags(instance: InstanceMetadata) -> bool:
    if instance.media_format != "dicom":
        return False
    return instance.pixel_spacing is not None or instance.frame_time_ms is not None


def _gallery_width(cell_w: int) -> int:
    return _COLUMN_COUNT * cell_w + (_COLUMN_COUNT - 1) * _CELL_SPACING + _SCROLLBAR_GUTTER


class ThumbnailGalleryWidget(QListWidget):
    """Two-column vertical thumbnail strip (Clinical left panel)."""

    instance_selected = Signal(object)
    export_mp4_requested = Signal(object)
    #: (instance, "left" | "right") - Multiview context-menu routing.
    open_in_pane_requested = Signal(object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("thumbnailGallery")
        self._collapsed = False
        self._saved_width = None
        self._horizontal_mode = False
        self._thumb_w, self._thumb_h = _THUMBNAIL_SCALES["medium"]["thumb"]
        self._cell_w, self._cell_h = _THUMBNAIL_SCALES["medium"]["cell"]
        self.setItemDelegate(ThumbnailGalleryDelegate(self))
        # LeftToRight + wrap => exactly two columns, rows grow downward (vertical scroll).
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Fixed)
        self.setUniformItemSizes(True)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(_CELL_SPACING)
        self._apply_gallery_metrics()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.itemClicked.connect(self._on_item_clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._multiview_enabled = False
        self._thumbnail_cache: dict[str, QIcon] = {}
        self._thumbnail_pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._items_by_uid: dict[str, QListWidgetItem] = {}
        self._instances: list[InstanceMetadata] = []
        self._studies: list[StudyMetadata] = []
        self._sort_mode = "created"
        self._thumbnail_loader: ThumbnailLoader | None = None
        self._loader_accepts_priority = False
        self._building = False
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(_SCROLL_DEBOUNCE_MS)
        self._scroll_timer.timeout.connect(self.request_visible_previews)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._scroll_timer.start())

        self._mv_start_hint = QLabel(self.viewport())
        self._mv_start_hint.setObjectName("multiviewStartHint")
        self._mv_start_hint.setWordWrap(True)
        self._mv_start_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mv_start_hint.setStyleSheet(
            f"QLabel {{ background-color: rgba(20, 22, 28, 230); color: {ACCENT_BRIGHT};"
            " border: 1px solid rgba(255, 255, 255, 40); border-radius: 6px;"
            " padding: 6px 10px; }"
        )
        self._mv_start_hint.hide()

    def set_multiview_start_hint(self, visible: bool) -> None:
        """Overlay asking for the second clip before Multiview is launched."""
        visible = bool(visible)
        if visible:
            self._mv_start_hint.setText(tr("multiview.gallery.start_hint"))
            self._position_start_hint()
            if self._mv_start_hint.width() > 0:
                self._mv_start_hint.show()
                self._mv_start_hint.raise_()
                return
        self._mv_start_hint.hide()

    def multiview_start_hint_visible(self) -> bool:
        return self._mv_start_hint.isVisible()

    def _position_start_hint(self) -> None:
        margin = 8
        width = self.viewport().width() - 2 * margin
        if width <= 0:
            self._mv_start_hint.setGeometry(0, 0, 0, 0)
            return
        self._mv_start_hint.setFixedWidth(width)
        self._mv_start_hint.adjustSize()
        self._mv_start_hint.move(margin, margin)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._mv_start_hint.isVisible():
            self._position_start_hint()

    def set_multiview_enabled(self, enabled: bool) -> None:
        """Show the "open in pane" actions and the Ctrl+click hint."""
        self._multiview_enabled = bool(enabled)
        self.setToolTip(tr("multiview.gallery.ctrl_hint") if self._multiview_enabled else "")

    def cell_width(self) -> int:
        return self._cell_w

    def cell_height(self) -> int:
        return self._cell_h

    def thumbnail_preview_size(self) -> int:
        """Physical pixel box for the preview decode (Э4).

        The delegate paints at ``thumb × devicePixelRatio`` device pixels, so a
        96 px source on a 150–200 % screen was upscaled and looked soft.  The
        decode box follows the current scale and the screen's DPR.
        """
        dpr = max(1.0, float(self.devicePixelRatioF()))
        return int(round(max(self._thumb_w, self._thumb_h) * dpr))

    def apply_scale(self, scale: str) -> None:
        spec = _THUMBNAIL_SCALES.get(scale, _THUMBNAIL_SCALES["medium"])
        self._thumb_w, self._thumb_h = spec["thumb"]
        self._cell_w, self._cell_h = spec["cell"]
        self._apply_gallery_metrics()
        self.viewport().update()

    def set_horizontal_mode(self, enabled: bool) -> None:
        if enabled:
            self._saved_width = self.width()
            self.setFixedWidth(16777215)
            row_h = self._cell_h + _CELL_SPACING
            self.setFixedHeight(row_h * 2 + 4)
            self.setWrapping(True)
            self.setFlow(QListWidget.Flow.LeftToRight)
            self.setGridSize(QSize(self._cell_w, row_h))
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(_gallery_width(self._cell_w))
            self.setFixedHeight(16777215)
            self.setFlow(QListWidget.Flow.LeftToRight)
            self.setGridSize(QSize(self._cell_w, self._cell_h))
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._horizontal_mode = enabled

    def wheelEvent(self, event) -> None:
        if self._horizontal_mode:
            delta = event.angleDelta().y()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta)
        else:
            super().wheelEvent(event)

    def _apply_gallery_metrics(self) -> None:
        self.setGridSize(QSize(self._cell_w, self._cell_h))
        self.setIconSize(QSize(self._thumb_w, self._thumb_h))
        self.setFixedWidth(_gallery_width(self._cell_w))

    def set_thumbnail_loader(self, loader: ThumbnailLoader) -> None:
        self._thumbnail_loader = loader
        try:
            sig = inspect.signature(loader)
            self._loader_accepts_priority = len(sig.parameters) >= 2
        except (TypeError, ValueError):
            self._loader_accepts_priority = False

    def set_sort_mode(self, mode: str) -> None:
        """Choose the panel order; re-populates when a study is already shown."""
        normalized = mode if mode in ("created", "filename") else "created"
        if normalized == self._sort_mode:
            return
        self._sort_mode = normalized
        if self._studies:
            self.populate(self._studies)

    def populate(self, studies: list[StudyMetadata]) -> None:
        self._building = True
        self._studies = list(studies)
        self.clear()
        self._items_by_uid.clear()
        self._instances.clear()
        self._thumbnail_pixmaps.clear()
        self._thumbnail_cache.clear()
        flattened = [instance for study in studies for series in study.series for instance in series.instances]
        ordered = sort_instances_by(flattened, self._sort_mode)
        for index, instance in enumerate(ordered, start=1):
            self._instances.append(instance)
            item = QListWidgetItem()
            item.setData(_ITEM_ROLE, instance)
            item.setData(Qt.ItemDataRole.UserRole + 1, index)
            item.setSizeHint(QSize(self._cell_w, self._cell_h))
            cached = self._thumbnail_cache.get(instance.sop_instance_uid)
            if cached is not None:
                item.setIcon(cached)
            self.addItem(item)
            self._items_by_uid[instance.sop_instance_uid] = item
        self._building = False
        QTimer.singleShot(0, self._after_populate)

    def _after_populate(self) -> None:
        self.request_visible_previews()
        self._enqueue_background_previews()

    def _enqueue_background_previews(self) -> None:
        if self._thumbnail_loader is None:
            return
        for instance in self._instances:
            uid = instance.sop_instance_uid
            if uid in self._thumbnail_pixmaps:
                continue
            if self._loader_accepts_priority:
                self._thumbnail_loader(instance, ThumbnailPriority.P2_BACKGROUND)  # type: ignore[misc]
            else:
                self._thumbnail_loader(instance)  # type: ignore[misc]

    def request_visible_previews(self, selected_instance: InstanceMetadata | None = None) -> None:
        if self._building or self._thumbnail_loader is None:
            return
        selected_uid = selected_instance.sop_instance_uid if selected_instance is not None else None
        if selected_uid is None:
            current = self.currentItem()
            if current is not None:
                payload = current.data(_ITEM_ROLE)
                if isinstance(payload, InstanceMetadata):
                    selected_uid = payload.sop_instance_uid

        visible_uids = self._visible_instance_uids()
        for row in range(self.count()):
            item = self.item(row)
            if item is None:
                continue
            instance = item.data(_ITEM_ROLE)
            if not isinstance(instance, InstanceMetadata):
                continue
            uid = instance.sop_instance_uid
            if uid in self._thumbnail_pixmaps:
                continue
            if uid not in visible_uids and uid != selected_uid:
                continue
            priority = (
                ThumbnailPriority.P0_VISIBLE_SELECTED if uid == selected_uid else ThumbnailPriority.P1_NEAR_VISIBLE
            )
            if self._loader_accepts_priority:
                self._thumbnail_loader(instance, priority)  # type: ignore[misc]
            else:
                self._thumbnail_loader(instance)  # type: ignore[misc]

    def set_thumbnail(self, instance_uid: str, image: QImage) -> None:
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        icon = QIcon(pixmap)
        if instance_uid in self._thumbnail_pixmaps:
            self._thumbnail_pixmaps.move_to_end(instance_uid)
        else:
            if len(self._thumbnail_pixmaps) >= _THUMBNAIL_PIXMAP_MAX:
                evicted_uid, _ = self._thumbnail_pixmaps.popitem(last=False)
                self._thumbnail_cache.pop(evicted_uid, None)
            self._thumbnail_pixmaps[instance_uid] = pixmap
        self._thumbnail_cache[instance_uid] = icon
        item = self._items_by_uid.get(instance_uid)
        if item is not None:
            item.setIcon(icon)
            self.viewport().update()
        self._scroll_timer.start()

    def thumbnail_pixmap(self, instance_uid: str) -> QPixmap | None:
        return self._thumbnail_pixmaps.get(instance_uid)

    def select_instance(self, instance: InstanceMetadata) -> None:
        item = self._items_by_uid.get(instance.sop_instance_uid)
        if item is not None:
            self.setCurrentItem(item)
            self.scrollToItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        instance = item.data(_ITEM_ROLE)
        if isinstance(instance, InstanceMetadata):
            self.instance_selected.emit(instance)

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        instance = item.data(_ITEM_ROLE)
        if not isinstance(instance, InstanceMetadata):
            return
        menu = QMenu(self)
        if self._multiview_enabled:
            menu.addAction(
                tr("multiview.gallery.open_left"),
                lambda: self.open_in_pane_requested.emit(instance, "left"),
            )
            menu.addAction(
                tr("multiview.gallery.open_right"),
                lambda: self.open_in_pane_requested.emit(instance, "right"),
            )
            menu.addSeparator()
        if instance.media_format == "dicom":
            menu.addAction(
                tr("gallery.copy_dicom"),
                lambda: self._copy_source_file(instance),
            )
            menu.addAction(
                tr("gallery.export_mp4"),
                lambda: self.export_mp4_requested.emit(instance),
            )
        elif instance.media_format == "mp4":
            menu.addAction(
                tr("gallery.copy_mp4"),
                lambda: self._copy_source_file(instance),
            )
        menu.exec(self.viewport().mapToGlobal(pos))

    def _copy_source_file(self, instance: InstanceMetadata) -> None:
        if instance.path is None:
            return
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        default_name = instance.path.name
        dest, _ = styled_save_file(
            self,
            tr("gallery.save_file"),
            default_name,
        )
        if dest:
            shutil.copy2(str(instance.path), dest)

    def toggle_collapse(self) -> None:
        if self._collapsed:
            self._animate_expand()
        else:
            self._animate_collapse()

    def select_next_instance(self) -> None:
        current = self.currentItem()
        if current is None:
            return
        row = self.row(current) + 1
        if row < self.count():
            self.setCurrentRow(row)
            item = self.item(row)
            if item is not None:
                instance = item.data(_ITEM_ROLE)
                if isinstance(instance, InstanceMetadata):
                    self.instance_selected.emit(instance)

    def select_previous_instance(self) -> None:
        current = self.currentItem()
        if current is None:
            return
        row = self.row(current) - 1
        if row >= 0:
            self.setCurrentRow(row)
            item = self.item(row)
            if item is not None:
                instance = item.data(_ITEM_ROLE)
                if isinstance(instance, InstanceMetadata):
                    self.instance_selected.emit(instance)

    def _animate_collapse(self) -> None:
        self._saved_width = self.width()
        self._anim = QPropertyAnimation(self, b"maximumWidth")
        self._anim.setDuration(200)
        self._anim.setStartValue(self._saved_width)
        self._anim.setEndValue(0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._anim.finished.connect(lambda: (self.hide(), setattr(self, "_collapsed", True)))
        self._anim.start()

    def _animate_expand(self) -> None:
        target = self._saved_width or _gallery_width(self._cell_w)
        self.show()
        self.setMaximumWidth(0)
        self._anim = QPropertyAnimation(self, b"maximumWidth")
        self._anim.setDuration(200)
        self._anim.setStartValue(0)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._anim.finished.connect(
            lambda: (
                self.setMaximumWidth(16777215),
                self.setFixedWidth(target),
                setattr(self, "_collapsed", False),
            )
        )
        self._anim.start()

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def _visible_instance_uids(self) -> set[str]:
        uids: set[str] = set()
        viewport = self.viewport()
        if viewport is None:
            return uids
        for row in range(self.count()):
            item = self.item(row)
            if item is None:
                continue
            rect = self.visualItemRect(item)
            padded = rect.adjusted(0, -_VISIBLE_PADDING * 4, 0, _VISIBLE_PADDING * 4)
            if not viewport.rect().intersects(padded):
                continue
            instance = item.data(_ITEM_ROLE)
            if isinstance(instance, InstanceMetadata):
                uids.add(instance.sop_instance_uid)
        return uids
