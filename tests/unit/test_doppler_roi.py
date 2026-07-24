"""Unit tests for Doppler spectrogram ROI and calibration state models."""

from __future__ import annotations

import dataclasses

import pytest

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerKind,
    DopplerSpectrogramRoi,
)


# ── DopplerKind ────────────────────────────────────────────────────


class TestDopplerKind:
    def test_spectral_values(self) -> None:
        assert DopplerKind.SPECTRAL.value == "spectral"
        assert DopplerKind.SPECTRAL.default_velocity_span_cm_s == 200.0

    def test_tissue_values(self) -> None:
        assert DopplerKind.TISSUE.value == "tissue"
        assert DopplerKind.TISSUE.default_velocity_span_cm_s == 40.0

    def test_string_representation(self) -> None:
        assert str(DopplerKind.SPECTRAL) == "DopplerKind.SPECTRAL"
        assert DopplerKind.SPECTRAL == "spectral"


# ── DopplerSpectrogramRoi ──────────────────────────────────────────


class TestDopplerSpectrogramRoi:
    def test_creation(self) -> None:
        roi = DopplerSpectrogramRoi(x0=10.0, y0=20.0, width=100.0, height=50.0)
        assert roi.x0 == 10.0
        assert roi.y0 == 20.0
        assert roi.width == 100.0
        assert roi.height == 50.0

    def test_x1_y1(self) -> None:
        roi = DopplerSpectrogramRoi(x0=10.0, y0=20.0, width=100.0, height=50.0)
        assert roi.x1 == 110.0
        assert roi.y1 == 70.0

    def test_contains_inside(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=100.0, height=100.0)
        assert roi.contains(50.0, 50.0) is True

    def test_contains_boundary(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=100.0, height=100.0)
        assert roi.contains(0.0, 0.0) is True
        assert roi.contains(100.0, 100.0) is True

    def test_contains_outside(self) -> None:
        roi = DopplerSpectrogramRoi(x0=10.0, y0=10.0, width=50.0, height=50.0)
        assert roi.contains(5.0, 5.0) is False
        assert roi.contains(100.0, 100.0) is False

    def test_normalized_clamps(self) -> None:
        roi = DopplerSpectrogramRoi(x0=90.0, y0=90.0, width=50.0, height=50.0)
        norm = roi.normalized(frame_width=100.0, frame_height=100.0)
        assert norm.x0 == 90.0
        assert norm.y0 == 90.0
        assert norm.width == 10.0  # clamped to frame_width - x0
        assert norm.height == 10.0

    def test_normalized_no_change(self) -> None:
        roi = DopplerSpectrogramRoi(x0=10.0, y0=10.0, width=50.0, height=50.0)
        norm = roi.normalized(frame_width=200.0, frame_height=200.0)
        assert norm.x0 == 10.0
        assert norm.width == 50.0

    def test_normalized_zero_frame(self) -> None:
        roi = DopplerSpectrogramRoi(x0=10.0, y0=10.0, width=50.0, height=50.0)
        norm = roi.normalized(frame_width=0.0, frame_height=0.0)
        # Returns self when frame dimensions are zero
        assert norm is roi

    def test_frozen(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=100.0, height=100.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            roi.x0 = 5.0  # type: ignore[misc]


# ── DopplerCalibrationState ────────────────────────────────────────


class TestDopplerCalibrationState:
    def _make_roi(self) -> DopplerSpectrogramRoi:
        return DopplerSpectrogramRoi(x0=10.0, y0=20.0, width=200.0, height=100.0)

    def test_defaults(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(roi=roi, baseline_y_px=50.0)
        assert state.time_origin_ms == 0.0
        assert state.time_span_ms == 1000.0
        assert state.velocity_span_cm_s == 200.0
        assert state.kind == DopplerKind.SPECTRAL
        assert state.from_dicom_tags is False
        assert state.velocity_from_dicom_tags is False

    def test_is_complete(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(roi=roi, baseline_y_px=50.0)
        assert state.is_complete() is True

    def test_is_not_complete_zero_velocity(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi, baseline_y_px=50.0, velocity_span_cm_s=0.0,
        )
        assert state.is_complete() is False

    def test_is_not_complete_zero_time(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi, baseline_y_px=50.0, time_span_ms=0.0,
        )
        assert state.is_complete() is False

    def test_has_velocity_scale(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(roi=roi, baseline_y_px=50.0)
        assert state.has_velocity_scale() is True

    def test_no_velocity_scale_zero_roi(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=0.0, height=0.0)
        state = DopplerCalibrationState(roi=roi, baseline_y_px=0.0)
        assert state.has_velocity_scale() is False

    def test_has_time_scale_from_dicom(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi, baseline_y_px=50.0, from_dicom_tags=True,
        )
        assert state.has_time_scale_from_dicom() is True

    def test_no_time_scale_from_dicom_when_not_dicom(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi, baseline_y_px=50.0, from_dicom_tags=False,
        )
        assert state.has_time_scale_from_dicom() is False

    def test_has_velocity_scale_from_dicom(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi, baseline_y_px=50.0, velocity_from_dicom_tags=True,
        )
        assert state.has_velocity_scale_from_dicom() is True

    def test_is_dicom_trusted(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi, baseline_y_px=50.0, from_dicom_tags=True,
        )
        assert state.is_dicom_trusted() is True

    def test_not_dicom_trusted_when_incomplete(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi, baseline_y_px=50.0, from_dicom_tags=True,
            velocity_span_cm_s=0.0,
        )
        assert state.is_dicom_trusted() is False

    def test_tissue_kind(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(
            roi=roi, baseline_y_px=50.0, kind=DopplerKind.TISSUE,
        )
        assert state.kind == DopplerKind.TISSUE

    def test_frozen(self) -> None:
        roi = self._make_roi()
        state = DopplerCalibrationState(roi=roi, baseline_y_px=50.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.baseline_y_px = 100.0  # type: ignore[misc]
