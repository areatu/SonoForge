"""Cardiac phase strip for a cine playback bar (main viewer and STE window).

Two visual layers:

* translucent **bands** for systole / diastole / unknown, spanning whole frame
  ranges (not just two chips), so the playhead always shows the current phase;
* discrete **ED/ES chips** with a pointer to the slider groove, plus a playhead.

Honesty rules (see spec ``2026-10-26-cine-phase-timeline-markers-ru.md``):
a source that is an estimate (``+prior``), a low-confidence result, a partial
cycle or an unavailable detector is hatched / muted.  Colour is never the only
cue — chips carry letters, and tooltips name the source and confidence.

Interaction: click = seek, drag a chip = manual correction, double-click a chip
= request reset to the automatic result.  The widget never mutates the timeline;
the owner applies :meth:`PhaseTimeline.with_manual_ed_es` and re-sets it.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from echo_personal_tool.domain.services.cine_phase_timeline import (
    PHASE_DIASTOLE,
    PHASE_SYSTOLE,
    PHASE_UNKNOWN,
    PhaseMarker,
    PhaseTimeline,
)
from echo_personal_tool.presentation.cine_phase_geometry import (
    SLIDER_INSET,
    frame_at_x,
    marker_points,
    segment_rects,
    x_for_frame,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

Translate = Callable[..., str]


def _fallback_tr(key: str, **kwargs: object) -> str:
    """Neutral stand-in when the owner does not inject a translator."""
    return key


def _with_alpha(color: str, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(alpha)
    return result


def source_label(source: str, translate: Translate) -> str:
    """Human-readable name of the phase source, with a safe fallback."""
    key = "cine.phase.source." + source.replace("+", "_").replace("-", "_")
    label = translate(key)
    return label if label != key else source


def warning_label(code: str, translate: Translate) -> str:
    """Human-readable warning code; unknown codes stay visible verbatim."""
    key = f"cine.phase.warn.{code}"
    label = translate(key)
    return label if label != key else code


class CinePhaseStrip(QWidget):
    """Draw a :class:`PhaseTimeline` aligned with the frame slider below it."""

    frame_selected = Signal(int)  # frame index
    marker_moved = Signal(int, str, int)  # cycle index, "ed"/"es", new frame
    marker_reset_requested = Signal(int, str)  # cycle index, "ed"/"es"

    HEIGHT = 20
    _CHIP_W = 14
    _CHIP_H = 12
    _POINTER_H = 3
    _SLIDER_INSET = SLIDER_INSET
    _LOW_CONFIDENCE = 0.60

    def __init__(self, parent: QWidget | None = None, translate: Translate | None = None) -> None:
        super().__init__(parent)
        # Translation is injected by the owner: a new presentation module must
        # not add a direct presentation -> infrastructure edge (issue #307).
        self._tr: Translate = translate or _fallback_tr
        self.setObjectName("cinePhaseStrip")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._timeline: PhaseTimeline | None = None
        self._base_timeline: PhaseTimeline | None = None
        self._total = 0
        self._current_frame = 0
        self._placeholder = True
        # Legacy two-chip API (used by CinePanel and its existing tests).
        self._systole: int | None = None
        self._diastole: int | None = None
        self._drag: tuple[PhaseMarker, float, float] | None = None
        self._drag_frame: int | None = None
        self._refresh_tooltip()

    # ── data ────────────────────────────────────────────────────────
    def set_timeline(self, timeline: PhaseTimeline | None) -> None:
        """Replace the annotation.  ``None`` returns to the muted placeholder."""
        self._timeline = timeline
        self._total = 0 if timeline is None else timeline.n_frames
        self._placeholder = timeline is None or not timeline.markers()
        if timeline is None or "manual" not in timeline.source:
            # Do not let a reset on a new/empty clip resurrect the old heart.
            self._base_timeline = timeline
        self._systole = None
        self._diastole = None
        self._drag = None
        self._refresh_tooltip()
        self.update()

    def set_markers(self, systole_frame: int | None, diastole_frame: int | None, total_frames: int) -> None:
        """Legacy API: two event chips without phase bands (no detector yet)."""
        self._timeline = None
        self._base_timeline = None
        self._systole = systole_frame
        self._diastole = diastole_frame
        self._total = max(0, int(total_frames))
        self._placeholder = systole_frame is None and diastole_frame is None
        self._refresh_tooltip()
        self.update()

    def clear_markers(self) -> None:
        self.set_markers(None, None, self._total)

    def set_total_frames(self, total_frames: int) -> None:
        """Keep click-to-seek working before a detector result arrives."""
        if self._timeline is None:
            self._total = max(0, int(total_frames))
            self.update()

    def set_current_frame(self, frame_index: int) -> None:
        value = max(0, int(frame_index))
        if value != self._current_frame:
            self._current_frame = value
            self.update()

    def phase_at(self, frame_index: int) -> str:
        if self._timeline is None or self._placeholder:
            return PHASE_UNKNOWN
        return self._timeline.phase_at(frame_index)

    def base_timeline(self) -> PhaseTimeline | None:
        """Last fully automatic result — the target of a reset request."""
        return self._base_timeline

    # ── geometry ───────────────────────────────────────────────────
    def _x_for_frame(self, frame: int | None, fallback_ratio: float = 0.5) -> float:
        """Pixel x of a frame (or a placeholder ratio), aligned to the groove."""
        if self._total > 1 and frame is not None:
            ratio = min(1.0, max(0.0, float(frame) / float(self._total - 1)))
        else:
            ratio = fallback_ratio
        inset = max(self._CHIP_W / 2.0, self._SLIDER_INSET)
        usable = max(0.0, self.width() - 2.0 * inset)
        return inset + usable * ratio

    def _frame_at_x(self, x: float) -> int:
        return frame_at_x(x, self._total, 0.0, float(self.width()), self._SLIDER_INSET)

    def _marker_at(self, x: float, y: float) -> tuple[PhaseMarker, float] | None:
        if self._timeline is None or self._placeholder or y > self.HEIGHT:
            return None
        best: tuple[PhaseMarker, float] | None = None
        for marker_x, marker in marker_points(self._timeline, 0.0, float(self.width()), self._SLIDER_INSET):
            if abs(x - marker_x) <= self._CHIP_W / 2.0 + 3:
                if best is None or abs(x - marker_x) < abs(x - best[1]):
                    best = (marker, marker_x)
        return best

    # ── painting ───────────────────────────────────────────────────
    def paintEvent(self, event) -> None:  # type: ignore[override]  # noqa: N802
        del event
        tokens = get_theme_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = float(self.width()), float(self.HEIGHT)
        band_top, band_height = 1.0, height - 6.0

        painter.setPen(QPen(QColor(tokens["line.1"]), 1.0))
        painter.drawLine(0, self.HEIGHT - 1, int(width), self.HEIGHT - 1)

        if self._timeline is not None and not self._placeholder:
            self._draw_segments(painter, tokens, band_top, band_height)
            self._draw_legendless_markers(painter, tokens)
            if self._total > 1:
                head_x = x_for_frame(
                    min(self._current_frame, self._total - 1),
                    self._total,
                    0.0,
                    width,
                    self._SLIDER_INSET,
                )
                painter.setPen(QPen(QColor(tokens["text.1"]), 1.0, Qt.PenStyle.DashLine))
                painter.drawLine(int(head_x), 0, int(head_x), self.HEIGHT - 1)
        else:
            self._draw_placeholders(painter, tokens)
        painter.end()

    def _draw_segments(self, painter: QPainter, tokens: dict, top: float, band_height: float) -> None:
        assert self._timeline is not None
        colors = {
            PHASE_SYSTOLE: tokens["state.err"],
            PHASE_DIASTOLE: tokens["state.info"],
            PHASE_UNKNOWN: tokens["line.1"],
        }
        for x0, x1, segment in segment_rects(self._timeline, 0.0, float(self.width()), self._SLIDER_INSET):
            rect = QRectF(x0, top, max(1.0, x1 - x0), band_height)
            color = colors.get(segment.phase, tokens["line.1"])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_with_alpha(color, 70 if segment.phase != PHASE_UNKNOWN else 35))
            painter.drawRoundedRect(rect, 2.0, 2.0)
            if self._needs_hatching(segment.confidence, segment.source):
                self._hatch(painter, rect, color)
        # A dragged chip is previewed at its candidate frame.
        if self._drag is not None and self._drag_frame is not None:
            x = self._x_for_frame(self._drag_frame)
            painter.setPen(QPen(QColor(tokens["focus.ring"]), 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(int(x), 0, int(x), self.HEIGHT - 1)

    @staticmethod
    def _needs_hatching(confidence: float, source: str) -> bool:
        return confidence < CinePhaseStrip._LOW_CONFIDENCE or "+prior" in source or "burned_ecg" in source

    @staticmethod
    def _hatch(painter: QPainter, rect: QRectF, color: str) -> None:
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(QPen(_with_alpha(color, 160), 1.0))
        step = 6
        start = int(rect.left() - rect.height())
        stop = int(rect.right() + rect.height())
        for x in range(start, stop, step):
            painter.drawLine(x, int(rect.bottom()), x + int(rect.height()), int(rect.top()))
        painter.restore()

    def _draw_legendless_markers(self, painter: QPainter, tokens: dict) -> None:
        assert self._timeline is not None
        font = QFont(painter.font())
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        chip_top = self.HEIGHT - self._CHIP_H - self._POINTER_H
        for marker_x, marker in marker_points(self._timeline, 0.0, float(self.width()), self._SLIDER_INSET):
            color = tokens["overlay.strain.ed"] if marker.kind == "ed" else tokens["overlay.strain.es"]
            rect = QRectF(marker_x - self._CHIP_W / 2.0, chip_top, self._CHIP_W, self._CHIP_H)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(rect, 3.0, 3.0)
            path = QPainterPath()
            path.moveTo(marker_x - 3, chip_top + self._CHIP_H)
            path.lineTo(marker_x + 3, chip_top + self._CHIP_H)
            path.lineTo(marker_x, self.HEIGHT - 1)
            path.closeSubpath()
            painter.drawPath(path)
            if marker.confidence < self._LOW_CONFIDENCE or marker.partial or "+prior" in marker.source:
                painter.setPen(QPen(QColor(tokens["surface.0"]), 1.0, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 2.0, 2.0)
            painter.setPen(QColor(tokens["surface.0"]))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "D" if marker.kind == "ed" else "S")

    def _draw_placeholders(self, painter: QPainter, tokens: dict) -> None:
        muted = QColor(tokens["text.disabled"])
        chip_top = self.HEIGHT - self._CHIP_H - self._POINTER_H
        font = QFont(painter.font())
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        for frame, ratio, letter in (
            (self._systole, 1 / 3, "S"),
            (self._diastole, 2 / 3, "D"),
        ):
            # No decorative S/D chips at arbitrary thirds of a non-cardiac
            # or unanalyzable clip. Only explicit legacy markers may be drawn.
            if frame is None:
                continue
            cx = self._x_for_frame(frame, ratio)
            rect = QRectF(cx - self._CHIP_W / 2.0, chip_top, self._CHIP_W, self._CHIP_H)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(muted)
            painter.drawRoundedRect(rect, 3.0, 3.0)
            path = QPainterPath()
            path.moveTo(cx - 3, chip_top + self._CHIP_H)
            path.lineTo(cx + 3, chip_top + self._CHIP_H)
            path.lineTo(cx, self.HEIGHT - 1)
            path.closeSubpath()
            painter.drawPath(path)
            painter.setPen(QColor(tokens["surface.0"]))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)

    # ── interaction ────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        hit = self._marker_at(pos.x(), pos.y())
        if hit is not None:
            marker, marker_x = hit
            self._drag = (marker, marker_x, pos.x())
            self._drag_frame = marker.frame
            event.accept()
            return
        if self._total > 0:
            self.frame_selected.emit(self._frame_at_x(pos.x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._drag is not None and self._total > 0:
            self._drag_frame = max(0, min(self._total - 1, self._frame_at_x(pos.x())))
            self.update()
            event.accept()
            return
        hit = self._marker_at(pos.x(), pos.y())
        if hit is None:
            self._refresh_tooltip()
        else:
            self.setToolTip(self._marker_tooltip(hit[0]))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            super().mouseReleaseEvent(event)
            return
        marker, _, start_x = self._drag
        target = self._drag_frame if self._drag_frame is not None else marker.frame
        dragged = abs(event.position().x() - start_x) > 3
        self._drag = None
        self._drag_frame = None
        if dragged:
            self.marker_moved.emit(marker.cycle_index, marker.kind, int(target))
        else:
            self.frame_selected.emit(marker.frame)
        self._refresh_tooltip()
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        hit = self._marker_at(pos.x(), pos.y())
        if hit is not None:
            self.marker_reset_requested.emit(hit[0].cycle_index, hit[0].kind)
            self._drag = None
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ── tooltips ───────────────────────────────────────────────────
    def _refresh_tooltip(self) -> None:
        if self._timeline is None or self._placeholder:
            self.setToolTip(self._tr("cine.phase.strip_placeholder"))
            return
        timeline = self._timeline
        warnings = ", ".join(warning_label(w, self._tr) for w in timeline.warnings[:3])
        self.setToolTip(
            self._tr(
                "cine.phase.strip_tooltip",
                source=source_label(timeline.source, self._tr),
                confidence=f"{timeline.confidence:.2f}",
                cycles=str(len(timeline.cycles)),
                warnings=warnings or "—",
            )
        )

    def _marker_tooltip(self, marker: PhaseMarker) -> str:
        assert self._timeline is not None
        frame_time = self._timeline.frame_time_ms
        time_text = (
            self._tr("cine.phase.frame_ms", ms=f"{marker.frame * frame_time:.0f}")
            if frame_time
            else self._tr("cine.phase.frame_no_time", frame=str(marker.frame + 1))
        )
        kind = self._tr("cine.phase.ed") if marker.kind == "ed" else self._tr("cine.phase.es")
        suffix = self._tr("cine.phase.manual") if marker.source == "manual" else ""
        return self._tr(
            "cine.phase.marker_tooltip",
            kind=kind,
            frame=str(marker.frame + 1),
            time=time_text,
            source=source_label(marker.source, self._tr),
            confidence=f"{marker.confidence:.2f}",
            suffix=suffix,
        )
