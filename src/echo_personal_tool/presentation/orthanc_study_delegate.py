"""Row painting for the server study browser (study cards + series rows).

Qt's stock tree rows render a checkbox, a branch arrow and one line of text per
column.  For a clinical study list that wastes the horizontal space the user
actually scans, so the loader paints its own rows:

* a large, unambiguous checkbox (hit-tested by :class:`CheckableTreeWidget`);
* a rounded thumbnail with a modality badge;
* a multi-line text block with elided titles and dim metadata;
* right-aligned date / size.

Row content is carried by two small row models (:class:`StudyRow`,
:class:`SeriesRow`) stored in ``ROLE_ROW``; the mutable parts (check state,
thumbnail) live in their own roles.  Everything is drawn from the active theme
palette, so dark, light and VS Code themes keep working without new assets.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from echo_personal_tool.domain.models.orthanc import SeriesInfo, StudyInfo
from echo_personal_tool.presentation.dark_theme import get_theme_palette

# ── Item data roles ─────────────────────────────────────────────────
ROLE_ROW = Qt.ItemDataRole.UserRole  # StudyRow | SeriesRow
ROLE_CHECKED = Qt.ItemDataRole.UserRole + 1  # bool
ROLE_PARTIAL = Qt.ItemDataRole.UserRole + 2  # bool (study: only some series picked)
ROLE_PIXMAP = Qt.ItemDataRole.UserRole + 3  # QPixmap (thumbnail)
ROLE_STATE = Qt.ItemDataRole.UserRole + 4  # str — transient status badge
ROLE_SORT_KEY = Qt.ItemDataRole.UserRole + 5  # str — explicit sorting
ROLE_UID = Qt.ItemDataRole.UserRole + 6  # str — study or series UID

# ── Metrics (px) ────────────────────────────────────────────────────
ROW_PADDING_X = 10
ROW_PADDING_Y = 8
CHECKBOX_SIZE = 20
CHECKBOX_GAP = 12
THUMB_RADIUS = 5.0
STUDY_THUMB = QSize(96, 72)
SERIES_THUMB = QSize(76, 57)
STUDY_ROW_HEIGHT = 92
SERIES_ROW_HEIGHT = 74
BADGE_HEIGHT = 18
BADGE_RADIUS = 9.0
BADGE_PADDING_X = 8

_CHECK_COLOR = QColor("#08202c")
_OVERLAY_COLOR = QColor(0, 0, 0, 165)


@dataclass(frozen=True)
class Badge:
    """Small pill label under a study title."""

    text: str
    kind: str = "default"  # default | accent | success | warning | error


@dataclass(frozen=True)
class StudyRow:
    study: StudyInfo
    title: str
    demographics: str = ""
    description: str = ""
    date_text: str = ""
    badges: tuple[Badge, ...] = ()
    thumb_badge: str = ""
    state_text: str = ""
    state_kind: str = "warning"

    def with_state(self, state_text: str, kind: str = "warning") -> StudyRow:
        return replace(self, state_text=state_text, state_kind=kind)


@dataclass(frozen=True)
class SeriesRow:
    series: SeriesInfo
    title: str
    subtitle: str = ""
    size_text: str = ""
    thumb_badge: str = ""
    state_text: str = ""
    state_kind: str = "warning"

    def with_state(self, state_text: str, kind: str = "warning") -> SeriesRow:
        return replace(self, state_text=state_text, state_kind=kind)


def checkbox_rect(row_rect: QRect) -> QRect:
    """Where a row's checkbox lives — used by the list widget for hit testing."""
    size = CHECKBOX_SIZE
    x = row_rect.left() + ROW_PADDING_X
    y = row_rect.top() + (row_rect.height() - size) // 2
    return QRect(x, y, size, size)


def _color(palette: dict[str, str], key: str, fallback: str) -> QColor:
    return QColor(palette.get(key, fallback))


def _dim_font(base: QFont, delta: float, *, bold: bool = False) -> QFont:
    font = QFont(base)
    font.setPointSizeF(max(7.5, base.pointSizeF() - delta))
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return font


