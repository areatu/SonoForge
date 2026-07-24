"""Unit tests for domain metadata models (InstanceRef, InstanceMetadata, SeriesMetadata, StudyMetadata)."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

import pytest

from echo_personal_tool.domain.models.metadata import (
    InstanceMetadata,
    InstanceRef,
    SeriesMetadata,
    StudyMetadata,
)


# ── InstanceRef ────────────────────────────────────────────────────


class TestInstanceRef:
    def test_creation(self) -> None:
        ref = InstanceRef(
            path=Path("/data/scan.dcm"),
            sop_instance_uid="1.2.3",
            series_uid="1.2.4",
            study_uid="1.2.5",
        )
        assert ref.path == Path("/data/scan.dcm")
        assert ref.sop_instance_uid == "1.2.3"
        assert ref.series_uid == "1.2.4"
        assert ref.study_uid == "1.2.5"

    def test_frozen(self) -> None:
        ref = InstanceRef(path=Path("/x"), sop_instance_uid="1", series_uid="2", study_uid="3")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.path = Path("/y")  # type: ignore[misc]


# ── InstanceMetadata ───────────────────────────────────────────────


class TestInstanceMetadata:
    def test_defaults(self) -> None:
        meta = InstanceMetadata(
            sop_instance_uid="1.2.3",
            series_uid="1.2.4",
            modality="US",
            number_of_frames=1,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="Test",
        )
        assert meta.path is None
        assert meta.media_format == "dicom"
        assert meta.pixel_spacing_source is None
        assert meta.frame_time_vector is None
        assert meta.patient_height_m is None
        assert meta.patient_weight_kg is None

    def test_populated(self) -> None:
        meta = InstanceMetadata(
            sop_instance_uid="1.2.3",
            series_uid="1.2.4",
            modality="US",
            number_of_frames=30,
            pixel_spacing=(0.4, 0.4),
            frame_time_ms=33.3,
            series_description="A4C",
            path=Path("/data/scan.dcm"),
            media_format="mp4",
            pixel_spacing_source="manual",
            frame_time_vector=(33.3, 33.4, 33.5),
            patient_height_m=1.75,
            patient_weight_kg=70.0,
        )
        assert meta.path == Path("/data/scan.dcm")
        assert meta.media_format == "mp4"
        assert meta.pixel_spacing == (0.4, 0.4)
        assert meta.frame_time_ms == 33.3
        assert len(meta.frame_time_vector) == 3
        assert meta.patient_height_m == 1.75
        assert meta.patient_weight_kg == 70.0

    def test_frozen(self) -> None:
        meta = InstanceMetadata(
            sop_instance_uid="1", series_uid="2", modality="US",
            number_of_frames=1, pixel_spacing=None, frame_time_ms=None,
            series_description="x",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.modality = "CT"  # type: ignore[misc]


# ── SeriesMetadata ─────────────────────────────────────────────────


class TestSeriesMetadata:
    def test_creation(self) -> None:
        inst = InstanceMetadata(
            sop_instance_uid="1.2.3", series_uid="1.2.4", modality="US",
            number_of_frames=1, pixel_spacing=None, frame_time_ms=None,
            series_description="frame",
        )
        series = SeriesMetadata(
            series_uid="1.2.4",
            study_uid="1.2.5",
            modality="US",
            description="A4C cine",
            instances=(inst,),
        )
        assert series.series_uid == "1.2.4"
        assert len(series.instances) == 1
        assert series.instances[0] is inst

    def test_empty_instances(self) -> None:
        series = SeriesMetadata(
            series_uid="1", study_uid="2", modality="US",
            description="empty", instances=(),
        )
        assert series.instances == ()

    def test_frozen(self) -> None:
        series = SeriesMetadata(
            series_uid="1", study_uid="2", modality="US",
            description="x", instances=(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            series.description = "y"  # type: ignore[misc]


# ── StudyMetadata ──────────────────────────────────────────────────


class TestStudyMetadata:
    def test_creation(self) -> None:
        study = StudyMetadata(
            study_uid="1.2.5",
            study_datetime=datetime(2025, 1, 15, 10, 30),
            series=(),
        )
        assert study.study_uid == "1.2.5"
        assert study.study_datetime == datetime(2025, 1, 15, 10, 30)
        assert study.series == ()

    def test_with_series(self) -> None:
        s1 = SeriesMetadata(
            series_uid="s1", study_uid="st1", modality="US",
            description="A4C", instances=(),
        )
        s2 = SeriesMetadata(
            series_uid="s2", study_uid="st1", modality="US",
            description="A2C", instances=(),
        )
        study = StudyMetadata(
            study_uid="st1",
            study_datetime=datetime(2025, 6, 1),
            series=(s1, s2),
        )
        assert len(study.series) == 2
        assert study.series[0].series_uid == "s1"
        assert study.series[1].series_uid == "s2"

    def test_frozen(self) -> None:
        study = StudyMetadata(
            study_uid="1", study_datetime=datetime.now(), series=(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            study.study_uid = "2"  # type: ignore[misc]
