"""The phase annotation of the playback bar (extracted controller).

The phase caption («Систола»/«Диастола»/«—») under the cine timeline, the
detected-phase strip and its editable markers used to live inline in
``viewer_widget`` (audit 2026-11-27 seam 4).  This module owns them as one
controller: the strip widget, the fixed-width caption label, the timeline
and every transition (set / marker drag / reset / frame change).  The
viewer keeps the public ``set_phase_timeline`` delegate and the transport
plumbing, so callers and tests are untouched.

No behaviour changed in the move.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.services.cine_phase_timeline import (
    PHASE_DIASTOLE,
    PHASE_SYSTOLE,
    PhaseTimeline,
)
from echo_personal_tool.presentation.cine_phase_strip import CinePhaseStrip
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

#: The caption style template (colour comes from the theme tokens at runtime).
_CAPTION_STYLE_TEMPLATE = "color: {color}; font-size: 10px;"


class PhaseAnnotationController(QObject):
    """One owner for the phase strip, its caption and the applied timeline.

    The signals mirror the strip's own ones (frame selected, marker moved,
    marker reset requested) so the viewer binds once, exactly as before.
    ``current_frame_provider`` supplies the playhead position for the
    caption default (the transport slider value), keeping the slider owned
    by the transport.
    """

    frame_selected = Signal(int)
    marker_moved = Signal(int, str, int)
    marker_reset_requested = Signal(int, str)

    def __init__(self, *, parent: QWidget, current_frame_provider: Callable[[], int]) -> None:
        super().__init__(parent)
        self._current_frame_provider = current_frame_provider
        self._timeline: PhaseTimeline | None = None
        self._strip = CinePhaseStrip(translate=tr)
        self._strip.hide()
        self._strip.frame_selected.connect(self.frame_selected)
        self._strip.marker_moved.connect(self.marker_moved)
        self._strip.marker_reset_requested.connect(self.marker_reset_requested)
        self._label = QLabel("")
        self._fix_caption_width()

    # ── widgets ──────────────────────────────────────────────────────

    @property
    def strip(self) -> CinePhaseStrip:
        return self._strip

    @property
    def label(self) -> QLabel:
        return self._label

    # ── timeline ─────────────────────────────────────────────────────

    def timeline(self) -> PhaseTimeline | None:
        return self._timeline

    def set_timeline(self, timeline: PhaseTimeline | None) -> None:
        """Apply a detected timeline and update the caption (viewer delegate)."""
        self._timeline = timeline
        self._strip.set_timeline(timeline)
        self._strip.setVisible(timeline is not None and bool(timeline.markers()))
        self.update_caption()

    def on_marker_moved(self, cycle_index: int, kind: str, frame: int) -> PhaseTimeline | None:
        """A marker drag: re-derive the timeline with the manual ED/ES pair.

        Returns the new timeline (or ``None`` when the drag was ignored) so
        the viewer routes it through its own ``set_phase_timeline`` — that
        path refreshes the strip, exactly as the inline version did.
        """
        timeline = self._timeline
        if timeline is None or not (0 <= cycle_index < len(timeline.cycles)):
            return None
        cycle = timeline.cycles[cycle_index]
        ed_frame = frame if kind == "ed" else cycle.ed_frame
        es_frame = frame if kind == "es" else cycle.es_frame
        return timeline.with_manual_ed_es(cycle_index, ed_frame, es_frame)

    def on_marker_reset(self) -> PhaseTimeline | None:
        """The reset request: the base (machine-detected) timeline, if any."""
        return self._strip.base_timeline()

    # ── caption ──────────────────────────────────────────────────────

    def update_caption(self, *, frame: int | None = None) -> None:
        """Re-render the phase caption for *frame* (the playhead by default)."""
        if frame is None:
            frame = self._current_frame_provider()
        phase = self._strip.phase_at(frame)
        tokens = get_theme_tokens()
        if phase == PHASE_SYSTOLE:
            text, color = tr("cine.phase.label_systole"), tokens["state.err"]
        elif phase == PHASE_DIASTOLE:
            text, color = tr("cine.phase.label_diastole"), tokens["state.info"]
        elif self._timeline is not None and self._timeline.source != "unavailable":
            text, color = tr("cine.phase.label_unknown"), tokens["text.disabled"]
        else:
            text, color = "", tokens["text.disabled"]
        if self._label.text() != text:
            self._label.setText(text)
        self._label.setStyleSheet(_CAPTION_STYLE_TEMPLATE.format(color=color))

    # ── frame range sync ─────────────────────────────────────────────

    def set_total_frames(self, total: int) -> None:
        self._strip.set_total_frames(total)

    def set_current_frame(self, frame: int) -> None:
        self._strip.set_current_frame(frame)

    def fix_caption_width(self) -> None:
        """Pin the caption to the widest localized phase name (fixed phase text)."""
        self._fix_caption_width()

    def _fix_caption_width(self) -> None:
        longest = max(
            (
                tr("cine.phase.label_systole"),
                tr("cine.phase.label_diastole"),
                tr("cine.phase.label_unknown"),
            ),
            key=len,
        )
        margins = self._label.contentsMargins()
        width = (
            self._label.fontMetrics().horizontalAdvance(longest)
            + margins.left()
            + margins.right()
            + 2 * self._label.margin()
            + 2
        )
        self._label.setFixedWidth(width)