class OrthancRowDelegate(QStyledItemDelegate):
    """Paint study / series rows as compact information cards."""

    def __init__(self, parent=None, *, kind: str = "study") -> None:
        super().__init__(parent)
        self._kind = kind
        self.row_height = STUDY_ROW_HEIGHT if kind == "study" else SERIES_ROW_HEIGHT
        self.thumb_size = STUDY_THUMB if kind == "study" else SERIES_THUMB

    # ── geometry ────────────────────────────────────────────────────
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802 (Qt API)
        return QSize(option.rect.width(), self.row_height)

    # ── painting ────────────────────────────────────────────────────
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        palette = get_theme_palette()
        row = index.data(ROLE_ROW)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        self._paint_background(painter, option, rect, palette)

        box = checkbox_rect(rect)
        self._paint_checkbox(painter, box, index, palette)
        thumb_rect = QRect(
            box.right() + CHECKBOX_GAP,
            rect.top() + (rect.height() - self.thumb_size.height()) // 2,
            self.thumb_size.width(),
            self.thumb_size.height(),
        )
        self._paint_thumbnail(painter, thumb_rect, index, palette)
        text_left = thumb_rect.right() + 12
        text_rect = QRect(
            text_left,
            rect.top() + ROW_PADDING_Y,
            max(40, rect.width() - text_left - ROW_PADDING_X),
            rect.height() - 2 * ROW_PADDING_Y,
        )
        if isinstance(row, StudyRow):
            self._paint_study_text(painter, text_rect, row, palette)
        elif isinstance(row, SeriesRow):
            self._paint_series_text(painter, text_rect, row, palette)
        painter.restore()

    # ── pieces ──────────────────────────────────────────────────────
    def _paint_background(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        rect: QRect,
        palette: dict[str, str],
    ) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.fillRect(rect, _color(palette, "bg_button", "#244161"))
            painter.fillRect(
                QRect(rect.left(), rect.top(), 3, rect.height()),
                _color(palette, "accent", "#40e2de"),
            )
        elif hovered:
            painter.fillRect(rect, _color(palette, "bg_panel", "#12273d"))
        else:
            painter.fillRect(rect, _color(palette, "bg_dark", "#101620"))
        painter.setPen(QPen(_color(palette, "border", "#2a4a6b"), 1.0))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

    def _paint_checkbox(
        self,
        painter: QPainter,
        box: QRect,
        index: QModelIndex,
        palette: dict[str, str],
    ) -> None:
        checked = bool(index.data(ROLE_CHECKED))
        partial = bool(index.data(ROLE_PARTIAL))
        accent = _color(palette, "accent", "#40e2de")
        box_rect = QRectF(box).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(box_rect, 5.0, 5.0)
        if checked or partial:
            painter.fillPath(path, accent)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_CHECK_COLOR, 1.0))
            painter.drawPath(path)
            if checked:
                self._paint_check_mark(painter, box_rect)
            else:
                pen = QPen(_CHECK_COLOR, 2.0)
                painter.setPen(pen)
                dash = QRectF(box_rect).adjusted(box_rect.width() * 0.26, 0, -box_rect.width() * 0.26, 0)
                painter.drawLine(QPointF(dash.left(), dash.center().y()), QPointF(dash.right(), dash.center().y()))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_color(palette, "border", "#2a4a6b"), 1.4))
            painter.drawPath(path)

    @staticmethod
    def _paint_check_mark(painter: QPainter, box_rect: QRectF) -> None:
        pen = QPen(_CHECK_COLOR, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        path.moveTo(box_rect.left() + box_rect.width() * 0.24, box_rect.center().y())
        path.lineTo(box_rect.left() + box_rect.width() * 0.44, box_rect.bottom() - box_rect.height() * 0.28)
        path.lineTo(box_rect.right() - box_rect.width() * 0.22, box_rect.top() + box_rect.height() * 0.28)
        painter.drawPath(path)

    def _paint_thumbnail(
        self,
        painter: QPainter,
        rect: QRect,
        index: QModelIndex,
        palette: dict[str, str],
    ) -> None:
        pixmap = index.data(ROLE_PIXMAP)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), THUMB_RADIUS, THUMB_RADIUS)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, QColor("#05070a"))
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            scaled = pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                rect.left() + (rect.width() - scaled.width()) // 2,
                rect.top() + (rect.height() - scaled.height()) // 2,
                scaled,
            )
        else:
            painter.fillRect(rect, _color(palette, "bg_control", "#1a3050"))
            self._paint_placeholder(painter, rect, palette)
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color(palette, "border", "#2a4a6b"), 1.0))
        painter.drawPath(path)

        row = index.data(ROLE_ROW)
        label = getattr(row, "thumb_badge", "")
        if label:
            self._paint_corner_badge(painter, rect, str(label), palette)

    def _paint_placeholder(self, painter: QPainter, rect: QRect, palette: dict[str, str]) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color(palette, "text_dim", "#9bacbb"), 1.3))
        frame = QRectF(rect).adjusted(
            rect.width() * 0.30,
            rect.height() * 0.24,
            -rect.width() * 0.30,
            -rect.height() * 0.24,
        )
        painter.drawRect(frame)

    def _paint_corner_badge(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        palette: dict[str, str],
    ) -> None:
        font = _dim_font(painter.font(), 4.0, bold=True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        width = min(rect.width() - 6, metrics.horizontalAdvance(text) + 10)
        badge = QRectF(rect.left() + 3, rect.bottom() - 18, width, 15)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_OVERLAY_COLOR)
        painter.drawRoundedRect(badge, 3.5, 3.5)
        painter.setPen(_color(palette, "text", "#f1f5f9"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    # ── text blocks ─────────────────────────────────────────────────
    def _paint_study_text(
        self,
        painter: QPainter,
        rect: QRect,
        row: StudyRow,
        palette: dict[str, str],
    ) -> None:
        text_color = _color(palette, "text", "#f1f5f9")
        dim_color = _color(palette, "text_dim", "#9bacbb")

        title_rect = QRect(rect.left(), rect.top(), rect.width(), 22)
        if row.date_text:
            date_font = _dim_font(painter.font(), 0.0, bold=True)
            date_width = QFontMetrics(date_font).horizontalAdvance(row.date_text) + 12
            painter.setFont(date_font)
            painter.setPen(text_color)
            painter.drawText(
                QRect(rect.right() - date_width, rect.top(), date_width, 22),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                row.date_text,
            )
            title_rect.setRight(rect.right() - date_width)

        name_font = _dim_font(painter.font(), -1.0, bold=True)
        painter.setFont(name_font)
        painter.setPen(text_color)
        metrics = QFontMetrics(name_font)
        name = metrics.elidedText(row.title, Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        used = metrics.horizontalAdvance(name)
        if row.demographics:
            info_font = _dim_font(painter.font(), 3.0)
            painter.setFont(info_font)
            painter.setPen(dim_color)
            info_rect = QRect(
                title_rect.left() + used + 10,
                title_rect.top(),
                max(0, title_rect.width() - used - 10),
                22,
            )
            painter.drawText(
                info_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(info_font).elidedText(row.demographics, Qt.TextElideMode.ElideRight, info_rect.width()),
            )

        if row.description:
            desc_font = _dim_font(painter.font(), 1.0)
            painter.setFont(desc_font)
            painter.setPen(dim_color)
            desc_rect = QRect(rect.left(), rect.top() + 23, rect.width(), 17)
            painter.drawText(
                desc_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(desc_font).elidedText(row.description, Qt.TextElideMode.ElideRight, desc_rect.width()),
            )

        badge_font = _dim_font(painter.font(), 3.0, bold=True)
        x = rect.left()
        y = rect.top() + 46
        badges = list(row.badges)
        if row.state_text:
            badges.append(Badge(row.state_text, row.state_kind))
        for badge in badges:
            if not badge.text:
                continue
            width = self._badge_width(painter, badge_font, badge.text)
            if x + width > rect.right() and x > rect.left():
                break
            self._draw_badge(painter, x, y, badge, badge_font, palette)
            x += width + 6

    def _paint_series_text(
        self,
        painter: QPainter,
        rect: QRect,
        row: SeriesRow,
        palette: dict[str, str],
    ) -> None:
        text_color = _color(palette, "text", "#f1f5f9")
        dim_color = _color(palette, "text_dim", "#9bacbb")

        title_rect = QRect(rect.left(), rect.top() + 2, rect.width(), 21)
        if row.size_text:
            size_font = _dim_font(painter.font(), 1.0, bold=True)
            width = QFontMetrics(size_font).horizontalAdvance(row.size_text) + 10
            painter.setFont(size_font)
            painter.setPen(text_color)
            painter.drawText(
                QRect(rect.right() - width, rect.top(), width, 21),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                row.size_text,
            )
            title_rect.setRight(rect.right() - width)

        title_font = _dim_font(painter.font(), 0.5, bold=True)
        painter.setFont(title_font)
        painter.setPen(text_color)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(title_font).elidedText(row.title, Qt.TextElideMode.ElideRight, title_rect.width()),
        )

        subtitle_font = _dim_font(painter.font(), 2.5)
        painter.setFont(subtitle_font)
        painter.setPen(dim_color)
        subtitle_rect = QRect(rect.left(), rect.top() + 26, rect.width(), 16)
        painter.drawText(
            subtitle_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(subtitle_font).elidedText(row.subtitle, Qt.TextElideMode.ElideRight, subtitle_rect.width()),
        )
        if row.state_text:
            badge_font = _dim_font(painter.font(), 3.0, bold=True)
            self._draw_badge(
                painter,
                rect.left(),
                rect.top() + 44,
                Badge(row.state_text, row.state_kind),
                badge_font,
                palette,
            )

    # ── badge helpers ───────────────────────────────────────────────
    @staticmethod
    def _badge_width(painter: QPainter, font: QFont, text: str) -> int:
        painter.setFont(font)
        return QFontMetrics(font).horizontalAdvance(text) + 2 * BADGE_PADDING_X

    @staticmethod
    def _draw_badge(
        painter: QPainter,
        x: int,
        y: int,
        badge: Badge,
        font: QFont,
        palette: dict[str, str],
    ) -> None:
        metrics = QFontMetrics(font)
        rect = QRectF(x, y, metrics.horizontalAdvance(badge.text) + 2 * BADGE_PADDING_X, BADGE_HEIGHT)
        if badge.kind == "accent":
            fg, bg = QColor("#062026"), _color(palette, "accent", "#40e2de")
        elif badge.kind == "success":
            fg, bg = QColor("#03261a"), _color(palette, "success", "#34d399")
        elif badge.kind in {"warning", "error"}:
            key = "warning" if badge.kind == "warning" else "error"
            fallback = "#fb923c" if badge.kind == "warning" else "#f87171"
            fg, bg = QColor("#2a1602"), _color(palette, key, fallback)
        else:
            fg = _color(palette, "text_dim", "#9bacbb")
            bg = _color(palette, "bg_control", "#1a3050")
        painter.setFont(font)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, BADGE_RADIUS, BADGE_RADIUS)
        painter.setPen(fg)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, badge.text)
