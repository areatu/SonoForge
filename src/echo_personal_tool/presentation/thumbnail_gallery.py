"""Clinical-style thumbnail gallery: grouped grid or one-row filmstrip.

The vertical gallery carries a two-row header above the list — the title with
its clip count, the grid/list view toggle and the mode filter chips of the
ui-redesign mockup (``docs/images/ui-redesign/01-main-classic.png``).  The
header lives in the top viewport margin so the widget itself stays the
``QListWidget`` its callers know.
"""

from __future__ import annotations

import inspect
import re
import shutil
from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
)

from echo_personal_tool.application.thumbnail_scheduler import ThumbnailPriority
from echo_personal_tool.domain.models import InstanceMetadata, StudyMetadata
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.keyboard_shortcuts import shortcut_label
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.theme.contrast import contrast_ratio
from echo_personal_tool.presentation.theme.tokens import GALLERY_GROUP_TOKENS
from echo_personal_tool.presentation.thumbnail_gallery_groups import (
    MODE_GROUP_ORDER,
    canonical_clip_mode,
    ordered_thumbnail_instances,
)

_ITEM_ROLE = Qt.ItemDataRole.UserRole
_GROUP_MARKER_ROLE = Qt.ItemDataRole.UserRole + 2
_GROUP_COLOR_ROLE = Qt.ItemDataRole.UserRole + 3
_MODE_HEADER_ROLE = Qt.ItemDataRole.UserRole + 4
_MODE_COUNT_ROLE = Qt.ItemDataRole.UserRole + 5
_VISIBLE_PADDING = 8
_SCROLL_DEBOUNCE_MS = 25
_THUMBNAIL_PIXMAP_MAX = 200

# Group outline stays thin so the selection ring (outer cell edge) reads as the
# current file. Widths are constants so tests can lock the visual contract.
GROUP_BORDER_WIDTH = 1
#: The mockup draws the selection with a 2 px accent ring (``thumb()``).
SELECTION_BORDER_WIDTH = 2

_HORIZONTAL_GALLERY_MIN_HEIGHT = 128
_HORIZONTAL_GALLERY_VERTICAL_PADDING = 4
_MODE_HEADER_HEIGHT = 18
_MODE_GROUP_ORDER = MODE_GROUP_ORDER
_MODE_LABEL_KEYS = {
    "2d": "gallery.mode.2d",
    "doppler": "gallery.mode.doppler",
    "m_mode": "gallery.mode.mmode",
}
#: Two-row header of the vertical gallery: title row + filter-chip row.
_HEADER_TITLE_HEIGHT = 34
_HEADER_FILTER_HEIGHT = 34
_HEADER_HEIGHT = _HEADER_TITLE_HEIGHT + _HEADER_FILTER_HEIGHT
#: Height of the bottom scrim that carries the thumbnail caption.
_CAPTION_HEIGHT = 20
#: Fine-grained Doppler badge of a thumbnail (word-bounded, as in the mapper).
_MODE_BADGE_RE = re.compile(r"(?<![a-z0-9])(pw|cw|tdi)(?![a-z0-9])")
_CDK_MARKERS = ("цдк", "цвет", "color flow", "colorflow", "cfm")
_MAX_WIDGET_SIZE = 16777215


