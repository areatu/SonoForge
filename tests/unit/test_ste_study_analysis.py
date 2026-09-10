"""Phase 3 — analysis record with provenance and the multi-view study (GLS_AV).

The user's decision for the module was "all three apical views available from
the start, analysed one at a time". That only works if a result records the view
it belongs to, keeps the definition of every number it reports, and if the views
can be averaged the way a vendor report does (``GLS_AV``). These tests pin:

* the analysis record is complete and JSON-serialisable (definitions, anchors,
  QC, segments, curves) — no number without its provenance;
* the study keeps per-view GLS, averages only the views that passed QC, and
  merges the 18 segments without inventing the ones nobody measured;
* exported dictionaries never contain NaN/Infinity (invalid JSON) for missing
  values.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import StrainResult
from echo_personal_tool.domain.models.ste_analysis import (
    ANALYSIS_SCHEMA_VERSION,
    StrainAnalysis,
    StrainStudy,
    study_from_results,
)


def _result(
    view: str,
    gls: float,
    status: str = "valid",
    segments: dict[int, float] | None = None,
    *,
    ess: float | None = -18.0,
    ttp: float = 330.0,
    avc_source: str = "ecg",
) -> StrainResult:
    segments = segments or {3: -17.0, 9: -18.5, 15: -21.0, 6: -19.0, 12: -20.0, 18: -21.5}
    n = 12
    return StrainResult(
        longitudinal=np.linspace(0.0, -18.0, n),
        radial=np.zeros(n),
        gls=gls,
        view=view,
        qc_status=status,
        qc_reasons=() if status == "valid" else ("strain.qc.reason.few_segments",),
        segment_strain=dict(segments),
        segment_quality={seg: 0.9 for seg in segments},
        segment_curves={seg: np.linspace(0.0, value, n) for seg, value in segments.items()},
        segment_ttp_ms={seg: ttp for seg in segments},
        ed_index=0,
        es_index=5,
        avc_index=5,
        avc_source=avc_source,
        avc_confidence=0.9,
        ess=ess,
        peak_strain=gls,
        drift_measured=-0.4,
        time_to_peak_ms=ttp,
        post_systolic_index=1.5,
        analysis_window_end=n - 1,
        config_preset="standard",
        tracking_quality_mean=0.92,
        qc_coverage=0.95,
        kernels_accepted_count=90,
        kernels_total_count=96,
        heart_rate_bpm=64.0,
        frame_time_ms=33.3,
    )


class TestAnalysisRecord:
    def test_record_carries_definitions_and_anchors(self) -> None:
        analysis = StrainAnalysis.from_result(_result("A2C", -18.0))
        assert analysis.view == "A2C"
        assert analysis.schema_version == ANALYSIS_SCHEMA_VERSION
        assert "peak of the global" in analysis.definition_gls
        assert "aortic valve closure" in analysis.definition_ess
        assert analysis.avc_source == "ecg"
        assert analysis.window_end == 11

    def test_record_is_json_serialisable_without_nan(self) -> None:
        analysis = StrainAnalysis.from_result(_result("A4C", -19.0))
        payload = analysis.to_dict()
        text = json.dumps(payload, allow_nan=False)
        assert "definitions" in text

    def test_missing_values_stay_null_not_nan(self) -> None:
        result = _result("A4C", -19.0)
        result = StrainResult(
            longitudinal=result.longitudinal,
            radial=result.radial,
            gls=result.gls,
            segment_strain=result.segment_strain,
            segment_curves=result.segment_curves,
        )
        analysis = StrainAnalysis.from_result(result)
        payload = analysis.to_dict()
        # Fields the worker did not provide must be null, never a NaN literal.
        assert payload["values"]["ess"] is None
        assert payload["values"]["drift"] is None
        json.dumps(payload, allow_nan=False)

    def test_curves_are_opt_in(self) -> None:
        analysis = StrainAnalysis.from_result(_result("A4C", -19.0))
        assert "curves" not in analysis.to_dict()
        with_curves = analysis.to_dict(with_curves=True)
        assert "curves" in with_curves
        assert set(with_curves["curves"]["segments"]) == {"3", "6", "9", "12", "15", "18"}

    def test_view_is_normalised(self) -> None:
        assert StrainAnalysis.from_result(_result("a2c", -18.0)).view == "A2C"
        assert StrainAnalysis.from_result(_result("DAO", -18.0)).view == "A4C"


class TestStudy:
    def _study(self) -> StrainStudy:
        return study_from_results(
            {
                "A4C": _result("A4C", -19.5),
                "A2C": _result(
                    "A2C",
                    -18.0,
                    segments={1: -17.5, 7: -18.0, 13: -19.0, 4: -17.0, 10: -18.5, 16: -18.0},
                ),
                "A3C": _result(
                    "A3C",
                    -12.0,
                    status="review",
                    segments={2: -9.0, 8: -11.0, 14: -13.0, 5: -12.0, 11: -12.5, 17: -14.0},
                ),
            }
        )

    def test_per_view_gls_is_kept(self) -> None:
        study = self._study()
        assert study.view_gls("A4C") == pytest.approx(-19.5)
        assert study.view_gls("A2C") == pytest.approx(-18.0)
        assert study.view_gls("A3C") == pytest.approx(-12.0)

    def test_average_uses_only_valid_views(self) -> None:
        study = self._study()
        assert study.views_valid() == ("A4C", "A2C")
        assert study.gls_average() == pytest.approx(-18.75)
        # Explicit override for the report needs the other mean.
        assert study.gls_average(only_valid=False) == pytest.approx(-16.5)

    def test_average_is_none_without_analysed_views(self) -> None:
        assert StrainStudy().gls_average() is None

    def test_merged_segments_never_invent_a_value(self) -> None:
        study = self._study()
        merged = study.merged_segments()
        assert set(merged) == set(range(1, 19)) - {2, 5, 8, 11, 14, 17}
        assert study.missing_segments() == (2, 5, 8, 11, 14, 17)
        assert merged[13] == pytest.approx(-19.0)
        assert study.segment_sources()[13] == "A2C"

    def test_newest_run_of_a_view_wins(self) -> None:
        study = StrainStudy().with_view(StrainAnalysis.from_result(_result("A4C", -17.0)))
        study = study.with_view(StrainAnalysis.from_result(_result("A4C", -20.0)))
        assert study.view_gls("A4C") == pytest.approx(-20.0)
        assert len(study.analyses) == 1

    def test_study_dict_is_json_serialisable(self) -> None:
        payload = self._study().to_dict(with_curves=True)
        json.dumps(payload, allow_nan=False)
        assert payload["gls_average"] == pytest.approx(-18.75)
        assert "A4C" in payload["analyses"]

    def test_bullseye_slots_only_for_measured_segments(self) -> None:
        slots = self._study().bullseye_segments()
        assert set(slots) <= set(range(1, 19))
        assert 1 in slots and 2 not in slots  # A3C is "review" → excluded


class TestSingleViewEquivalence:
    def test_one_view_average_equals_that_view(self) -> None:
        study = StrainStudy().with_view(StrainAnalysis.from_result(_result("A4C", -19.2)))
        assert study.gls_average() == pytest.approx(-19.2)

    def test_no_analysis_contains_nan_in_exported_segments(self) -> None:
        analysis = StrainAnalysis.from_result(_result("A4C", -19.2))
        for value in analysis.to_dict()["segments"].values():
            if value is not None:
                assert math.isfinite(value)
