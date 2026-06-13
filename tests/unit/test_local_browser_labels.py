"""Tests for LocalBrowser instance labels."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.presentation.local_browser import _instance_label


def test_dicom_instance_label_uses_filename() -> None:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.840.113619.2.55.3.604688123.868.1730000000.123",
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=45,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="",
        path=Path("/data/study/A4C_clip.dcm"),
        media_format="dicom",
    )
    label = _instance_label(instance)
    assert label.startswith("A4C_clip.dcm")
    assert "45 frames" in label
    assert "1.2.840" not in label


def test_single_frame_label() -> None:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.4",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description="",
        path=Path("/data/frame.dcm"),
    )
    assert _instance_label(instance) == "frame.dcm\n(1 frame)"