def _group_marker(index: int) -> str:
    """Return spreadsheet-style group labels: A…Z, AA, AB, and so on."""
    if index < 0:
        raise ValueError("Group index must be non-negative")
    marker = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        marker = chr(ord("A") + remainder) + marker
    return marker


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
            height = widget.cell_height() + (_MODE_HEADER_HEIGHT if widget._horizontal_mode else 0)
            return QSize(widget.cell_width(), height)
        return QSize(108, 84)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        instance = index.data(_ITEM_ROLE)
        if not isinstance(instance, InstanceMetadata):
            super().paint(painter, option, index)
            return

        list_widget = option.widget
        tokens = list_widget._theme_tokens if isinstance(list_widget, ThumbnailGalleryWidget) else get_theme_tokens()
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        rect = option.rect
        painter.fillRect(rect, QColor_from(tokens["surface.0"]))
        # Selection sits on the outer cell edge so it does not merge with the
        # 1 px group outline drawn later on the thumbnail itself.
        if option.state & QStyle.StateFlag.State_Selected:
            selection_pen = QPen(QColor_from(tokens["accent.text"]), SELECTION_BORDER_WIDTH)
            selection_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            # Cosmetic: the ring keeps its 3 px at any device pixel ratio instead
            # of being scaled into a half-transparent halo on 125/150 % screens.
            selection_pen.setCosmetic(True)
            painter.setPen(selection_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = SELECTION_BORDER_WIDTH // 2
            painter.drawRoundedRect(rect.adjusted(inset, inset, -(inset + 1), -(inset + 1)), 5, 5)

        horizontal_mode = isinstance(list_widget, ThumbnailGalleryWidget) and list_widget._horizontal_mode
        header_height = _MODE_HEADER_HEIGHT if horizontal_mode else 0
        thumb_rect = rect.adjusted(4, 4 + header_height, -4, -4)
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
            painter.setPen(QColor_from(tokens["line.1"]))
            painter.drawRoundedRect(thumb_rect, 4, 4)

        if horizontal_mode:
            header_mode = index.data(_MODE_HEADER_ROLE)
            label_key = _MODE_LABEL_KEYS.get(str(header_mode)) if header_mode else None
            if label_key is not None:
                count = int(index.data(_MODE_COUNT_ROLE) or 0)
                header_text = f"{tr(label_key)} · {count}" if count else tr(label_key)
                header_rect = QRect(rect.left() + 4, rect.top(), max(0, rect.width() - 8), _MODE_HEADER_HEIGHT)
                header_font = painter.font()
                header_font.setBold(True)
                header_font.setPointSize(8)
                painter.setFont(header_font)
                painter.setPen(QColor_from(tokens["text.2"]))
                painter.drawText(
                    header_rect,
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    header_text,
                )
                painter.setPen(QPen(QColor_from(tokens["line.1"]), 1))
                painter.drawLine(
                    header_rect.left(),
                    header_rect.bottom() - 1,
                    header_rect.right(),
                    header_rect.bottom() - 1,
                )

        group_marker = index.data(_GROUP_MARKER_ROLE)
        group_color_token = index.data(_GROUP_COLOR_ROLE)
        group_color_text = tokens.get(str(group_color_token)) if group_marker and group_color_token else None
        if group_marker and group_color_text:
            group_color = QColor_from(group_color_text)
            group_pen = QPen(group_color, GROUP_BORDER_WIDTH)
            group_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            # A 1 px frame is the only marker of a study group (HELP §…): drawn
            # through the logical transform it can wash out to a few percent of
            # alpha at a fractional DPR and read as «рамки нет». Cosmetic keeps
            # it one solid device pixel on every screen.
            group_pen.setCosmetic(True)
            painter.setPen(group_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(thumb_rect.adjusted(0, 0, -1, -1), 4, 4)

            marker = str(group_marker)
            badge_font = painter.font()
            badge_font.setBold(True)
            badge_font.setPointSize(8)
            painter.setFont(badge_font)
            badge_width = max(16, painter.fontMetrics().horizontalAdvance(marker) + 8)
            badge_height = max(15, painter.fontMetrics().height())
            badge_rect = QRect(
                thumb_rect.right() - badge_width + 1,
                thumb_rect.top() + 2,
                badge_width,
                badge_height,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(group_color)
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.setPen(QColor_from(_contrast_text_color(group_color, tokens)))
            painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), marker)

        # Mode badge top-left, then the cine / DICOM marks beside it (the
        # bottom of the thumbnail belongs to the caption of the mockup).
        badge_text, badge_token = mode_badge(instance)
        badge_color = QColor_from(tokens[badge_token])
        badge_font = painter.font()
        badge_font.setBold(True)
        badge_font.setPointSize(8)
        painter.setFont(badge_font)
        badge_width = max(18, painter.fontMetrics().horizontalAdvance(badge_text) + 8)
        badge_height = max(14, painter.fontMetrics().height() + 3)
        badge_rect = QRect(thumb_rect.left() + 4, thumb_rect.top() + 4, badge_width, badge_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 158))
        painter.drawRoundedRect(badge_rect, 3.5, 3.5)
        outline = QPen(QColor_from(tokens[badge_token]), 1)
        outline.setCosmetic(True)
        painter.setPen(outline)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(badge_rect, 3.5, 3.5)
        painter.setPen(badge_color)
        painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), badge_text)

        mark_x = badge_rect.right() + 4
        mark_font = painter.font()
        is_cine = instance.number_of_frames > 1
        if is_cine:
            painter.setPen(QColor_from(tokens["gallery.cine"]))
            mark_font.setPointSize(8)
            painter.setFont(mark_font)
            painter.drawText(
                QRect(mark_x, thumb_rect.top() + 4, 14, badge_height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                "▶",
            )
            mark_x += 14
        if _has_dicom_tags(instance):
            painter.setPen(QColor_from(tokens["gallery.dicom"]))
            mark_font.setBold(True)
            mark_font.setPointSize(9)
            painter.setFont(mark_font)
            painter.drawText(
                QRect(mark_x, thumb_rect.top() + 4, 14, badge_height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                "D",
            )

        # Caption inside the bottom of the thumbnail: scrim + label + duration.
        caption = str(instance.series_description or "").strip()
        duration = frames_caption(instance)
        if caption or duration:
            painter.save()
            painter.setClipRect(thumb_rect)
            scrim = QLinearGradient(
                QPointF(thumb_rect.left(), thumb_rect.bottom() - _CAPTION_HEIGHT),
                QPointF(thumb_rect.left(), thumb_rect.bottom()),
            )
            scrim.setColorAt(0.0, QColor(0, 0, 0, 0))
            scrim.setColorAt(1.0, QColor(0, 0, 0, 217))
            painter.fillRect(
                QRect(thumb_rect.left(), thumb_rect.bottom() - _CAPTION_HEIGHT, thumb_rect.width(), _CAPTION_HEIGHT),
                scrim,
            )
            caption_font = painter.font()
            caption_font.setBold(True)
            caption_font.setPointSize(9)
            painter.setFont(caption_font)
            metrics = painter.fontMetrics()
            duration_width = metrics.horizontalAdvance(duration) + 4 if duration else 0
            label_rect = QRect(
                thumb_rect.left() + 6,
                thumb_rect.bottom() - _CAPTION_HEIGHT,
                max(0, thumb_rect.width() - 12 - duration_width),
                _CAPTION_HEIGHT,
            )
            # The scrim is black in every theme, so the caption uses the fixed
            # light gallery ink rather than the theme's primary text.
            painter.setPen(QColor_from(tokens["gallery.group.text.light"]))
            painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), caption)
            if duration:
                painter.setFont(caption_font)
                duration_rect = QRect(
                    thumb_rect.right() - 6 - duration_width,
                    thumb_rect.bottom() - _CAPTION_HEIGHT,
                    duration_width,
                    _CAPTION_HEIGHT,
                )
                duration_color = QColor_from(tokens["gallery.group.text.light"])
                duration_color.setAlpha(165)
                painter.setPen(duration_color)
                painter.drawText(
                    duration_rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), duration
                )
            painter.restore()

        painter.restore()


