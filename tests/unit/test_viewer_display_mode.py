"""Viewer display mode and DICOM color handling."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
pytestmark = pytest.mark.gui

from echo_personal_tool.domain.models import InstanceMetadata, ViewerState
from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from echo_personal_tool.presentation.viewer_widget import ViewerWidget
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom, write_synthetic_rgb_dicom


@pytest.fixture
def viewer(qtbot):
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    return widget


def _viewer_state_for(path: Path, media_format: str = "dicom") -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.4",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.3, 0.3),
        frame_time_ms=None,
        series_description="Synthetic",
        path=path,
        media_format=media_format,
    )
    return ViewerState(
        instance=instance,
        current_frame_index=0,
        total_frames=1,
        frame_time_ms=None,
        is_playing=False,
    )


def test_rgb_dicom_keeps_red_channel(viewer, qtbot, tmp_path: Path) -> None:
    path = tmp_path / "rgb.dcm"
    write_synthetic_rgb_dicom(path)
    viewer.set_state(_viewer_state_for(path))
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    pixels[:, :, 0] = 200
    pixels[:, :, 1] = 40
    pixels[:, :, 2] = 20
    pixels[0, 0] = np.array([255, 0, 0], dtype=np.uint8)
    viewer.show_frame(pixels)
    frame = viewer._color_source_rgb
    assert frame is not None
    assert np.array_equal(frame[0, 0], np.array([255, 0, 0], dtype=np.uint8))


def test_grayscale_dicom_enables_window_level(viewer, qtbot, tmp_path: Path) -> None:
    path = tmp_path / "mono.dcm"
    write_synthetic_dicom(path)
    viewer.set_state(_viewer_state_for(path))
    pixels = DicomReaderImpl().read_pixels(path, frame_index=0)
    viewer.show_frame(pixels)
    assert viewer._window_level_enabled
    assert viewer._window_slider.isEnabled()


def test_rgb_dicom_preserves_color_without_window_level(viewer, qtbot, tmp_path: Path) -> None:
    path = tmp_path / "rgb.dcm"
    write_synthetic_rgb_dicom(path)
    viewer.set_state(_viewer_state_for(path))
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    pixels[:, :, 0] = 200
    pixels[:, :, 1] = 40
    pixels[:, :, 2] = 20
    viewer.show_frame(pixels)
    assert viewer._is_color_frame
    assert not viewer._window_level_enabled
    assert not viewer._window_slider.isEnabled()


def test_bmode_rgb_packing_uses_grayscale_window_level(viewer, qtbot, tmp_path: Path) -> None:
    path = tmp_path / "rgb.dcm"
    write_synthetic_rgb_dicom(path)
    viewer.set_state(_viewer_state_for(path))
    pixels = DicomReaderImpl().read_pixels(path, frame_index=0)
    viewer.show_frame(pixels)
    assert not viewer._is_color_frame
    assert viewer._window_level_enabled
    assert viewer._window_slider.isEnabled()
