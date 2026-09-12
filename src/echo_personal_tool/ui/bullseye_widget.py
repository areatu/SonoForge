"""Standard 18-segment AHA bull's-eye with colour-coded strain values."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.ui.strain_helpers import (
    PALETTES,
    STRAIN_RAMP,
    DEFORMATION_PLUS_RAMP,
    RAINBOW_RAMP,
    MONOCHROME_RAMP,
)


class BullseyeWidget(QWidget):
    """Standard 18-segment AHA bull's-eye with colour-coded strain values.

    Geometry follows the standard AHA layout (issue #C11): the anterior wall is
    centred on 12 o'clock and each ring is drawn clockwise from it, so the
    segment ids the worker assigns appear at their anatomical positions:

    * basal 1, 6, 5, 4, 3, 2 — anterior, anterolateral, inferolateral,
      inferior, inferoseptal, anteroseptal;
    * mid 7, 12, 11, 10, 9, 8;
    * apical 13, 18, 17, 16, 15, 14.

    The 18-segment model has no separate apex segment, so the centre cap is
    drawn as an unlabelled "not measured" region instead of inventing a value
    for it (the old map showed segment 15 as *basal* septal, which put real
    numbers on the wrong wall).
    """

    # (ring, angle_index) -> segment_id. Rings: 0=apex cap, 1=apical, 2=mid, 3=basal
    SEGMENT_GEOMETRY: dict[int, tuple[int, int]] = {
        # Apical ring (6 segments, clockwise from anterior)
        13: (1, 0),
        18: (1, 1),
        17: (1, 2),
        16: (1, 3),
        15: (1, 4),
        14: (1, 5),
        # Mid ring
        7: (2, 0),
        12: (2, 1),
        11: (2, 2),
        10: (2, 3),
        9: (2, 4),
        8: (2, 5),
        # Basal ring
        1: (3, 0),
        6: (3, 1),
        5: (3, 2),
        4: (3, 3),
        3: (3, 4),
        2: (3, 5),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(250)
        self.setMinimumWidth(250)

        self._segment_items: dict[int, pg.PlotDataItem] = {}
        self._label_items: dict[int, pg.TextItem] = {}
        self._value_items: dict[int, pg.TextItem] = {}
        self._colorbar_item: pg.PlotDataItem | None = None

        # Default: all segments white (no data)
        self._segment_strains: dict[int, float] = {}
        self._segment_quality: dict[int, float] = {}
        self._segment_ttp: dict[int, float] = {}
        self._ttp_mode = False
        self._palette_index = 0
        self._hovered_segment: int | None = None
        self._segment_polygons: dict[int, object] = {}
        self.setMouseTracking(True)
        self.setToolTip(tr("strain.bullseye_tooltip_hint"))

    def paintEvent(self, event) -> None:
        """Custom paint using QPainter for filled segments."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainter, QPen, QPolygonF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        # The colourbar sits in the right margin, so the map (and its wall
        # labels) is laid out in the remaining area instead of centred in the
        # full widget — otherwise the lateral labels run under the bar.
        cb_total_w = self.COLORBAR_WIDTH + 46 if w >= 260 else 0
        map_w = max(w - cb_total_w, 1)

        # Wall labels are drawn around the rim, so the radius has to leave room
        # for the widest of them (side labels sit 30° off the horizontal, hence
        # the cos(30°) projection) and for a text line above/below.
        label_font = QFont(painter.font())
        label_font.setPointSize(9)
        label_font.setBold(True)
        metrics = QFontMetrics(label_font)
        line_h = float(metrics.height())
        side_w = max(
            float(metrics.horizontalAdvance(tr(key)))
            for key in ("strain.lbl_anterior", "strain.lbl_lateral", "strain.lbl_septal", "strain.lbl_inferior")
        )
        cos_side = float(np.cos(np.radians(30.0)))
        r_max = max(
            20.0,
            min(
                (map_w / 2.0 - side_w - 6.0) / cos_side,
                h / 2.0 - line_h - 4.0,
            ),
        )
        r_max *= 0.99  # keep the outermost ring stroke inside the widget

        cx, cy = map_w / 2, h / 2

        # Ring radii
        r_apex = r_max * 0.15
        r_apical = r_max * 0.38
        r_mid = r_max * 0.68
        r_basal = r_max * 1.0

        ring_radii = [r_apex, r_apical, r_mid, r_basal]

        # Draw filled segments (strain or time-to-peak, whichever was selected)
        ttp_mode = bool(getattr(self, "_ttp_mode", False))
        values = self._segment_ttp if ttp_mode else self._segment_strains
        for seg_id, (ring, angle_idx) in self.SEGMENT_GEOMETRY.items():
            strain = values.get(seg_id, None)

            # Check if segment is accepted by QC
            is_accepted = True
            if hasattr(self, "_qc_accepted_segments") and self._qc_accepted_segments is not None:
                is_accepted = seg_id in self._qc_accepted_segments

            quality = self._segment_quality.get(seg_id)
            low_confidence = quality is not None and float(quality) < self.LOW_QUALITY_THRESHOLD

            if strain is None:
                # No data for this segment: hatched/dark instead of a plausible
                # looking colour (issue #C11 — never colour a segment that was
                # not measured).
                color = QColor(40, 40, 40)
            elif not is_accepted:
                color = QColor(60, 60, 60)  # rejected by QC
            elif ttp_mode:
                color = self._ttp_to_color(strain)
            else:
                color = self._strain_to_color(strain)

            # Calculate polygon
            if ring == 0:
                # Apex cap: the 18-segment model has no apex segment, so the
                # centre is always drawn as "not measured".
                color = QColor(30, 30, 30)
                polygon = QPolygonF()
                for a in range(360):
                    rad = np.radians(a)
                    polygon.append(QPointF(cx + r_apex * np.cos(rad), cy + r_apex * np.sin(rad)))
            else:
                # Other rings: arc segments
                n_segments = 6
                angle_span = 360 / n_segments
                # Standard AHA orientation: segment 1 (basal anterior) is
                # *centred* on 12 o'clock, so the ring starts half a segment
                # counter-clockwise of it and runs clockwise (anterior →
                # anterolateral → inferolateral → inferior → inferoseptal →
                # anteroseptal).
                start_angle = -90 - angle_span / 2 + angle_idx * angle_span
                end_angle = start_angle + angle_span

                inner_r = ring_radii[ring - 1]
                outer_r = ring_radii[ring]

                polygon = QPolygonF()
                # Outer arc
                for a in range(int(start_angle), int(end_angle) + 1):
                    rad = np.radians(a)
                    polygon.append(QPointF(cx + outer_r * np.cos(rad), cy + outer_r * np.sin(rad)))
                # Inner arc (reversed)
                for a in range(int(end_angle), int(start_angle) - 1, -1):
                    rad = np.radians(a)
                    polygon.append(QPointF(cx + inner_r * np.cos(rad), cy + inner_r * np.sin(rad)))

            painter.setPen(QPen(QColor(80, 80, 80), 1))
            painter.setBrush(color)
            painter.drawPolygon(polygon)
            self._segment_polygons[seg_id] = polygon

            # State styling (plan §6.5): hatch = never measured, slash =
            # excluded by QC, dashed outline = low confidence.
            if strain is None:
                self._paint_hatch(painter, polygon)
            elif not is_accepted:
                self._paint_slash(painter, polygon)
            elif low_confidence:
                painter.save()
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(255, 235, 130), 1, Qt.PenStyle.DashLine))
                painter.drawPolygon(polygon)
                painter.restore()

            if seg_id == self._hovered_segment:
                # Hover highlight: a bright outline, so the segment under the
                # cursor is identifiable without moving the mouse off the map.
                painter.setPen(QPen(QColor(255, 255, 255), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(polygon)

        self._paint_colorbar(painter, w, h, r_max, ttp_mode)

        # Draw segment labels and values
        painter.setPen(QPen(QColor(220, 220, 220), 1))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        for seg_id, (ring, angle_idx) in self.SEGMENT_GEOMETRY.items():
            # Calculate label position (centroid of segment)
            n_segments_ring = 6
            angle_span = 360 / n_segments_ring
            mid_angle = np.radians(-90 + angle_idx * angle_span)  # label the segment centre

            if ring == 0:
                label_r = r_apex * 0.5
            else:
                inner_r = ring_radii[ring - 1]
                outer_r = ring_radii[ring]
                # Push the numbers towards the outer edge of their ring: at the
                # exact centre of the apical ring they crowd the apex cap.
                label_r = inner_r + 0.58 * (outer_r - inner_r)

            lx = cx + label_r * np.cos(mid_angle)
            ly = cy + label_r * np.sin(mid_angle)

            # Draw segment value (ms for the TTP map, % for strain)
            strain = self._segment_ttp.get(seg_id) if ttp_mode else self._segment_strains.get(seg_id)
            if strain is not None:
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                text = f"{strain:.0f}" if ttp_mode else f"{strain:.1f}"
                # Centre the text on the segment: the old fixed −15 px offset
                # cut the minus sign off the wider values.
                half = painter.fontMetrics().horizontalAdvance(text) / 2.0
                painter.drawText(QPointF(lx - half, ly + 4), text)

        # Draw outer labels (wall names) at the centre angle of the wall they
        # name — the same angle the segment fill uses.
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(180, 180, 180), 1))

        # Clockwise from the anterior wall, matching SEGMENT_GEOMETRY.
        outer_labels = {
            0: tr("strain.lbl_anterior"),
            1: tr("strain.lbl_lateral"),
            2: tr("strain.lbl_inferior_lateral"),
            3: tr("strain.lbl_inferior"),
            4: tr("strain.lbl_septal_inferior"),
            5: tr("strain.lbl_septal"),
        }
        for i, label in outer_labels.items():
            angle = np.radians(-90 + i * 60)
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            lx = cx + (r_basal + 8) * cos_a
            ly = cy + (r_basal + 8) * sin_a
            width = float(metrics.horizontalAdvance(label))
            # Anchor the label on the side it points at, so neighbouring walls
            # never collide and nothing runs under the colourbar.
            if cos_a < -0.01:
                x0 = lx - width
            elif cos_a > 0.01:
                x0 = lx
            else:
                x0 = lx - width / 2.0
            x0 = min(max(x0, 2.0), max(map_w - width - 2.0, 2.0))
            painter.drawText(QPointF(x0, ly + line_h / 4.0), label)

        # Draw concentric circles. The brush is cleared first: the colourbar
        # above paints with a QLinearGradient brush, and a filled ellipse here
        # would repaint the whole disc with that ramp instead of the segments.
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for r in ring_radii:
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Draw radial lines (segment boundaries: 12 o'clock ± 30°, every 60°)
        for angle_deg in range(0, 360, 60):
            rad = np.radians(angle_deg - 90)
            painter.drawLine(
                QPointF(cx + r_apex * np.cos(rad), cy + r_apex * np.sin(rad)),
                QPointF(cx + r_basal * np.cos(rad), cy + r_basal * np.sin(rad)),
            )

        # Draw center dot
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.setBrush(QColor(60, 60, 60))
        painter.drawEllipse(QPointF(cx, cy), 4, 4)

        painter.end()

    # Colour ramps of the bull's-eye. ``(value_threshold, RGB)`` from the most
    # negative end upwards; the first threshold the value satisfies wins.
    #
    # Default is the GE/EchoPAC ramp (plan §6.5, §11.1): bright red = normal
    # (|ε| > 16 %), then light red (16–11), light pink (10–6), pale pink (5–0),
    # blue = positive strain.
    #
    # PALETTES and ramp constants are imported from strain_helpers.py to avoid
    # circular dependency with ControlPanel.  Class-level aliases keep
    # ``BullseyeWidget.PALETTES`` working for callers and tests.

    # Colourbar range of the strain map: what the plan calls the "−20…+20 %"
    # scale with the blue end on top (GE reference).
    COLORBAR_MIN = -20.0
    COLORBAR_MAX = 20.0
    COLORBAR_TICKS = (20.0, 0.0, -5.0, -10.0, -15.0, -20.0)
    COLORBAR_WIDTH = 16

    # Segments whose tracking quality (NCC) is below this are drawn with a
    # dashed outline — "measured, but do not trust it" (plan §6.5). The value
    # matches the low-quality kernel colouring of the cine panels.
    LOW_QUALITY_THRESHOLD = 0.5

    # Class-level aliases for the module-level palette constants (see
    # strain_helpers.py).  Needed so that ``BullseyeWidget.PALETTES`` resolves
    # for tests and external callers.
    STRAIN_RAMP = STRAIN_RAMP
    DEFORMATION_PLUS_RAMP = DEFORMATION_PLUS_RAMP
    RAINBOW_RAMP = RAINBOW_RAMP
    MONOCHROME_RAMP = MONOCHROME_RAMP
    PALETTES = PALETTES

    # Time-to-peak ramp (blue → yellow → red): late activation is red, which is
    # the vendor convention for the TTP bull's-eye.
    TTP_RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
        (0.0, (38, 96, 214)),
        (200.0, (58, 190, 220)),
        (330.0, (255, 214, 64)),
        (430.0, (240, 120, 30)),
        (float("inf"), (206, 40, 40)),
    )

    @staticmethod
    def _ramp_color(value: float, ramp: tuple[tuple[float, tuple[int, int, int]], ...]) -> QColor:
        from PySide6.QtGui import QColor

        for threshold, color in ramp:
            if value <= threshold:
                return QColor(*color)
        return QColor(*ramp[-1][1])

    @property
    def palette_key(self) -> str:
        """i18n key of the active bull's-eye palette."""
        return PALETTES[self._palette_index][0]

    def active_palette_key(self) -> str:
        """Alias kept for callers that prefer an explicit method."""
        return self.palette_key

    def set_palette(self, name: str) -> None:
        """Activate a palette by i18n key (unknown names are ignored)."""
        for index, (key, _ramp) in enumerate(PALETTES):
            if key == name:
                self._palette_index = index
                self.update()
                return

    def cycle_palette(self) -> str:
        """Switch to the next palette (the ``C`` shortcut) and return its key."""
        self._palette_index = (self._palette_index + 1) % len(PALETTES)
        self.update()
        return self.palette_key

    def _strain_to_color(self, strain: float) -> QColor:
        """Map strain value to colour with the active bull's-eye palette."""
        return self._ramp_color(float(strain), PALETTES[self._palette_index][1])

    def _ttp_to_color(self, ttp_ms: float) -> QColor:
        """Map a time-to-peak value (ms from ED) to the TTP palette."""
        return self._ramp_color(float(ttp_ms), self.TTP_RAMP)

    def _colorbar_range(self, ttp_mode: bool) -> tuple[float, float]:
        """(low, high) of the colourbar for the active mode.

        Strain always uses the clinical −20…+20 % scale (so maps of different
        patients are comparable at a glance); the TTP map scales to the study,
        rounded up to a round number so its ticks stay readable.
        """
        if not ttp_mode:
            return self.COLORBAR_MIN, self.COLORBAR_MAX
        peak = max(self._segment_ttp.values(), default=0.0)
        step = 100.0 if peak > 300.0 else 50.0
        return 0.0, max(float(np.ceil(max(float(peak), 400.0) / step) * step), 400.0)

    def _colorbar_ticks(self, ttp_mode: bool) -> tuple[tuple[float, str], ...]:
        """Tick values and labels of the colourbar for the active mode."""
        lo, hi = self._colorbar_range(ttp_mode)
        if ttp_mode:
            return tuple(
                (round(lo + (hi - lo) * f, 0), f"{round(lo + (hi - lo) * f)}") for f in (1.0, 0.75, 0.5, 0.25, 0.0)
            )
        return tuple((value, f"{value:.0f}") for value in self.COLORBAR_TICKS)

    def _colorbar_ramp(self, ttp_mode: bool):
        return self.TTP_RAMP if ttp_mode else PALETTES[self._palette_index][1]

    def _paint_colorbar(self, painter, w: int, h: int, r_max: float, ttp_mode: bool) -> None:
        """Vertical colour scale of the map: the plan requires it next to the map.

        Range −20…+20 % for strain (blue end on top, as in the GE reference) and
        0…max ms for the time-to-peak map; the ramp is the active palette's.
        """
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QLinearGradient, QPen

        bar_h = r_max * 1.7
        bar_w = self.COLORBAR_WIDTH
        bar_x = w - bar_w - 46
        bar_y = (h - bar_h) / 2
        map_right = w - (self.COLORBAR_WIDTH + 46) if w >= 260 else w
        if bar_x < 0 or bar_x < map_right:  # not enough room next to the map
            return

        ramp = self._colorbar_ramp(ttp_mode)
        lo, hi = self._colorbar_range(ttp_mode)
        gradient = QLinearGradient(QPointF(bar_x, bar_y), QPointF(bar_x, bar_y + bar_h))
        steps = 32
        for step in range(steps + 1):
            frac = step / steps  # 0 = top of the bar
            value = hi - frac * (hi - lo)
            gradient.setColorAt(frac, self._ramp_color(value, ramp))
        painter.setPen(QPen(QColor(120, 120, 120), 1))
        painter.setBrush(gradient)
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        for value, label in self._colorbar_ticks(ttp_mode):
            frac = (hi - value) / (hi - lo) if hi > lo else 0.0
            ty = bar_y + frac * bar_h
            painter.drawLine(QPointF(bar_x + bar_w, ty), QPointF(bar_x + bar_w + 4, ty))
            painter.drawText(QPointF(bar_x + bar_w + 6, ty + 3), label)
        unit = tr("strain.unit_ms") if ttp_mode else "%"
        painter.drawText(QPointF(bar_x - 2, bar_y - 6), unit)
        painter.setBrush(Qt.BrushStyle.NoBrush)  # never leak the ramp brush

    @staticmethod
    def _clip_to_polygon(painter, polygon):
        """Clip the painter to a segment polygon and return its bounding box."""
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        path.addPolygon(polygon)
        painter.save()
        painter.setClipPath(path)
        return path, polygon.boundingRect()

    @staticmethod
    def _paint_hatch(painter, polygon) -> None:
        """Diagonal hatch over a segment that was never measured (plan §6.5)."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QPen

        _path, rect = BullseyeWidget._clip_to_polygon(painter, polygon)
        painter.setPen(QPen(QColor(145, 145, 145), 1))
        step = 6.0
        x = float(rect.left()) - float(rect.height())
        while x < float(rect.right()):
            painter.drawLine(QPointF(x, rect.bottom()), QPointF(x + rect.height(), rect.top()))
            x += step
        painter.restore()

    @staticmethod
    def _paint_slash(painter, polygon) -> None:
        """One bold slash across a segment excluded by QC (plan §6.5)."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QPen

        _path, rect = BullseyeWidget._clip_to_polygon(painter, polygon)
        painter.setPen(QPen(QColor(235, 235, 235), 2))
        painter.drawLine(QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.top()))
        painter.restore()

    def segment_at(self, x: float, y: float) -> int | None:
        """Segment id under a widget-space point, or None (hit test)."""
        try:
            from PySide6.QtCore import QPointF
        except ImportError:  # pragma: no cover - Qt is always present in the UI
            return None
        point = QPointF(float(x), float(y))
        for seg_id, polygon in self._segment_polygons.items():
            if polygon.containsPoint(point, Qt.FillRule.WindingFill):
                return int(seg_id)
        return None

    def segment_tooltip(self, seg_id: int) -> str:
        """Human-readable description of one segment (value, quality, TTP)."""
        values = self._segment_ttp if self._ttp_mode else self._segment_strains
        value = values.get(seg_id)
        if value is None:
            return f"{tr('strain.segment')} {seg_id}: {tr('strain.no_data')}"
        if self._ttp_mode:
            text = f"{tr('strain.segment')} {seg_id}: {float(value):.0f} {tr('strain.unit_ms')}"
        else:
            text = f"{tr('strain.segment')} {seg_id}: {float(value):+.1f} %"
        quality = self._segment_quality.get(seg_id)
        if quality is not None:
            text += f" · {tr('strain.quality')} {float(quality):.2f}"
        ttp = self._segment_ttp.get(seg_id)
        if ttp is not None and not self._ttp_mode:
            text += f" · TTP {float(ttp):.0f} {tr('strain.unit_ms')}"
        return text

    def mouseMoveEvent(self, event) -> None:
        """Track the cursor so the map can explain what is under it."""
        pos = event.position() if hasattr(event, "position") else event.pos()
        seg_id = self.segment_at(pos.x(), pos.y())
        if seg_id != self._hovered_segment:
            self._hovered_segment = seg_id
            self.update()
        if seg_id is not None:
            self.setToolTip(self.segment_tooltip(seg_id))
        else:
            self.setToolTip(tr("strain.bullseye_tooltip_hint"))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hovered_segment is not None:
            self._hovered_segment = None
            self.update()
        super().leaveEvent(event)

    def update_data(
        self,
        segment_strain: dict[int, float],
        segment_quality: dict[int, float] | None = None,
        segment_ttp_ms: dict[int, float] | None = None,
    ) -> None:
        """Update bull's eye with strain data (and the TTP map when supplied)."""
        self._segment_strains = segment_strain.copy()
        self._segment_quality = (segment_quality or {}).copy()
        self._segment_ttp = {int(k): float(v) for k, v in (segment_ttp_ms or {}).items()}
        self._qc_accepted_segments: set[int] | None = None
        self.update()  # Trigger repaint

    def set_ttp_mode(self, enabled: bool) -> None:
        """Switch the bull's-eye between strain and time-to-peak colourization."""
        self._ttp_mode = bool(enabled)
        self.update()

    def update_qc(
        self,
        segment_strain: dict[int, float],
        segment_quality: dict[int, float] | None,
        accepted_segments: set[int],
    ) -> None:
        """Update bull's eye with quality control information."""
        self._segment_strains = segment_strain.copy()
        self._segment_quality = (segment_quality or {}).copy()
        self._qc_accepted_segments = accepted_segments.copy()
        self.update()  # Trigger repaint

    def clear(self) -> None:
        self._segment_strains.clear()
        self._segment_quality.clear()
        self._segment_ttp.clear()
        self.update()