def QColor_from(hex_color: str) -> QColor:  # noqa: N802
    return QColor(hex_color)


def _contrast_text_color(color: QColor, tokens: dict[str, str] | None = None) -> str:
    """Pick the gallery's dark or light group-label token with better contrast."""
    palette = tokens if tokens is not None else get_theme_tokens()
    fill = color.name(QColor.NameFormat.HexRgb)
    dark = palette["gallery.group.text.dark"]
    light = palette["gallery.group.text.light"]
    return dark if contrast_ratio(dark, fill) >= contrast_ratio(light, fill) else light


def _has_dicom_tags(instance: InstanceMetadata) -> bool:
    if instance.media_format != "dicom":
        return False
    return instance.pixel_spacing is not None or instance.frame_time_ms is not None


def mode_badge(instance: InstanceMetadata) -> tuple[str, str]:
    """Return ``(short label, gallery.mode token)`` of a thumbnail badge.

    Fine labels (PW/TDI/CW/ЦДК) come from the series description when it says
    so; otherwise the badge shows the coarse acquisition group of the gallery.
    """
    if instance.clip_mode == "m_mode":
        return tr("gallery.badge.mmode"), "gallery.mode.mmode"
    if instance.clip_mode == "doppler":
        description = instance.series_description.casefold()
        match = _MODE_BADGE_RE.search(description)
        if match is not None:
            kind = match.group(1)
            return tr(f"gallery.badge.{kind}"), f"gallery.mode.{kind}"
        if any(marker in description for marker in _CDK_MARKERS):
            return tr("gallery.badge.cdk"), "gallery.mode.cdk"
        return tr("gallery.badge.doppler"), "gallery.mode.doppler"
    return tr("gallery.badge.2d"), "gallery.mode.2d"


