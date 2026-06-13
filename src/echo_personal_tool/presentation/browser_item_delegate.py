"""Custom tree item rendering for instance thumbnails."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget

from echo_personal_tool.domain.models import InstanceMetadata

_ITEM_DATA_ROLE = 256
THUMB_SIDE = 128
THUMB_ROW_HEIGHT = 156
THUMB_WIDTH = 220
_TEXT_HEIGHT = 28


class InstanceThumbnailDelegate(QStyledItemDelegate):
    """Paint instance rows with thumbnail above filename."""

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # type: ignore[override]
        if index.column() != 0:
            index = index.siblingAtColumn(0)
        tree = option.widget
        if isinstance(tree, QTreeWidget):
            item = tree.itemFromIndex(index)
            if item is not None and isinstance(item.data(0, _ITEM_DATA_ROLE), InstanceMetadata):
                width = max(option.rect.width(), THUMB_WIDTH)
                return QSize(width, THUMB_ROW_HEIGHT)
        return super().sizeHint(option, index)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        if index.column() != 0:
            index = index.siblingAtColumn(0)
        tree = option.widget
        if not isinstance(tree, QTreeWidget) or not hasattr(tree, "thumbnail_pixmap"):
            super().paint(painter, option, index)
            return

        item = tree.itemFromIndex(index)
        if item is None:
            super().paint(painter, option, index)
            return

        instance = item.data(0, _ITEM_DATA_ROLE)
        if not isinstance(instance, InstanceMetadata):
            super().paint(painter, option, index)
            return

        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        rect = option.rect
        icon_size = min(THUMB_SIDE, rect.width() - 8, THUMB_ROW_HEIGHT - _TEXT_HEIGHT - 8)
        icon_x = rect.x() + (rect.width() - icon_size) // 2
        icon_y = rect.y() + 4
        icon_rect = QRect(icon_x, icon_y, icon_size, icon_size)

        pixmap = tree.thumbnail_pixmap(instance.sop_instance_uid)  # type: ignore[attr-defined]
        if pixmap is not None and not pixmap.isNull():
            painter.drawPixmap(icon_rect, pixmap)

        text_rect = QRect(
            rect.x() + 2,
            icon_y + icon_size + 2,
            rect.width() - 4,
            _TEXT_HEIGHT,
        )
        painter.setPen(option.palette.text().color())
        align = (
            Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap
        )
        painter.drawText(text_rect, int(align), item.text(0))
        painter.restore()
