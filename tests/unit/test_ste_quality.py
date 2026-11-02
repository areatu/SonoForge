"""QC validity assessment: NCC fidelity is not measurement validity (issue #C7)."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.quality import (
    REASON_CONSISTENCY,
    REASON_FEW_SEGMENTS,
    REASON_GEOMETRY,
    REASON_INTERPOLATION,
    REASON_LOW_COVERAGE,
    REASON_NO_DATA,
    REASON_PHYSIOLOGY,
    STATUS_INVALID,
    STATUS_REVIEW,
    STATUS_VALID,
    assess_tracking_quality,
)


def _assess(**overrides):
    params = {
        "has_curve": True,
        "fidelity": 0.92,
        "coverage": 0.95,
        "interpolated_fraction": 0.02,
        "consistency_delta": 0.3,
        "physiology_ok": True,
        "geometry_ok": True,
        "n_segments_measured": 6,
    }
    params.update(overrides)
    return assess_tracking_quality(**params)


class TestStatuses:
    def test_clean_tracking_is_valid(self) -> None:
        report = _assess()
        assert report.status == STATUS_VALID
        assert report.is_valid
        assert report.reasons == ()
        assert report.confidence == pytest.approx(0.92 * 0.95 * (1 - 0.5 * (0.02 / 0.3)) - 0.0, abs=0.02)

    def test_high_ncc_with_impossible_physiology_is_invalid(self) -> None:
        """The reported symptom: NCC > 90 % while the curve cannot be true."""
        report = _assess(fidelity=0.96, physiology_ok=False, physiology_notes=("no systolic shortening",))
        assert report.status == STATUS_INVALID
        assert REASON_PHYSIOLOGY in report.reasons
        assert report.confidence <= 0.35
        assert "no systolic shortening" in report.notes

    def test_unusable_geometry_is_invalid(self) -> None:
        report = _assess(geometry_ok=False, geometry_notes=("LV outline looks like a closed ring",))
        assert report.status == STATUS_INVALID
        assert REASON_GEOMETRY in report.reasons

    def test_no_curve_is_invalid(self) -> None:
        report = _assess(has_curve=False)
        assert report.status == STATUS_INVALID
        assert REASON_NO_DATA in report.reasons

    def test_half_the_line_untracked_is_invalid(self) -> None:
        report = _assess(coverage=0.4)
        assert report.status == STATUS_INVALID
        assert REASON_LOW_COVERAGE in report.reasons

    @pytest.mark.parametrize(
        "overrides, expected",
        [
            ({"coverage": 0.7}, REASON_LOW_COVERAGE),
            ({"interpolated_fraction": 0.25}, REASON_INTERPOLATION),
            ({"consistency_delta": 3.0}, REASON_CONSISTENCY),
            ({"n_segments_measured": 1}, REASON_FEW_SEGMENTS),
        ],
    )
    def test_soft_issues_downgrade_to_review(self, overrides, expected) -> None:
        report = _assess(**overrides)
        assert report.status == STATUS_REVIEW
        assert expected in report.reasons
        assert report.confidence <= 0.75
        assert not report.is_valid

    def test_confidence_never_reaches_one_with_a_review_status(self) -> None:
        assert _assess(coverage=0.79).confidence < 0.75

    def test_reasons_are_deduplicated_and_ordered(self) -> None:
        report = _assess(coverage=0.6, interpolated_fraction=0.2, consistency_delta=5.0)
        assert len(report.reasons) == len(set(report.reasons))
        assert report.reasons[0] == REASON_LOW_COVERAGE


class TestConfidenceMonotonicity:
    def test_lower_coverage_never_raises_confidence(self) -> None:
        strong = _assess(coverage=0.95)
        weak = _assess(coverage=0.85)
        assert weak.confidence < strong.confidence

    def test_more_interpolation_never_raises_confidence(self) -> None:
        assert _assess(interpolated_fraction=0.1).confidence < _assess(interpolated_fraction=0.0).confidence

    def test_consistency_gap_penalises_confidence(self) -> None:
        assert _assess(consistency_delta=4.0).confidence < _assess(consistency_delta=0.5).confidence
