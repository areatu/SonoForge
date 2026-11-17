"""Item 1 of the 2026-11-17 list: the dP/dt interval is a duration, not a free pick.

The owner's requirement is concrete: dP/dt is ``ΔP / Δt`` where ``Δt`` is the
time the regurgitant CW jet needs to climb from 1 m/s to 3 m/s (MR) or to
2 m/s (TR).  So the *height* of both clicks is fixed by the physics — only the
time is chosen.  Before this slice the interval tool was a free measurement: the
physician placed both clicks wherever, and nothing on screen said which velocity
the click was bound to.

This file pins the guide that replaced that:

* the target velocity comes from the catalog (100 → 300 cm/s for MR,
  100 → 200 cm/s for TR) and only for the two dP/dt intervals;
* the guide is mirrored onto the side of the baseline the jet is drawn on, so a
  below-baseline spectrum does not get a guide above it;
* the crosshair reads :meth:`DopplerIntervalGuide.plot_y`, so the click lands on
  the velocity even though the pointer is free in ``x``;
* the preview bar of a pending interval is the same collaborator, and it is
  removed from the plot when the interval finishes or is cancelled.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("pytestqt")

import pyqtgraph as pg  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from echo_personal_tool.domain.doppler_catalog import dpdt_click_velocity_cm_s  # noqa: E402
from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping  # noqa: E402
from echo_personal_tool.presentation.doppler_overlay import DopplerOverlayTools  # noqa: E402
from echo_personal_tool.presentation.viewer.doppler_interval_guide import (  # noqa: E402
    DopplerIntervalGuide,
    guide_target_velocity,
)


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def overlay(qtbot) -> DopplerOverlayTools:
    plot = pg.PlotWidget()
    qtbot.addWidget(plot)
    plot.image = pg.ImageItem(np.full((120, 200), 10, dtype=np.uint8))
    tools = DopplerOverlayTools(plot, parent=plot)
    tools.set_axis_mapping(DopplerAxisMapping(time_span_ms=2000.0))
    return tools


# -- the physics -----------------------------------------------------------


def test_the_catalog_fixes_both_click_velocities() -> None:
    assert dpdt_click_velocity_cm_s("MR dP/dt", second=False) == 100.0
    assert dpdt_click_velocity_cm_s("MR dP/dt", second=True) == 300.0
    assert dpdt_click_velocity_cm_s("TR dP/dt", second=False) == 100.0
    assert dpdt_click_velocity_cm_s("TR dP/dt", second=True) == 200.0


def test_only_the_dpdt_intervals_have_a_fixed_velocity() -> None:
    assert guide_target_velocity("RR", second_click=False, active=True) is None
    assert guide_target_velocity("MR dP/dt", second_click=False, active=False) is None
    assert guide_target_velocity("MR dP/dt", second_click=True, active=True) == 300.0


# -- the overlay wiring ----------------------------------------------------


def test_the_guide_is_hidden_until_the_interval_tool_is_active(overlay) -> None:
    assert overlay.interval_guide.plot_y() is None
    overlay.set_tool_mode("interval")
    overlay.set_interval_label("MR dP/dt")
    assert overlay.interval_guide.plot_y() is not None


def test_the_guide_moves_from_the_first_velocity_to_the_second(overlay) -> None:
    overlay.set_tool_mode("interval")
    overlay.set_interval_label("MR dP/dt")
    first = overlay.interval_guide.velocity_cm_s()

    overlay.handle_click(100.0, 20.0)
    second = overlay.interval_guide.velocity_cm_s()

    assert abs(first) == pytest.approx(100.0)
    assert abs(second) == pytest.approx(300.0)


def test_the_guide_disappears_once_the_interval_is_placed(overlay) -> None:
    overlay.set_tool_mode("interval")
    overlay.set_interval_label("MR dP/dt")
    overlay.handle_click(100.0, 20.0)
    overlay.handle_click(500.0, 80.0)

    assert overlay.interval_guide.plot_y() is None
    assert overlay.interval_guide.pending_start_ms() is None
    assert len(overlay.get_measurement_dto().intervals) == 1


def test_a_free_interval_never_shows_the_guide(overlay) -> None:
    overlay.set_tool_mode("interval")
    overlay.set_interval_label("RR")

    assert overlay.interval_guide.velocity_cm_s() is None
    assert overlay.interval_guide.plot_y() is None


def test_the_guide_rides_the_plot_geometry(overlay) -> None:
    """The guide's ``y`` is the axis mapping's, so the crosshair is on the level."""
    mapping = DopplerAxisMapping(time_span_ms=2000.0)
    overlay.set_axis_mapping(mapping)
    overlay.set_tool_mode("interval")
    overlay.set_interval_label("MR dP/dt")

    expected = mapping.y_from_velocity_cm_s(overlay.interval_guide.velocity_cm_s())
    assert overlay.interval_guide.plot_y() == pytest.approx(expected)


# -- the mirroring ---------------------------------------------------------


class _StubPlot:
    """The two things the guide touches: ``addItem``/``removeItem`` and ``image``."""

    def __init__(self, array: np.ndarray) -> None:
        self.items: list[object] = []
        self.image = type("Image", (), {"image": array})()

    def addItem(self, item: object) -> None:  # noqa: N802 - Qt spelling
        self.items.append(item)

    def removeItem(self, item: object) -> None:  # noqa: N802 - Qt spelling
        if item in self.items:
            self.items.remove(item)


def _guide(plot: _StubPlot, *, target: float) -> DopplerIntervalGuide:
    mapping = DopplerAxisMapping(time_span_ms=2000.0)
    return DopplerIntervalGuide(plot, mapping=lambda: mapping, target=lambda: target, pending_start=lambda: None)


def test_an_above_baseline_jet_keeps_its_guide_above() -> None:
    """The generator's polarity: the jet is bright above the baseline."""
    array = np.zeros((120, 200), dtype=np.uint8)
    array[:50] = 200  # bright jet above the baseline
    guide = _guide(_StubPlot(array), target=100.0)

    assert guide.velocity_cm_s() > 0


