"""Tests for composite frame panel models."""

from __future__ import annotations

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import (
    FramePanelLayout,
    PanelKind,
    UltrasoundPanel,
)
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    PHYSICAL_UNIT_CM,
    PHYSICAL_UNIT_SEC,
)


def test_ultrasound_panel_horizontal_mm_per_pixel() -> None:
    panel = UltrasoundPanel(
        kind=PanelKind.B_MODE,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=100),
        physical_delta_x=0.02,
        physical_delta_y=0.03,
        physical_units_x=PHYSICAL_UNIT_CM,
        physical_units_y=PHYSICAL_UNIT_CM,
    )
    assert panel.horizontal_mm_per_pixel == 0.2
    assert panel.vertical_mm_per_pixel == 0.3


def test_ultrasound_panel_horizontal_mm_none_on_time_axis() -> None:
    panel = UltrasoundPanel(
        kind=PanelKind.M_MODE,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=100),
        physical_delta_x=0.024,
        physical_units_x=PHYSICAL_UNIT_SEC,
    )
    assert panel.horizontal_mm_per_pixel is None
    assert panel.horizontal_ms_per_pixel == 24.0


def _b_mode_panel() -> UltrasoundPanel:
    return UltrasoundPanel(
        kind=PanelKind.B_MODE,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=100),
        physical_delta_x=0.02,
        physical_delta_y=0.03,
        physical_units_x=PHYSICAL_UNIT_CM,
        physical_units_y=PHYSICAL_UNIT_CM,
    )


def test_doppler_zone_beats_a_b_mode_tag_inside_the_zone() -> None:
    """Samsung tags many Doppler stills as B-mode; the calibrated zone is Doppler."""
    layout = FramePanelLayout((_b_mode_panel(),))
    zone = DopplerSpectrogramRoi(x0=40, y0=50, width=60, height=50)

    tagged = layout.with_doppler_zone(zone)

    assert tagged.doppler is not None
    assert tagged.doppler.bounds == zone
    # Inside the calibrated spectrum the B-mode geometry no longer applies…
    assert tagged.b_mode_panel_at(60, 70) is None
    # …while the rest of the frame keeps it (composite B-mode + spectrum).
    assert tagged.b_mode_panel_at(10, 10) is not None


def test_doppler_zone_replaces_a_previous_doppler_panel() -> None:
    stale = UltrasoundPanel(
        kind=PanelKind.DOPPLER,
        bounds=DopplerSpectrogramRoi(x0=0, y0=0, width=10, height=10),
    )
    layout = FramePanelLayout((stale, _b_mode_panel()))
    zone = DopplerSpectrogramRoi(x0=40, y0=50, width=60, height=50)

    tagged = layout.with_doppler_zone(zone)

    dopplers = [panel for panel in tagged.panels if panel.kind is PanelKind.DOPPLER]
    assert [panel.bounds for panel in dopplers] == [zone]
    assert tagged.b_mode is not None


def test_layout_without_a_doppler_zone_keeps_b_mode_geometry() -> None:
    layout = FramePanelLayout((_b_mode_panel(),))
    assert layout.doppler is None
    assert layout.b_mode_panel_at(60, 70) is not None
