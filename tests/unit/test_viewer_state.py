"""Unit tests for ViewerState domain model."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState


def _make_instance(
    pixel_spacing: tuple[float, float] | None = (0.5, 0.5),
    pixel_spacing_source: str | None = "dicom",
) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.4",
        modality="US",
        number_of_frames=30,
        pixel_spacing=pixel_spacing,
        frame_time_ms=33.3,
        series_description="A4C",
        path=Path("/data/test.dcm"),
        pixel_spacing_source=pixel_spacing_source,
    )


class TestViewerStateDefaults:
    def test_minimal(self) -> None:
        state = ViewerState(
            instance=None,
            current_frame_index=0,
            total_frames=0,
            frame_time_ms=None,
            is_playing=False,
        )
        assert state.instance is None
        assert state.current_frame_index == 0
        assert state.total_frames == 0
        assert state.is_playing is False
        assert state.doppler_measurement is None
        assert state.contours == ()
        assert state.linear_measurements == ()
        assert state.measurement_snapshot is None
        assert state.decode_in_progress is False
        assert state.manual_pixel_spacing is None
        assert state.scroll_navigation is False


class TestEffectivePixelSpacing:
    def test_manual_overrides_instance(self) -> None:
        inst = _make_instance(pixel_spacing=(0.3, 0.3))
        state = ViewerState(
            instance=inst, current_frame_index=0, total_frames=1,
            frame_time_ms=33.3, is_playing=False,
            manual_pixel_spacing=(1.0, 1.0),
        )
        assert state.effective_pixel_spacing == (1.0, 1.0)

    def test_from_instance(self) -> None:
        inst = _make_instance(pixel_spacing=(0.4, 0.4))
        state = ViewerState(
            instance=inst, current_frame_index=0, total_frames=1,
            frame_time_ms=33.3, is_playing=False,
        )
        assert state.effective_pixel_spacing == (0.4, 0.4)

    def test_none_when_no_instance_no_manual(self) -> None:
        state = ViewerState(
            instance=None, current_frame_index=0, total_frames=0,
            frame_time_ms=None, is_playing=False,
        )
        assert state.effective_pixel_spacing is None

    def test_none_when_instance_has_no_spacing(self) -> None:
        inst = _make_instance(pixel_spacing=None)
        state = ViewerState(
            instance=inst, current_frame_index=0, total_frames=1,
            frame_time_ms=33.3, is_playing=False,
        )
        assert state.effective_pixel_spacing is None


class TestPixelSpacingSourceLabel:
    def test_manual_source(self) -> None:
        state = ViewerState(
            instance=_make_instance(), current_frame_index=0, total_frames=1,
            frame_time_ms=33.3, is_playing=False,
            manual_pixel_spacing=(1.0, 1.0),
        )
        assert state.pixel_spacing_source_label == "manual"

    def test_from_instance(self) -> None:
        inst = _make_instance(pixel_spacing_source="dicom")
        state = ViewerState(
            instance=inst, current_frame_index=0, total_frames=1,
            frame_time_ms=33.3, is_playing=False,
        )
        assert state.pixel_spacing_source_label == "dicom"

    def test_none_when_no_instance(self) -> None:
        state = ViewerState(
            instance=None, current_frame_index=0, total_frames=0,
            frame_time_ms=None, is_playing=False,
        )
        assert state.pixel_spacing_source_label is None


class TestFps:
    def test_normal(self) -> None:
        state = ViewerState(
            instance=None, current_frame_index=0, total_frames=1,
            frame_time_ms=33.3, is_playing=False,
        )
        assert abs(state.fps - 30.03) < 0.1

    def test_zero_when_none(self) -> None:
        state = ViewerState(
            instance=None, current_frame_index=0, total_frames=0,
            frame_time_ms=None, is_playing=False,
        )
        assert state.fps == 0.0

    def test_zero_when_negative(self) -> None:
        state = ViewerState(
            instance=None, current_frame_index=0, total_frames=0,
            frame_time_ms=-10.0, is_playing=False,
        )
        assert state.fps == 0.0

    def test_zero_when_zero(self) -> None:
        state = ViewerState(
            instance=None, current_frame_index=0, total_frames=0,
            frame_time_ms=0.0, is_playing=False,
        )
        assert state.fps == 0.0


class TestFrozen:
    def test_cannot_mutate(self) -> None:
        state = ViewerState(
            instance=None, current_frame_index=0, total_frames=0,
            frame_time_ms=None, is_playing=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.current_frame_index = 5  # type: ignore[misc]