def test_a_below_baseline_jet_gets_the_guide_below() -> None:
    """An inverted spectrum must not have its 1 m/s level above the baseline."""
    array = np.zeros((120, 200), dtype=np.uint8)
    array[90:] = 200  # bright jet below the baseline
    guide = _guide(_StubPlot(array), target=100.0)

    assert guide.velocity_cm_s() < 0


def test_an_unreadable_image_falls_back_to_above() -> None:
    class _Broken:
        @property
        def image(self):  # noqa: ANN202
            raise ValueError("no buffer")

    class _Plot(_StubPlot):
        def __init__(self) -> None:
            super().__init__(np.zeros((4, 4), dtype=np.uint8))
            self.image = _Broken()

    guide = _guide(_Plot(), target=100.0)
    assert guide.velocity_cm_s() > 0


# -- the preview bar -------------------------------------------------------


def test_the_preview_bar_follows_the_pending_interval(overlay) -> None:
    overlay.set_tool_mode("interval")
    overlay.set_interval_label("RR")
    overlay.interval_guide.refresh_preview()

    assert overlay.interval_guide.pending_start_ms() is None
    assert overlay.interval_guide.preview_item() is None

    overlay.handle_click(100.0, 20.0)
    overlay.interval_guide.refresh_preview(end_x_px=300.0)

    item = overlay.interval_guide.preview_item()
    assert item is not None
    assert item.scene() is not None
    x_values, y_values = item.getData()
    assert len(x_values) == len(y_values) == 6, "bar plus an end tick at each side"


def test_cancelling_removes_the_preview_bar(overlay) -> None:
    overlay.set_tool_mode("interval")
    overlay.set_interval_label("RR")
    overlay.handle_click(100.0, 20.0)

    assert overlay.cancel_active_tool()
    assert overlay.interval_guide.pending_start_ms() is None
    item = overlay.interval_guide.preview_item()
    assert item is None or item.scene() is None
