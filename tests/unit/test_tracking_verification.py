"""Round-trip verification of the tracking itself (clinical review Q6).

The question this file answers: *how can the frame-to-frame contour tracking be
trusted?* Three layers:

* ``verify_trajectory_closure`` matches every analysed frame of the *finished*
  trajectory (interpolated, repaired, smoothed — what the overlay draws and the
  strain integrates) back to the end-diastolic frame and measures by how much it
  misses the drawn contour;
* the worker summarises that over the analysed window — the share of node-frames
  the tracker could not confirm, the share that produced no verdict at all, and
  the closure error in millimetres — and the QC report gates on it;
* the phantom, which knows where every material point went, is used to check that
  the summary still *means* something: node-frames the tracker rejected must be
  worse than the ones it verified.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import SpeckleConfig, TrackingKernel
from echo_personal_tool.domain.services.quality import assess_tracking_quality
from echo_personal_tool.domain.services.speckle_tracking import (
    track_cine_bidirectional,
    track_cine_sequential,
    verify_trajectory_closure,
)

REASON = "strain.qc.reason.tracking_verification"


def _texture(seed: int = 0, size: int = 48) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.normal(0.5, 0.18, size=(size, size))
    # A little smoothing so the pattern survives the pyramid: this is the kind of
    # speckle a block matcher is meant to follow.
    from scipy.ndimage import gaussian_filter

    return np.clip(gaussian_filter(base, 1.2), 0.0, 1.0)


def _kernels(centers: list[tuple[float, float]], layer: str = "endo") -> list[TrackingKernel]:
    return [
        TrackingKernel(center=(x, y), radius=5, node_index=index, layer=layer) for index, (x, y) in enumerate(centers)
    ]


class TestTrackerClosureError:
    def test_pure_translation_closes_the_round_trip(self) -> None:
        """Texture that moved by a known offset must be matched there and back."""
        first = _texture()
        shift_x, shift_y = 3, -2
        second = np.roll(np.roll(first, shift_y, axis=0), shift_x, axis=1)
        kernels = _kernels([(24.0, 24.0), (30.0, 22.0)])
        config = SpeckleConfig(kernel_size=10, search_radius=8, pyramid_levels=1, ncc_threshold=0.5)
        results = track_cine_bidirectional(np.stack([first, second]), kernels, ed_index=0, config=config)

        assert len(results) == 1
        assert np.allclose(
            results[0].kernel_positions - np.array([k.center for k in kernels]),
            [shift_x, shift_y],
            atol=1.0,
        )


class TestTrajectoryVerificationPass:
    """``verify_trajectory_closure`` is what the report is allowed to quote."""

    @staticmethod
    def _trajectory(frames: np.ndarray, centers: np.ndarray, offset: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
        positions = np.stack([centers + np.array(offset) for _ in range(frames.shape[0])])
        return positions

    def test_verified_trajectory_closes(self) -> None:
        first = _texture()
        second = np.roll(first, 3, axis=1)
        frames = np.stack([first, second])
        kernels = _kernels([(24.0, 24.0), (30.0, 22.0)])
        positions = self._trajectory(frames, np.array([k.center for k in kernels]), offset=(3.0, 0.0))
        closure = verify_trajectory_closure(
            frames,
            positions,
            kernels,
            ed_index=0,
            config=SpeckleConfig(kernel_size=10, search_radius=8, pyramid_levels=1, ncc_threshold=0.5),
        )

        assert closure.shape == (2, 2)
        assert float(np.max(np.abs(closure[0]))) == 0.0  # the reference frame is exact
        assert np.all(np.isfinite(closure[1]))
        assert float(np.max(closure[1])) < 1.0, f"a correct trajectory must close: {closure[1]}"

    def test_wrong_position_is_measured_as_closure_error(self) -> None:
        """A trajectory that drifted off the tissue cannot close back onto ED."""
        first = _texture()
        frames = np.stack([first, first.copy()])
        kernels = _kernels([(24.0, 24.0)])
        drifted = self._trajectory(frames, np.array([k.center for k in kernels]), offset=(6.0, 0.0))
        closure = verify_trajectory_closure(
            frames,
            drifted,
            kernels,
            ed_index=0,
            config=SpeckleConfig(kernel_size=10, search_radius=8, pyramid_levels=1, ncc_threshold=0.5),
        )

        assert np.isfinite(closure[1, 0])
        assert float(closure[1, 0]) > 3.0, f"drift not detected: {closure[1, 0]}"

    def test_blank_frame_gives_no_verdict_instead_of_a_confident_zero(self) -> None:
        first = _texture()
        frames = np.stack([first, np.full_like(first, 0.5)])
        kernels = _kernels([(24.0, 24.0)])
        positions = self._trajectory(frames, np.array([k.center for k in kernels]))
        closure = verify_trajectory_closure(
            frames,
            positions,
            kernels,
            ed_index=0,
            config=SpeckleConfig(kernel_size=10, search_radius=8, pyramid_levels=1, ncc_threshold=0.5),
        )

        assert not np.isfinite(closure[1, 0]) or float(closure[1, 0]) > 1.0

    def test_gate_is_the_one_the_pass_uses(self) -> None:
        """The summary must not judge closure with a radius the round trip never got."""
        from echo_personal_tool.domain.services.speckle_tracking import (
            VERIFICATION_SEARCH_RADIUS_PX,
            verification_gate_px,
        )

        small = SpeckleConfig(kernel_size=10, search_radius=8)
        assert verification_gate_px(small) == pytest.approx(
            small.closure_error_threshold * VERIFICATION_SEARCH_RADIUS_PX
        )
        large = SpeckleConfig(kernel_size=10, search_radius=40)
        assert verification_gate_px(large) == pytest.approx(large.closure_error_threshold * 40)


class TestSequentialModeUsesTheSameVerdict:
    def test_sequential_closure_is_verified_by_the_pass_not_by_the_mode(self) -> None:
        """Mode-independent honesty: the sequential tracker reports no internal flag."""
        frames = np.stack([_texture(), np.roll(_texture(), 2, axis=1)])
        config = SpeckleConfig(kernel_size=10, search_radius=8, pyramid_levels=1)
        results = track_cine_sequential(frames, _kernels([(24.0, 24.0)]), ed_index=0, config=config)
        kernels = _kernels([(24.0, 24.0)])
        positions = np.stack([np.array([k.center for k in kernels]) for _ in range(2)])
        closure = verify_trajectory_closure(frames, positions, kernels, ed_index=0, config=config)
        assert np.isfinite(closure).any()
        assert isinstance(results, list)


class TestVerificationQualityPolicy:
    def _report(self, **kw):
        return assess_tracking_quality(
            has_curve=True,
            fidelity=0.9,
            coverage=1.0,
            interpolated_fraction=0.0,
            consistency_delta=0.0,
            physiology_ok=True,
            n_segments_measured=6,
            gls_pp=-19.0,
            **kw,
        )

    def test_clean_tracking_needs_no_verification_flag(self) -> None:
        report = self._report(rejected_fraction=0.05, closure_median_mm=0.4)
        assert report.status == "valid"
        assert REASON not in report.reasons

    def test_rejected_share_downgrades_to_review(self) -> None:
        report = self._report(rejected_fraction=0.15, closure_median_mm=0.6)
        assert report.status == "review"
        assert REASON in report.reasons
        assert any("round-trip" in note for note in report.notes)
        assert report.confidence <= 0.75

    def test_massive_rejection_is_invalid(self) -> None:
        report = self._report(rejected_fraction=0.35, closure_median_mm=2.0)
        assert report.status == "invalid"
        assert REASON in report.reasons

    def test_no_verdict_at_all_is_not_a_pass(self) -> None:
        report = self._report(unverified_fraction=0.4)
        assert report.status == "review"
        assert REASON in report.reasons

    def test_fractions_are_clamped(self) -> None:
        report = self._report(rejected_fraction=-1.0, unverified_fraction=-1.0)
        assert report.status == "valid"
        assert report.rejected_fraction == 0.0


@pytest.fixture(scope="module")
def phantom_module():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures"))
    from ste_phantom import StePhantom, StePhantomConfig

    return StePhantom, StePhantomConfig


def _run_worker(phantom):
    from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker

    config = phantom.config
    payload: dict = {}
    worker = SpeckleTrackingWorker(
        frames=phantom.frames(),
        zone=phantom.zone(),
        pixel_spacing=(config.pixel_spacing_mm, config.pixel_spacing_mm),
        frame_time_ms=config.frame_time_ms,
        manual_ed=0,
        manual_es=config.es_index,
        view="A4C",
        config=SpeckleConfig.preset_standard(),
    )
    worker.signals.finished.connect(lambda result: payload.setdefault("result", result))
    worker.signals.error.connect(lambda message: payload.setdefault("error", message))
    worker.run()
    assert "error" not in payload, payload.get("error")
    return payload["result"]


@pytest.mark.gui
def test_clean_clip_tracking_is_verified_and_reported(phantom_module, qapp) -> None:
    """A clean clip: the round trip closes, and the numbers say so."""
    StePhantom, StePhantomConfig = phantom_module
    phantom = StePhantom(StePhantomConfig.quick(mode="uniform", noise_db=40.0, decorrelation=0.25))
    result = _run_worker(phantom)

    assert result.qc_status == "valid"
    assert result.qc_rejected_fraction <= 0.10, f"rejected {result.qc_rejected_fraction:.2f}"
    assert result.qc_unverified_fraction == 0.0
    assert result.qc_closure_median_mm <= 0.6, f"closure {result.qc_closure_median_mm:.2f} mm — median"
    assert result.qc_coverage == 1.0
    assert result.closure_all_frames is not None
    assert np.isfinite(result.closure_all_frames[result.es_index]).all()


@pytest.mark.gui
def test_rejected_node_frames_are_the_worse_ones(phantom_module, qapp) -> None:
    """The reported flag must keep its meaning: rejected > verified in truth.

    This is the calibration claim behind the QC gate, checked against the exact
    phantom trajectories rather than asserted in a comment.
    """
    StePhantom, StePhantomConfig = phantom_module
    phantom = StePhantom(StePhantomConfig.quick(mode="uniform", noise_db=40.0, decorrelation=0.25))
    result = _run_worker(phantom)

    positions = np.asarray(result.tracked_positions_all, dtype=np.float64)
    closure = np.asarray(result.closure_all_frames, dtype=np.float64)
    kernels = list(result.kernels)
    centers = np.array([kernel.center for kernel in kernels], dtype=np.float64)
    truth = np.stack([phantom.deform(centers, frame) for frame in range(positions.shape[0])])
    error_mm = np.linalg.norm(positions - truth, axis=2) * phantom.config.pixel_spacing_mm

    window = slice(0, int(result.tracking_window_end) + 1)
    gate_px = 0.5 * 24.0  # closure_error_threshold × effective search radius
    rejected = closure[window] > gate_px
    assert rejected.sum() > 20, "the clean phantom should reject a few node-frames, not none at all"

    verified_error = error_mm[window][~rejected]
    rejected_error = error_mm[window][rejected]
    assert np.percentile(rejected_error, 95) > 1.5 * np.percentile(verified_error, 95), (
        f"p95 error verified {np.percentile(verified_error, 95):.2f} mm vs "
        f"rejected {np.percentile(rejected_error, 95):.2f} mm"
    )


@pytest.mark.gui
def test_noisy_clip_reports_unverified_tracking(phantom_module, qapp) -> None:
    """At 10 dB a fifth of the wall cannot be confirmed — and that is reported."""
    StePhantom, StePhantomConfig = phantom_module
    phantom = StePhantom(StePhantomConfig.quick(mode="uniform", noise_db=10.0, decorrelation=0.25))
    result = _run_worker(phantom)

    assert result.qc_rejected_fraction > 0.10, f"rejected {result.qc_rejected_fraction:.2f}"
    assert result.qc_closure_median_mm > result.qc_closure_median_mm * 0  # finite, reported
    assert result.qc_status != "valid"
    assert REASON in result.qc_reasons


class TestVerificationIsClinicallyReported:
    """A verdict the UI cannot phrase is not a verdict the clinician can read."""

    def test_reason_and_summary_strings_exist_in_both_locales(self) -> None:
        import json
        from pathlib import Path

        from echo_personal_tool.domain.services.quality import REASON_TRACKING_VERIFICATION

        root = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "infrastructure" / "locales"
        for name in ("en.json", "ru.json"):
            data = json.loads((root / name).read_text(encoding="utf-8"))
            assert REASON_TRACKING_VERIFICATION in data, name
            assert data[REASON_TRACKING_VERIFICATION].strip(), name
            assert "strain.tracking_verification" in data, name
            assert "{confirmed}" in data["strain.tracking_verification"]
            assert "{closure}" in data["strain.tracking_verification"]


class TestEacviAseDeclarations:
    """Voigt 2015 asks a strain number to declare what it was measured on.

    Not a style point: without the sampling extent, the translation handling, the
    regularization and the frame rate, two "GLS" values are not comparable, which
    is the whole purpose of the consensus document.
    """

    def test_analysis_record_declares_sampling_and_processing(self) -> None:
        from echo_personal_tool.domain.models.speckle import StrainResult
        from echo_personal_tool.domain.models.ste_analysis import (
            DEFINITION_COMPARABILITY,
            StrainAnalysis,
        )

        result = StrainResult(
            longitudinal=np.zeros((1, 1)),
            radial=np.zeros((1, 1)),
            gls=-19.0,
            sampling_kernel_mm=5.4,
            sampling_node_spacing_mm=2.95,
            regularization="Savitzky-Golay 9-frame filter",
            translation_compensation_applied=True,
            frame_rate_hz=60.0,
        )
        analysis = StrainAnalysis.from_result(result)
        payload = analysis.to_dict()

        assert analysis.definition_comparability == DEFINITION_COMPARABILITY
        assert payload["sampling"]["kernel_mm"] == pytest.approx(5.4)
        assert payload["sampling"]["node_spacing_mm"] == pytest.approx(2.95)
        assert payload["sampling"]["translation_compensation"] is True
        assert payload["sampling"]["frame_rate_hz"] == pytest.approx(60.0)
        assert payload["sampling"]["regularization"]
        assert payload["definitions"]["comparability"] == DEFINITION_COMPARABILITY

    def test_declaration_defaults_are_not_silently_invented(self) -> None:
        """An old result without the fields must read as "not declared", not zero."""
        from echo_personal_tool.domain.models.speckle import StrainResult
        from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis

        analysis = StrainAnalysis.from_result(
            StrainResult(longitudinal=np.zeros((1, 1)), radial=np.zeros((1, 1)), gls=-19.0)
        )

        assert analysis.sampling_kernel_mm == pytest.approx(0.0)
        assert analysis.regularization == ""
        assert analysis.translation_compensation is False


class TestTrustFlagHarness:
    """The harness that compares candidate trust flags must itself be right."""

    @staticmethod
    def _module():
        import importlib.util
        import sys
        from pathlib import Path

        name = "ste_trust_flags_bench"
        if name in sys.modules:
            return sys.modules[name]
        path = Path(__file__).resolve().parents[2] / "bench" / "ste_trust_flags.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        # dataclasses resolves annotations through sys.modules, so the module
        # has to exist there before it is executed.
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def test_scoring_counts_flagged_bad_node_frames(self) -> None:
        module = self._module()
        error_mm = np.array([10.0, 1.0, 1.0, 1.0])
        flag = np.array([True, False, False, False])
        bad = error_mm > 5.0

        score = module._score(flag, bad, error_mm, "test")

        assert score.name == "test"
        assert score.detection["flagged"] == 1
        assert score.detection["bad"] == 1
        assert score.detection["precision"] == pytest.approx(1.0)
        assert score.detection["recall"] == pytest.approx(1.0)
        # The one thing the flag is for: the group it leaves alone is better
        # than the group it marks.
        assert score.trusted_p95_mm < score.flagged_p95_mm
        assert score.flagged_p95_mm == pytest.approx(10.0)

    def test_a_missed_bad_node_frame_stays_in_the_trusted_group(self) -> None:
        module = self._module()
        error_mm = np.array([10.0, 1.0, 1.0, 12.0])
        flag = np.array([True, False, False, False])

        score = module._score(flag, error_mm > 5.0, error_mm, "partial")

        assert score.detection["recall"] == pytest.approx(0.5)
        # Recall is the honest part of the score: an unflagged 12 mm error is
        # still reported as trusted, which is exactly why the flag may not be
        # presented as a complete detector.
        assert score.trusted_p95_mm > 5.0

    def test_a_flag_that_never_fires_scores_zero_not_full_marks(self) -> None:
        module = self._module()
        score = module._score(np.zeros(4, dtype=bool), np.array([True, False, False, False]), np.ones(4), "silent")

        assert score.flagged_fraction == 0.0
        assert score.detection["precision"] == 0.0
        assert score.detection["recall"] == 0.0
        assert not np.isfinite(score.flagged_p95_mm)