def frames_caption(instance: InstanceMetadata) -> str:
    """Caption under the thumbnail: frame count or clip duration («83 к.», «4,1 с»)."""
    from echo_personal_tool.infrastructure.i18n import get_language

    if instance.number_of_frames > 1:
        return tr("gallery.caption_frames", count=instance.number_of_frames)
    if instance.frame_time_ms:
        seconds = instance.frame_time_ms * max(1, instance.number_of_frames) / 1000.0
        value = f"{seconds:.1f}"
        if get_language() == "ru":
            value = value.replace(".", ",")
        return tr("gallery.caption_seconds", value=value)
    return ""


def _gallery_width(cell_w: int, columns: int = _COLUMN_COUNT) -> int:
    return columns * cell_w + max(0, columns - 1) * _CELL_SPACING + _SCROLLBAR_GUTTER


class ThumbnailGalleryWidget(QListWidget):
    """Grouped thumbnail grid or a single-row horizontally scrolling filmstrip."""

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
        self._compact_horizontal_mode = False
        self._theme_tokens = get_theme_tokens()
        self._thumb_w, self._thumb_h = _THUMBNAIL_SCALES["medium"]["thumb"]
        self._cell_w, self._cell_h = _THUMBNAIL_SCALES["medium"]["cell"]
        self._view_mode = "grid"
        self._mode_filter = "all"
        self._mode_counts: dict[str, int] = {}
        self._total_count = 0
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
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_value_changed)
        self.horizontalScrollBar().valueChanged.connect(self._on_scroll_bar_value_changed)

        self._mv_start_hint = QLabel(self.viewport())
        self._mv_start_hint.setObjectName("multiviewStartHint")
        self._mv_start_hint.setWordWrap(True)
        self._mv_start_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._build_header()

        self._apply_theme_tokens()
        self._mv_start_hint.hide()
        self._position_header()

    # ── Header: title, view toggle, mode filter chips ─────────────

    def _build_header(self) -> None:
        """Assemble the two-row header that sits in the top viewport margin."""
        self._header = QWidget(self)
        self._header.setObjectName("galleryHeader")

        self._title = QLabel(self._header)
        self._title.setObjectName("galleryTitle")
        self._count_badge = QLabel(self._header)
        self._count_badge.setObjectName("galleryCountBadge")
        self._grid_btn = QToolButton(self._header)
        self._grid_btn.setObjectName("galleryGridButton")
        self._grid_btn.setText("▦")
        self._grid_btn.setCheckable(True)
        self._grid_btn.setChecked(True)
        self._grid_btn.setToolTip(tr("gallery.view_grid"))
        self._grid_btn.setAccessibleName(tr("gallery.view_grid"))
        self._list_btn = QToolButton(self._header)
        self._list_btn.setObjectName("galleryListButton")
        self._list_btn.setText("☰")
        self._list_btn.setCheckable(True)
        self._list_btn.setToolTip(tr("gallery.view_list"))
        self._list_btn.setAccessibleName(tr("gallery.view_list"))
        self._grid_btn.clicked.connect(self._on_grid_clicked)
        self._list_btn.clicked.connect(self._on_list_clicked)

        self._filter_bar = QFrame(self._header)
        self._filter_bar.setObjectName("galleryFilterBar")
        self._filter_buttons: dict[str, QToolButton] = {}
        for key, label_key in (
            ("all", "gallery.filter_all"),
            ("2d", "gallery.filter_2d"),
            ("doppler", "gallery.filter_doppler"),
            ("m_mode", "gallery.filter_mmode"),
        ):
            button = QToolButton(self._filter_bar)
            button.setObjectName("galleryFilterButton")
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            # The mode lives on the widget: a single bound-method connection
            # keeps the gallery collectible (a lambda closure would pin the
            # widget from the child's C++ signal, which Python GC cannot see).
            button.setProperty("mode", key)
            button.clicked.connect(self._on_filter_clicked)
            self._filter_buttons[key] = button
        self._filter_buttons["all"].setChecked(True)

        self._header.hide()

    def _on_grid_clicked(self, _checked: bool = False) -> None:
        self.set_view_mode("grid")

    def _on_list_clicked(self, _checked: bool = False) -> None:
        self.set_view_mode("list")

    def _on_filter_clicked(self, _checked: bool = False) -> None:
        sender = self.sender()
        mode = sender.property("mode") if sender is not None else None
        if isinstance(mode, str) and mode:
            self.set_mode_filter(mode)

    def _header_height(self) -> int:
        """Height of the header overlay for the current view mode.

        The mode chips belong to the grid view only: the one-column list drops
        the second row together with its viewport margin instead of reserving
        an empty band above the thumbnails.
        """
        if self._horizontal_mode or self._view_mode == "list":
            return _HEADER_TITLE_HEIGHT
        return _HEADER_HEIGHT

    def _position_header(self) -> None:
        """Place the header rows over the top viewport margin (vertical mode)."""
        if not hasattr(self, "_header"):
            return
        show_header = not self._horizontal_mode
        self._header.setVisible(show_header)
        if not show_header:
            return
        show_filters = self._view_mode == "grid"
        self._filter_bar.setVisible(show_filters)
        width = max(self.width(), 120)
        self._header.setGeometry(0, 0, width, self._header_height())
        margin = 12
        title_y = 6
        button_size = 26
        gap = 8
        self._title.move(margin, title_y)
        list_x = width - margin - button_size
        grid_x = width - margin - 2 * button_size - 4
        self._list_btn.setGeometry(list_x, title_y, button_size, button_size)
        self._grid_btn.setGeometry(grid_x, title_y, button_size, button_size)
        # The count sits after the title but never under the view buttons: the
        # one-column list narrows the panel until a fixed offset pushed the
        # badge onto the grid toggle (2026-10-25).  Keep an 8 px gap and drop
        # the badge only when even that does not fit.
        if self._total_count > 0:
            badge_x = min(margin + self._title.width() + gap, grid_x - gap - self._count_badge.width())
            self._count_badge.setVisible(badge_x >= margin + self._title.width())
            self._count_badge.move(max(badge_x, margin), title_y)
        if show_filters:
            filter_y = _HEADER_TITLE_HEIGHT + 2
            self._filter_bar.setGeometry(margin, filter_y, width - 2 * margin, _HEADER_FILTER_HEIGHT - 6)
            filter_width = self._filter_bar.width()
            keys = list(self._filter_buttons)
            segment_width = max(40, filter_width // len(keys))
            for index, key in enumerate(keys):
                button = self._filter_buttons[key]
                button.setGeometry(index * segment_width, 1, segment_width - 1, self._filter_bar.height() - 2)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if hasattr(self, "_header"):
            self._position_header()
        if self._mv_start_hint.isVisible():
            self._position_start_hint()

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

    def _sync_horizontal_gallery_height(self) -> None:
        if self._horizontal_mode:
            row_height = self._cell_h + _MODE_HEADER_HEIGHT + _CELL_SPACING
            scrollbar_height = self.horizontalScrollBar().sizeHint().height()
            frame_height = 2 * self.frameWidth()
            content_height = row_height + 2 * _HORIZONTAL_GALLERY_VERTICAL_PADDING + scrollbar_height + frame_height
            self.setFixedHeight(max(_HORIZONTAL_GALLERY_MIN_HEIGHT, content_height))

    def _horizontal_side_panel_width(self) -> int:
        """Fit one complete thumbnail in the compact right-side filmstrip."""
        return self._cell_w + 2 * self.spacing() + 2 * self.frameWidth()

    def _apply_theme_tokens(self) -> None:
        """Refresh the gallery's theme roles, including the Multiview hint."""
        self._theme_tokens = get_theme_tokens()
        tokens = self._theme_tokens
        self._mv_start_hint.setStyleSheet(
            f"QLabel {{ background-color: {tokens['surface.1']}; "
            f"color: {tokens['accent.text']}; "
            f"border: 1px solid {tokens['line.1']}; border-radius: 6px; "
            "padding: 6px 10px; }"
        )
        self._header.setStyleSheet(
            f"#galleryHeader {{ background: {tokens['surface.1']}; }}"
            f"#galleryTitle {{ color: {tokens['text.1']}; font-weight: 600; font-size: 13px; }}"
            f"#galleryCountBadge {{ color: {tokens['text.2']}; background: {tokens['surface.3']}; "
            "border-radius: 9px; padding: 1px 8px; font-size: 10.5px; font-weight: 600; }"
            f"#galleryGridButton, #galleryListButton {{ background: transparent; border: 1px solid transparent; "
            "border-radius: 5px; min-width: 22px; min-height: 22px; padding: 0; font-size: 13px; "
            f"color: {tokens['text.3']}; }}"
            f"#galleryGridButton:hover, #galleryListButton:hover {{ background: {tokens['surface.hover']}; }}"
            f"#galleryGridButton:checked, #galleryListButton:checked {{"
            f" background: {tokens['accent.tint']}; border-color: {tokens['accent.line']};"
            f" color: {tokens['accent.text']}; }}"
            f"#galleryFilterBar {{ background: {tokens['surface.2']}; border: 1px solid {tokens['line.1']};"
            " border-radius: 6px; }"
            f"#galleryFilterBar #galleryFilterButton {{ background: transparent; border: none;"
            f" border-radius: 5px; color: {tokens['text.2']}; font-size: 11px; font-weight: 500; padding: 0; }}"
            f"#galleryFilterBar #galleryFilterButton:hover {{ background: {tokens['surface.hover']}; color: {tokens['text.1']}; }}"
            f"#galleryFilterBar #galleryFilterButton:checked {{ background: {tokens['surface.3']};"
            f" border: 1px solid {tokens['line.2']}; color: {tokens['text.1']}; font-weight: 600; }}"
        )
        self.viewport().update()

    def reload_text(self) -> None:
        """Refresh the theme tokens, the header labels and the Multiview hint."""
        self._apply_theme_tokens()
        self.set_multiview_enabled(self._multiview_enabled)
        self._refresh_header_text()

    def _refresh_header_text(self) -> None:
        """Localized title, count badge, view toggles and filter chips."""
        self._title.setText(tr("gallery.title"))
        self._count_badge.setText(str(self._total_count))
        self._count_badge.setVisible(self._total_count > 0)
        for widget, key in ((self._grid_btn, "gallery.view_grid"), (self._list_btn, "gallery.view_list")):
            widget.setToolTip(tr(key))
            widget.setAccessibleName(tr(key))
        counts = self._mode_counts
        labels = {
            "all": tr("gallery.filter_all"),
            "2d": tr("gallery.filter_2d"),
            "doppler": tr("gallery.filter_doppler"),
            "m_mode": tr("gallery.filter_mmode"),
        }
        for mode, button in self._filter_buttons.items():
            count = self._total_count if mode == "all" else counts.get(mode, 0)
            button.setText(f"{labels[mode]} {count}" if count else labels[mode])
        # Size the labels before placing them: the badge offset depends on the
        # title width, and the old order positioned with the previous text's
        # extents on the first refresh after a count change.
        self._title.adjustSize()
        self._count_badge.adjustSize()
        self._position_header()

    def set_multiview_enabled(self, enabled: bool) -> None:
        """Show the "open in pane" actions and the Ctrl+click hint."""
        self._multiview_enabled = bool(enabled)
        self.setToolTip(
            tr(
                "multiview.gallery.ctrl_hint",
                shortcut=shortcut_label("multiview_ctrl_click"),
            )
            if self._multiview_enabled
            else ""
        )

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

    def set_view_mode(self, mode: str) -> None:
        """Switch the vertical gallery between the 2-column grid and one-column list."""
        normalized = mode if mode in ("grid", "list") else "grid"
        if normalized == self._view_mode:
            self._sync_view_buttons()
            return
        self._view_mode = normalized
        self._sync_view_buttons()
        if not self._horizontal_mode:
            self._apply_gallery_metrics()
            self.viewport().update()

    def set_mode_filter(self, mode: str) -> None:
        """Show only one acquisition group («Все» shows everything)."""
        normalized = mode if mode in ("all", *_MODE_GROUP_ORDER) else "all"
        if normalized == self._mode_filter:
            self._sync_filter_buttons()
            return
        self._mode_filter = normalized
        self._sync_filter_buttons()
        if self._studies:
            self.populate(self._studies)

    def _sync_view_buttons(self) -> None:
        if hasattr(self, "_grid_btn"):
            self._grid_btn.setChecked(self._view_mode == "grid")
            self._list_btn.setChecked(self._view_mode == "list")

    def _sync_filter_buttons(self) -> None:
        if not hasattr(self, "_filter_buttons"):
            return
        for mode, button in self._filter_buttons.items():
            button.blockSignals(True)
            button.setChecked(mode == self._mode_filter)
            button.blockSignals(False)

    def _column_count(self) -> int:
        if not self._horizontal_mode and self._view_mode == "list":
            return 1
        return _COLUMN_COUNT

    def apply_scale(self, scale: str) -> None:
        spec = _THUMBNAIL_SCALES.get(scale, _THUMBNAIL_SCALES["medium"])
        self._thumb_w, self._thumb_h = spec["thumb"]
        self._cell_w, self._cell_h = spec["cell"]
        self._apply_gallery_metrics()
        self._sync_horizontal_gallery_height()
        self.viewport().update()

    def set_horizontal_mode(self, enabled: bool, *, compact_side_panel: bool = False) -> None:
        """Use a one-row filmstrip, optionally constrained to one side-panel tile.

        The bottom filmstrip expands across the window. A gallery in the right
        side slot stays one thumbnail wide, so it scrolls horizontally instead
        of reserving the width of a two-column grid.
        """
        enabled = bool(enabled)
        compact_side_panel = bool(enabled and compact_side_panel)
        if enabled and not self._horizontal_mode:
            self._saved_width = self.width()

        self._horizontal_mode = enabled
        self._compact_horizontal_mode = compact_side_panel
        if enabled:
            self.setMinimumWidth(0)
            self.setMaximumWidth(_MAX_WIDGET_SIZE)
            self.setMinimumHeight(0)
            self.setMaximumHeight(_MAX_WIDGET_SIZE)
            self.setWrapping(False)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            horizontal_policy = QSizePolicy.Policy.Fixed if compact_side_panel else QSizePolicy.Policy.Expanding
            self.setSizePolicy(horizontal_policy, QSizePolicy.Policy.Fixed)
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(_MAX_WIDGET_SIZE)
            self.setMinimumHeight(0)
            self.setMaximumHeight(_MAX_WIDGET_SIZE)
            self.setWrapping(True)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self._apply_gallery_metrics()
        self._sync_horizontal_gallery_height()
        self._position_header()
        self.viewport().update()

    def wheelEvent(self, event) -> None:
        if not self._horizontal_mode:
            super().wheelEvent(event)
            return

        pixels = event.pixelDelta()
        angles = event.angleDelta()
        if pixels.x():
            delta = pixels.x()
        elif angles.x():
            delta = angles.x()
        elif pixels.y():
            delta = -pixels.y()
        else:
            delta = -angles.y()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() + delta)
        event.accept()

    def _apply_gallery_metrics(self) -> None:
        item_height = self._cell_h + (_MODE_HEADER_HEIGHT if self._horizontal_mode else 0)
        grid_height = item_height + (_CELL_SPACING if self._horizontal_mode else 0)
        self.setGridSize(QSize(self._cell_w, grid_height))
        self.setIconSize(QSize(self._thumb_w, self._thumb_h))
        if self._horizontal_mode:
            self.setMinimumWidth(0)
            self.setMaximumWidth(_MAX_WIDGET_SIZE)
            if self._compact_horizontal_mode:
                self.setFixedWidth(self._horizontal_side_panel_width())
            self.setViewportMargins(0, 0, 0, 0)
        else:
            self.setFixedWidth(_gallery_width(self._cell_w, self._column_count()))
            self.setViewportMargins(0, self._header_height(), 0, 0)
        for row in range(self.count()):
            item = self.item(row)
            if item is not None:
                item.setSizeHint(QSize(self._cell_w, item_height))
        self._position_header()

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

        ordered = ordered_thumbnail_instances(studies, self._sort_mode)
        self._mode_counts = {}
        for instance, _ in ordered:
            mode = canonical_clip_mode(instance.clip_mode)
            self._mode_counts[mode] = self._mode_counts.get(mode, 0) + 1
        self._total_count = len(ordered)
        visible = [
            (instance, study_index)
            for instance, study_index in ordered
            if self._mode_filter == "all" or canonical_clip_mode(instance.clip_mode) == self._mode_filter
        ]
        has_multiple_studies = len({study_index for _, study_index in visible}) > 1

        item_height = self._cell_h + (_MODE_HEADER_HEIGHT if self._horizontal_mode else 0)
        for display_index, (instance, study_index) in enumerate(visible, 1):
            self._instances.append(instance)
            item = QListWidgetItem()
            item.setData(_ITEM_ROLE, instance)
            item.setData(Qt.ItemDataRole.UserRole + 1, display_index)
            item.setData(_GROUP_MARKER_ROLE, _group_marker(study_index) if has_multiple_studies else None)
            item.setData(
                _GROUP_COLOR_ROLE,
                GALLERY_GROUP_TOKENS[study_index % len(GALLERY_GROUP_TOKENS)] if has_multiple_studies else None,
            )
            item.setSizeHint(QSize(self._cell_w, item_height))
            self.addItem(item)
            self._items_by_uid[instance.sop_instance_uid] = item

        self._building = False
        if self._horizontal_mode:
            self.setViewportMargins(0, 0, 0, 0)
        else:
            self.setViewportMargins(0, self._header_height(), 0, 0)
        self._refresh_header_text()
        self._sync_view_buttons()
        self._sync_filter_buttons()
        self._sync_horizontal_gallery_height()
        QTimer.singleShot(0, self._after_populate)

    def _after_populate(self) -> None:
        self.request_visible_previews()
        self._enqueue_background_previews()

    def _on_scroll_bar_value_changed(self, _value: int) -> None:
        self._scroll_timer.start()

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
            padding = _VISIBLE_PADDING * 4
            padded = (
                rect.adjusted(-padding, 0, padding, 0)
                if self._horizontal_mode
                else rect.adjusted(0, -padding, 0, padding)
            )
            if not viewport.rect().intersects(padded):
                continue
            instance = item.data(_ITEM_ROLE)
            if isinstance(instance, InstanceMetadata):
                uids.add(instance.sop_instance_uid)
        return uids
