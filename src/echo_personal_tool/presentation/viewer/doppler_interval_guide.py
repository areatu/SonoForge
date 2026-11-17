"""Interval tool guide: the preview bar and the dP/dt click velocity (item 1, 2026-11-17).

Two things happen around an interval measurement, and neither belongs in
:class:`DopplerOverlayTools` — it has a size ratchet, and every one of them used
to be four private methods of it:

* **the preview bar.**  After the first click a dashed bar with end ticks hangs
  at the first click's time and follows the pointer until the second click
  lands.  It is pure geometry over the axis mapping, so it lives here.
* **the fixed-click velocity.**  dP/dt is not a free interval: the calculation
  divides a fixed pressure rise by the time the regurgitant CW jet needs to
  travel from 1 m/s to 3 m/s (MR) or to 2 m/s (TR).  The physician therefore
  does not choose the *height* of either click — only its time.  This
  collaborator reports the velocity the next click is bound to, mirrors it onto
  the side of the baseline the jet is actually drawn on, and paints the dashed
  guide the crosshair rides.

Both read their state through plain callables supplied by the overlay, so no
interval state moves: the overlay keeps owning the click state machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import Qt

from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.domain.doppler_catalog import dpdt_click_velocity_cm_s
from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.presentation import dark_theme

logger = logging.getLogger(__name__)

#: Half-height of the end ticks of the preview bar, in plot pixels.
_PREVIEW_TICK_HALF_PX = 6.0
#: Height of the strip inspected on each side of the baseline to decide where
#: the spectrum is drawn, in plot pixels.
_JET_SIDE_STRIP_PX = 40


class DopplerIntervalGuide:
    """Preview bar of the interval tool and the fixed-velocity click guide."""

    def __init__(
        self,
        plot: Any,
        *,
        mapping: Callable[[], DopplerAxisMapping],
        target: Callable[[], float | None],
        pending_start: Callable[[], float | None],
    ) -> None:
        self._plot = plot
        self._mapping_supplier = mapping
        #: Unmirrored velocity the next click is bound to — ``None`` for a free
        #: interval or when the interval tool is not the active tool.
        self._target_supplier = target
        #: Time of the first click of the pending interval, ``None`` if none.
        self._pending_supplier = pending_start
        self._velocity_item: Any | None = None
        self._preview_item: Any | None = None

    # -- fixed click velocity -------------------------------------------------

    def velocity_cm_s(self) -> float | None:
        """Signed velocity of the guide (mirrored onto the jet side)."""
        target = self._target_supplier()
        if target is None:
            return None
        return target * self._jet_side()

    def plot_y(self) -> float | None:
        """Plot ``y`` of the velocity guide, ``None`` when there is none."""
        velocity = self.velocity_cm_s()
        if velocity is None:
            return None
        return self._mapping().y_from_velocity_cm_s(velocity)

    def refresh(self) -> None:
        """Draw the velocity guide for the current state, or clear it."""
        velocity = self.velocity_cm_s()
        if velocity is None:
            self.clear_velocity()
            return
        if self._velocity_item is None:
            self._velocity_item = self._add_item(17, dash=True)
        mapping = self._mapping()
        y = mapping.y_from_velocity_cm_s(velocity)
        x0 = mapping.plot_origin_x
        x1 = x0 + max(1.0, mapping.plot_width)
        self._velocity_item.setData([x0, x1], [y, y])

    def clear_velocity(self) -> None:
        """Hide the velocity guide (keeps the item for the next show)."""
        self._remove_from_plot(self._velocity_item)

    # -- preview bar ----------------------------------------------------------

    def pending_start_ms(self) -> float | None:
        """Time of the first click of the pending interval, ``None`` if none."""
        return self._pending_supplier()

    def baseline_y(self) -> float:
        """Plot ``y`` of the baseline — where the interval bar is drawn."""
        mapping = self._mapping()
        baseline = mapping.baseline_plot_y()
        return float(baseline) if baseline is not None else mapping.plot_height * 0.5

    def refresh_preview(self, *, end_x_px: float | None = None) -> None:
        """Draw the bar of the pending interval, with an end tick at *end_x_px*."""
        start_time_ms = self.pending_start_ms()
        if start_time_ms is None:
            self.clear_preview()
            return
        mapping = self._mapping()
        x_start = mapping.x_from_time_ms(start_time_ms)
        y_base = self.baseline_y()
        preview = self._ensure_preview_item()
        if end_x_px is None:
            preview.setData(
                [x_start, x_start],
                [y_base - _PREVIEW_TICK_HALF_PX, y_base + _PREVIEW_TICK_HALF_PX],
            )
            return
        x_end = float(end_x_px)
        xs: list[float] = [x_start, x_end]
        ys: list[float] = [y_base, y_base]
        for x_tick in (x_start, x_end):
            xs.extend([x_tick, x_tick])
            ys.extend([y_base - _PREVIEW_TICK_HALF_PX, y_base + _PREVIEW_TICK_HALF_PX])
        preview.setData(xs, ys)

    def clear_preview(self) -> None:
        """Remove the preview bar from the plot."""
        self._remove_from_plot(self._preview_item)

    def preview_item(self) -> Any | None:
        """The preview bar item, ``None`` until the first click created it."""
        return self._preview_item

    # -- items ----------------------------------------------------------------

    def _ensure_preview_item(self) -> Any:
        if self._preview_item is None:
            interval = dark_theme.get_theme_tokens()["overlay.doppler.interval"]
            import pyqtgraph as pg

            self._preview_item = pg.PlotDataItem(
                pen=pg.mkPen(interval, width=3, style=Qt.PenStyle.DashLine),
                symbol="t",
                symbolSize=10,
                symbolBrush=pg.mkBrush(interval),
            )
            self._preview_item.setZValue(19)
            self._plot.addItem(self._preview_item)
        elif self._preview_item.scene() is None:
            # Finishing/cancelling removes the preview; reattach it for repeats.
            self._plot.addItem(self._preview_item)
        return self._preview_item

    def _add_item(self, z_value: int, *, dash: bool) -> Any:
        import pyqtgraph as pg

        token = dark_theme.get_theme_tokens()["overlay.doppler.interval"]
        style = Qt.PenStyle.DashDotLine if dash else Qt.PenStyle.SolidLine
        item = pg.PlotDataItem(pen=pg.mkPen(token, width=1, style=style))
        item.setZValue(z_value)
        self._plot.addItem(item)
        return item

    def _remove_from_plot(self, item: Any | None) -> None:
        if item is None:
            return
        item.setData([], [])
        if item.scene() is None:
            return
        try:
            self._plot.removeItem(item)
        except Exception as exc:  # noqa: BLE001 - plot teardown boundary
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)

    # -- geometry -------------------------------------------------------------

    def _mapping(self) -> DopplerAxisMapping:
        return self._mapping_supplier()

    def _jet_side(self) -> float:
        """``+1`` when the spectrum is above the baseline, ``-1`` below it.

        The image is read through the plot's image item — the buffer the
        physician sees — so an inverted (below-baseline) CW jet keeps its guide
        on the visible jet.  Any unreadable state falls back to «above», the
        usual orientation of a mitral/tricuspid regurgitation spectrum.
        """
        mapping = self._mapping()
        baseline = self.baseline_y()
        image = getattr(self._plot, "image", None)
        if image is None or mapping.plot_height <= 0.0:
            return 1.0
        try:
            array = image.image
            rows = int(array.shape[0])
            start = int(baseline) + 1
            if start >= rows:
                return 1.0
            above = float(np.mean(array[max(0, int(baseline) - _JET_SIDE_STRIP_PX) : max(1, int(baseline))]))
            below = float(np.mean(array[start : min(start + _JET_SIDE_STRIP_PX, rows)]))
        except (AttributeError, TypeError, ValueError, IndexError):
            return 1.0
        return -1.0 if below > above else 1.0


def guide_target_velocity(interval_label: str, *, second_click: bool, active: bool) -> float | None:
    """Velocity the next click of *interval_label* is bound to.

    ``None`` when the interval tool is not active or the interval is free:
    only MR/TR dP/dt have fixed click velocities.
    """
    if not active:
        return None
    return dpdt_click_velocity_cm_s(interval_label, second=second_click)
