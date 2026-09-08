"""Tests for STE measurement honesty: QC vs NCC, clinical GLS and drift (issue #3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import SpeckleConfig, StrainResult
from echo_personal_tool.domain.services.aha_segments import choose_clinical_gls
from echo_personal_tool.domain.services.strain_computation import assess_strain_plausibility

# ── physiological plausibility check ──────────────────────────────


class TestAssessStrainPlausibility:
    def _curve(self, values):
        return np.array(values, dtype=np.float64)

    def test_normal_systolic_shortening_is_plausible(self) -> None:
        longitudinal = self._curve([0.0, -5.0, -10.0, -15.0, -18.0, -15.0, -6.0, -1.0])
        radial = self._curve([0.0, 2.0, 5.0, 8.0, 10.0, 8.0, 3.0, 0.0])
        ok, reasons = assess_strain_plausibility(longitudinal, radial, ed_index=0, es_index=4)
        assert ok
        assert reasons == []

    def test_positive_longitudinal_is_hard_failure(self) -> None:
        # NCC can be >90% yet the curve is physiologically impossible: positive
        # longitudinal strain during systole (issue #3).
        longitudinal = self._curve([0.0, 5.0, 20.0, 33.0, 15.0])
        ok, reasons = assess_strain_plausibility(longitudinal, None, ed_index=0, es_index=3)
        assert not ok
        assert any("no systolic shortening" in r for r in reasons)

    def test_no_radial_thickening_is_hard_failure(self) -> None:
        longitudinal = self._curve([0.0, -5.0, -12.0, -15.0])
        radial = self._curve([0.0, -1.0, -4.0, -6.0])
        ok, reasons = assess_strain_plausibility(longitudinal, radial, ed_index=0, es_index=3)
        assert not ok
        assert any("no radial thickening" in r for r in reasons)

    def test_peak_before_mid_systole_warns(self) -> None:
        longitudinal = self._curve([0.0, -20.0, -5.0, -2.0, -1.0])
        ok, reasons = assess_strain_plausibility(longitudinal, None, ed_index=0, es_index=4)
        assert any("before mid-systole" in r for r in reasons)

    def test_empty_window(self) -> None:
        ok, reasons = assess_strain_plausibility(np.array([np.nan, np.nan]), None, 0, 1)
        assert not ok

    def test_none_longitudinal(self) -> None:
        ok, reasons = assess_strain_plausibility(None, None, 0, 1)
        assert not ok
        assert reasons == ["no longitudinal strain curve"]


# ── clinical GLS aggregation ──────────────────────────────────────


class TestClinicalGls:
    def test_mean_not_worst_segment(self) -> None:
        # Old behaviour picked np.min -> one bad segment (-40) dominated the GLS.
        curve = -18.0
        segment_strain = {1: -40.0, 2: -17.0, 3: -19.0}
        segment_quality = {1: 0.9, 2: 0.85, 3: 0.9}
        gls, source = choose_clinical_gls(curve, segment_strain, segment_quality)
        assert source == "segments"
        assert gls == pytest.approx(-25.333, abs=0.01)  # mean, not -40

    def test_insufficient_segments_falls_back_to_curve(self) -> None:
        curve = -18.0
        segment_strain = {1: -40.0, 2: -17.0}
        segment_quality = {1: 0.9, 2: 0.85}
        gls, source = choose_clinical_gls(curve, segment_strain, segment_quality, min_segments=3)
        assert source == "curve"
        assert gls == pytest.approx(-18.0)

    def test_low_quality_segments_excluded(self) -> None:
        curve = -18.0
        segment_strain = {1: -40.0, 2: -17.0, 3: -19.0}
        segment_quality = {1: 0.1, 2: 0.9, 3: 0.9}
        gls, source = choose_clinical_gls(
            curve,
            segment_strain,
            segment_quality,
            min_segment_quality=0.5,
            min_segments=2,
        )
        assert source == "segments"
        assert gls == pytest.approx(-18.0, abs=0.01)  # only segments 2,3

    def test_empty_segments_curve(self) -> None:
        gls, source = choose_clinical_gls(-14.0, {}, {})
        assert source == "curve"
        assert gls == pytest.approx(-14.0)


# ── StrainResult QC fields exist and default sanely ───────────────


class TestStrainResultQcFields:
    def test_defaults(self) -> None:
        res = StrainResult(longitudinal=np.zeros(5), radial=np.zeros(5), gls=-15.0)
        assert res.qc_score == 0.0
        assert res.qc_physiology_ok is True
        assert res.qc_physiology_reasons == ()
        assert res.gls_source == "curve"

    def test_fields_populated(self) -> None:
        res = StrainResult(
            longitudinal=np.zeros(5),
            radial=np.zeros(5),
            gls=-15.0,
            qc_score=0.42,
            qc_physiology_ok=False,
            qc_physiology_reasons=("no systolic shortening",),
            gls_source="curve",
        )
        assert res.qc_score == pytest.approx(0.42)
        assert not res.qc_physiology_ok
        assert res.qc_physiology_reasons == ("no systolic shortening",)


# ── worker-level: drift + QC wiring ───────────────────────────────


def _make_zone(n_points=16):
    angles = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    endo = np.column_stack([16 + 5 * np.cos(angles), 16 + 5 * np.sin(angles)])
    epi = np.column_stack([16 + 8 * np.cos(angles), 16 + 8 * np.sin(angles)])
    from echo_personal_tool.domain.models.speckle import MyocardialZone

    return MyocardialZone(
        endo_points=endo,
        epi_points=epi,
        thickness_mm=8.0,
        pixel_spacing=(0.5, 0.5),
    )


class TestWorkerQcWiring:
    def _run_worker(
        self,
        *,
        longitudinal_values,
        manual_ed=0,
        manual_es=5,
        n=10,
        radial_values=None,
    ):
        from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
        from echo_personal_tool.domain.models.speckle import TrackingKernel

        if radial_values is None:
            radial_values = [0.0, 2.0, 5.0, 3.0, 0.0, 0.0]
        frames = np.random.randint(0, 256, (n, 32, 32), dtype=np.uint8)
        zone = _make_zone()
        kernels = [
            TrackingKernel(center=(10.0, 10.0), radius=4, node_index=0, layer="endo"),
            TrackingKernel(center=(12.0, 12.0), radius=4, node_index=1, layer="endo"),
            TrackingKernel(center=(14.0, 14.0), radius=4, node_index=2, layer="endo"),
            TrackingKernel(center=(18.0, 18.0), radius=4, node_index=3, layer="epi"),
            TrackingKernel(center=(20.0, 20.0), radius=4, node_index=4, layer="epi"),
        ]
        n_kernels = len(kernels)
        curve = np.array(longitudinal_values, dtype=np.float64)
        patches = {
            "detect_ed_es_from_frames": MagicMock(return_value=(0, 5)),
            "track_cine_sequential": MagicMock(return_value=[MagicMock(displacements=np.zeros((6, n_kernels, 2)))]),
            "preprocess_echo_frame": MagicMock(return_value=np.zeros((32, 32), dtype=np.uint8)),
            "build_zone_mask": MagicMock(return_value=np.ones((32, 32), dtype=bool)),
            "extract_trajectories": MagicMock(
                return_value=(
                    np.full((6, n_kernels, 2), 10.0),
                    np.full((6, n_kernels), 0.95),
                )
            ),
            "interpolate_invalid_kernels": MagicMock(return_value=np.full((6, n_kernels, 2), 10.0)),
            "smooth_trajectories": MagicMock(return_value=np.full((6, n_kernels, 2), 10.0)),
            "apply_motion_model": MagicMock(return_value=np.full((6, n_kernels, 2), 10.0)),
            "compute_weighted_longitudinal_strain_gl": MagicMock(return_value=curve),
            "compute_weighted_radial_strain_gl": MagicMock(return_value=np.array(radial_values, dtype=np.float64)),
            "compute_strain_rate": MagicMock(return_value=np.zeros(n)),
            "estimate_heart_rate_fft": MagicMock(return_value=72.0),
            "build_myocardial_roi_mask": MagicMock(return_value=np.ones((32, 32), dtype=bool)),
            "compute_gls": MagicMock(return_value=-15.0),
            "compute_aha_segment_strain": MagicMock(
                return_value=({1: -15.0, 2: -16.0, 3: -17.0}, {1: 0.9, 2: 0.9, 3: 0.9})
            ),
        }

        with (
            patch("echo_personal_tool.application.workers.speckle_worker.sample_kernels_in_zone", return_value=kernels),
            patch("echo_personal_tool.application.workers.speckle_worker.assign_aha_segments", return_value=kernels),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.detect_ed_es_from_frames",
                patches["detect_ed_es_from_frames"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.track_cine_sequential",
                patches["track_cine_sequential"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.preprocess_echo_frame",
                patches["preprocess_echo_frame"],
            ),
            patch("echo_personal_tool.application.workers.speckle_worker.build_zone_mask", patches["build_zone_mask"]),
            patch("echo_personal_tool.application.workers.speckle_worker.extract_trajectories", patches["extract_trajectories"]),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.interpolate_invalid_kernels",
                patches["interpolate_invalid_kernels"],
            ),
            patch("echo_personal_tool.application.workers.speckle_worker.smooth_trajectories", patches["smooth_trajectories"]),
            patch("echo_personal_tool.application.workers.speckle_worker.apply_motion_model", patches["apply_motion_model"]),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.compute_weighted_longitudinal_strain_gl",
                patches["compute_weighted_longitudinal_strain_gl"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.compute_weighted_radial_strain_gl",
                patches["compute_weighted_radial_strain_gl"],
            ),
            patch("echo_personal_tool.application.workers.speckle_worker.compute_strain_rate", patches["compute_strain_rate"]),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.estimate_heart_rate_fft",
                patches["estimate_heart_rate_fft"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.build_myocardial_roi_mask",
                patches["build_myocardial_roi_mask"],
            ),
            patch("echo_personal_tool.application.workers.speckle_worker.compute_gls", patches["compute_gls"]),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.compute_aha_segment_strain",
                patches["compute_aha_segment_strain"],
            ),
        ):
            worker = SpeckleTrackingWorker(
                frames=frames,
                zone=zone,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                manual_ed=manual_ed,
                manual_es=manual_es,
                config=SpeckleConfig(tracking_mode="sequential"),
            )
            finished = []
            worker.signals.finished.connect(lambda r: finished.append(r))
            worker.run()
            assert len(finished) == 1
            return finished[0]

    def test_drift_off_for_systolic_window(self) -> None:
        # Window ED..ES (0..5) ends at end-systole — no baseline to close, so
        # drift compensation must be reported OFF even though the config enables it.
        res = self._run_worker(longitudinal_values=[0.0, -5.0, -10.0, -5.0, 0.0, 0.0])
        assert res.drift_compensation_applied is False

    def test_implausible_curve_lowers_qc_score(self) -> None:
        # NCC is 0.95 (high) but the curve shows lengthening, not shortening.
        res = self._run_worker(longitudinal_values=[0.0, 5.0, 20.0, 33.0, 15.0, 5.0])
        assert res.tracking_quality_mean > 0.9  # raw NCC still high
        assert res.qc_physiology_ok is False
        assert res.qc_physiology_reasons
        assert res.qc_score <= 0.5

    def test_plausible_curve_keeps_qc_high(self) -> None:
        res = self._run_worker(longitudinal_values=[0.0, -5.0, -10.0, -5.0, 0.0, 0.0])
        assert res.qc_physiology_ok is True
        assert res.qc_score > 0.7
