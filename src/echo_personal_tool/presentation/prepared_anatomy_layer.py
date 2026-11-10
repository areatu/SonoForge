"""Visual-only anatomy overlay shared by Full and Presenter viewers.

Scene items are deliberately NOT Contour objects and cannot flow into the
measurement session, persistence, calculators, or report. A missing annotated
frame is blank: no temporal guess or extrapolation is made.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsSimpleTextItem, QLabel

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.prepared_anatomy import STRUCTURES, Annotation
from echo_personal_tool.presentation.theme.palettes import (
    TEACHING_BADGE_BORDER,
    TEACHING_BADGE_TEXT,
    TEACHING_LABEL_OUTLINE,
    TEACHING_STRUCTURE_COLORS,
)

DEFAULT_COLORS = TEACHING_STRUCTURE_COLORS


class PreparedAnatomyLayer:
    def __init__(self, viewer: Any) -> None:
        self._viewer = viewer
        self._items: list[QGraphicsPathItem | QGraphicsSimpleTextItem] = []
        self._disposed = False
        self.annotation: Annotation | None = None
        self.enabled = True
        self.labels = True
        self.line_width = 3
        self.fill_alpha = 65
        self.visible = set(STRUCTURES)
        self.colors = dict(DEFAULT_COLORS)
        self._badge = QLabel(viewer)
        self._badge.setObjectName("teachingAnatomyBadge")
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._badge.setStyleSheet(
            f"QLabel {{ background: rgba(9,18,31,225); color: {TEACHING_BADGE_TEXT}; "
            f"border: 1px solid {TEACHING_BADGE_BORDER}; border-radius: 7px; "
            "font-size: 14px; padding: 7px 10px; }"
        )
        self._badge.hide()

    def clear(self) -> None:
        if self._disposed:
            return
        for item in self._items:
            self._viewer._view.removeItem(item)
        self._items.clear()
        self._badge.hide()

    def render(self, frame_index: int, image_size: tuple[int, int] | None) -> None:
        if self._disposed:
            return
        self.clear()
        annotation = self.annotation
        if not self.enabled or annotation is None or image_size != (annotation.height, annotation.width):
            return
        rendered: list[str] = []
        for shape in annotation.frames.get(frame_index, ()):
            if shape.structure not in self.visible:
                continue
            rendered.append(shape.structure)
            color = QColor(self.colors[shape.structure])
            path = QPainterPath()
            x, y = shape.points[0]
            path.moveTo(x * (annotation.width - 1), y * (annotation.height - 1))
            for x, y in shape.points[1:]:
                path.lineTo(x * (annotation.width - 1), y * (annotation.height - 1))
            path.closeSubpath()
            item = QGraphicsPathItem(path)
            pen = QPen(color)
            pen.setWidth(self.line_width)
            pen.setCosmetic(True)  # same projected width regardless of zoom
            item.setPen(pen)
            fill = QColor(color)
            fill.setAlpha(self.fill_alpha)
            item.setBrush(fill if self.fill_alpha else Qt.BrushStyle.NoBrush)
            item.setZValue(60)
            self._viewer._view.addItem(item)
            self._items.append(item)
            if self.labels:
                label = QGraphicsSimpleTextItem(tr(f"teaching_anatomy.structure.{shape.structure}"))
                label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                font = label.font()
                font.setBold(True)
                font.setPointSize(13)
                label.setFont(font)
                outline = QPen(QColor(TEACHING_LABEL_OUTLINE))
                outline.setWidth(3)
                label.setPen(outline)
                label.setBrush(color)
                label.setPos(
                    sum(px for px, _ in shape.points) / len(shape.points) * (annotation.width - 1),
                    sum(py for _, py in shape.points) / len(shape.points) * (annotation.height - 1),
                )
                label.setZValue(61)
                self._viewer._view.addItem(label)
                self._items.append(label)
        view = tr(f"teaching_anatomy.view.{annotation.view.lower()}")
        position = tr(f"teaching_anatomy.position.{annotation.position}")
        message = tr("teaching_anatomy.badge", view=view, position=position, frame=frame_index + 1)
        if frame_index not in annotation.frames:
            message += "\n" + tr("teaching_anatomy.unmarked")
        elif rendered:
            message += "\n" + " · ".join(tr(f"teaching_anatomy.structure.{s}") for s in rendered)
        self._badge.setText(message)
        self._badge.adjustSize()
        self._badge.move(self._viewer._graphics.x() + 12, self._viewer._graphics.y() + 12)
        self._badge.show()
        self._badge.raise_()

    def dispose(self) -> None:
        if self._disposed:
            return
        self.clear()
        self._disposed = True
        self._badge.deleteLater()
