"""Myocardial Work domain tests (plan А.9, issue #647).

The math is verified against an analytically known pressure-strain loop: a
linear pressure ramp pinned to valve events and a piecewise-linear strain
curve give GWI/GCW/GWW/GWE as closed-form trapezoid areas, so a regression
shows up as an exact number, not a vibe. The valve-event detector is checked
against synthetic beats with a delayed shortening onset (the ICT), and the
never-raises contract mirrors the phase field's.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.myocardial_work import (
    DEFAULT_LVEDP_MMHG,
    LVESP_SBP_FACTOR,
    WorkResult,
    _integrate_loop,
    build_pressure_curve,
    compute_myocardial_work,
    detect_valve_events,
    myocardial_work_from_analysis,
)

ED = 5
AVC = 35  # ED + 30 frames of systole
N = 65  # one beat: ED at 5, AVc at 35, filling to the end
SBP, DBP = 120.0, 80.0


def _normal_beat(gls: float = -18.0, onset: int = 8, fill_start: int = 40) -> np.ndarray:
    """Strain curve: flat during ICT, linear shortening, plateau, filling."""
    curve = np.zeros(N, dtype=np.float64)
    curve[:onset] = 0.0  # isovolumetric contraction — no shortening yet
    curve[onset : AVC + 1] = np.linspace(0.0, gls, AVC + 1 - onset)
    curve[AVC + 1 : fill_start] = gls  # postsystolic plateau
    curve[fill_start:] = np.linspace(gls, 0.0, N - fill_start)  # filling
    return curve


class TestValveEvents:
    def test_mvc_is_ed_and_avc_is_the_anchor(self) -> None:
        events = detect_valve_events(_normal_beat(), ed_frame=ED, avc_frame=AVC)
        assert events is not None
        assert events.mvc_frame == ED
        assert abs(events.avc_frame - AVC) <= 2  # the strain minimum confirms

    def test_avo_from_shortening_onset(self) -> None:
        events = detect_valve_events(_normal_beat(onset=8), ed_frame=ED, avc_frame=AVC)
        assert events is not None
        assert events.avo_source == "strain"
        # Shortening starts at 8; the 5 %-of-beat threshold lands within 2 frames.
        assert 8 <= events.avo_frame <= 10

    def test_mvo_from_filling_onset(self) -> None:
        events = detect_valve_events(_normal_beat(fill_start=40), ed_frame=ED, avc_frame=AVC)
        assert events is not None
        assert events.mvo_source == "strain"
        assert 40 <= events.mvo_frame <= 42

    def test_flat_systole_falls_back_to_phase_fractions(self) -> None:
        flat = np.zeros(N, dtype=np.float64)
        flat[AVC + 1 :] = 2.0  # some lengthening after AVc
        events = detect_valve_events(flat, ed_frame=ED, avc_frame=AVC)
        assert events is not None
        assert events.avo_source == "phase"  # no shortening to key on
        assert events.mvc_frame < events.avo_frame < events.avc_frame < events.mvo_frame

    def test_too_short_beat_is_rejected(self) -> None:
        assert detect_valve_events(_normal_beat(), ed_frame=0, avc_frame=2) is None

    def test_ed_outside_curve_is_rejected(self) -> None:
        assert detect_valve_events(_normal_beat(), ed_frame=100, avc_frame=AVC) is None

    def test_confidence_drops_for_phase_fallbacks(self) -> None:
        full = detect_valve_events(_normal_beat(), ed_frame=ED, avc_frame=AVC)
        flat = detect_valve_events(np.zeros(N), ed_frame=ED, avc_frame=AVC)
        assert full is not None and flat is not None
        assert full.confidence > flat.confidence


class TestPressureCurve:
    def test_knots_hold_the_method_values(self) -> None:
        events = detect_valve_events(_normal_beat(), ed_frame=ED, avc_frame=AVC)
        assert events is not None
        pressure = build_pressure_curve(N, events, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert pressure.size == N
        assert pressure[events.mvc_frame] == pytest.approx(DEFAULT_LVEDP_MMHG, abs=0.5)
        assert pressure[events.avo_frame] == pytest.approx(DBP, abs=1.0)
        assert pressure[events.avc_frame] == pytest.approx(LVESP_SBP_FACTOR * SBP, abs=1.0)
        assert pressure.min() >= 0.0  # never a negative pressure

    def test_lvesp_is_nine_tenths_of_sbp(self) -> None:
        events = detect_valve_events(_normal_beat(), ed_frame=ED, avc_frame=AVC)
        assert events is not None
        pressure = build_pressure_curve(N, events, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert float(pressure.max()) <= SBP + 1e-6  # peak ≈ SBP, never above


class TestWorkMath:
    def test_normal_beat_yields_the_reference_magnitudes(self) -> None:
        # GLS 18% under ~100 mmHg mean ejection pressure: GWI in the
        # 1500-2500 mmHg% band, GWE near 100 for a clean beat.
        result = compute_myocardial_work(_normal_beat(), ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert result.cycles
        assert 1200.0 <= result.gwi_mmhg_pct <= 2600.0
        assert result.gcw_mmhg_pct > 0.0
        assert result.gww_mmhg_pct < 0.05 * result.gcw_mmhg_pct  # a clean beat wastes ~nothing
        assert result.gwe_percent > 95.0
        assert result.cycles[0].esp_mmhg == pytest.approx(LVESP_SBP_FACTOR * SBP)
        assert result.warnings == ()

    def test_closed_form_on_a_triangular_loop(self) -> None:
        # The integration math against an exact loop: strain falls linearly
        # 0 → -20 over 20 frames while pressure rises linearly 0 → 100; every
        # increment is a rectangle, so GCW = Σ P_i · 1 = 0+5+…+95 = 950.
        strain = np.concatenate([np.linspace(0.0, -20.0, 21), np.linspace(-20.0, 0.0, 21)[1:]])
        pressure = np.linspace(0.0, 100.0, 41)
        # Every systolic step is Δε = -1 at the running pressure mean: the
        # sum is the arithmetic series of P midpoints (0.5·(P[i]+P[i+1])).
        net, constructive, wasted = _integrate_loop(strain, pressure, start=0, end=20)
        expected_gcw = sum(0.5 * (pressure[i] + pressure[i + 1]) for i in range(20))
        assert constructive == pytest.approx(expected_gcw, rel=1e-9)
        assert wasted == pytest.approx(0.0, abs=1e-9)
        assert net == pytest.approx(expected_gcw, rel=1e-9)
        # The return path (lengthening at falling pressure) is pure waste.
        net2, constructive2, wasted2 = _integrate_loop(strain, pressure, start=20, end=40)
        expected_gww = sum(0.5 * (pressure[i] + pressure[i + 1]) for i in range(20, 40))
        assert wasted2 == pytest.approx(expected_gww, rel=1e-9)
        assert constructive2 == pytest.approx(0.0, abs=1e-9)
        assert net2 == pytest.approx(-expected_gww, rel=1e-9)

    def test_mid_systolic_lengthening_produces_wasted_work(self) -> None:
        # Dys-synchrony: the wall lengthens 5 pp under peak pressure before
        # re-shortening — the loop's negative-area segment → GWW > 0, GWE < 100.
        curve = _normal_beat(gls=-20.0, onset=8, fill_start=AVC + 1)
        bob = curve.copy()
        bob[20:25] = np.linspace(-10.0, 2.0, 5)  # lengthening under peak P
        bob[25 : AVC + 1] = np.linspace(2.0, -20.0, AVC + 1 - 25)  # re-shortening
        pathological = compute_myocardial_work(bob, ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        clean = compute_myocardial_work(_normal_beat(gls=-20.0), ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert pathological.gww_mmhg_pct is not None and pathological.gww_mmhg_pct > 0.0
        assert pathological.gwe_percent is not None and clean.gwe_percent is not None
        assert pathological.gwe_percent < clean.gwe_percent
        assert pathological.gwe_percent < 95.0

    def test_gwe_is_scale_invariant(self) -> None:
        """A global pressure-amplitude error cancels in GWE by construction."""
        curve = _normal_beat()
        full = compute_myocardial_work(curve, ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        misread = compute_myocardial_work(curve, ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP * 1.25, dbp_mmhg=DBP * 1.25)
        assert full.gwe_percent is not None and misread.gwe_percent is not None
        assert misread.gwe_percent == pytest.approx(full.gwe_percent, abs=2.0)
        # …but the absolute work does not: GWI scales with the pressure.
        assert misread.gwi_mmhg_pct is not None and full.gwi_mmhg_pct is not None
        assert misread.gwi_mmhg_pct > full.gwi_mmhg_pct

    def test_ess_and_edp_stored_on_the_cycle(self) -> None:
        result = compute_myocardial_work(_normal_beat(), ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        cycle = result.cycles[0]
        assert cycle.esp_mmhg == pytest.approx(108.0)  # 0.9 · 120
        assert cycle.edp_mmhg == pytest.approx(DEFAULT_LVEDP_MMHG)


class TestNeverRaises:
    def test_missing_blood_pressure_ranges_warn(self) -> None:
        result = compute_myocardial_work(_normal_beat(), ed_frame=ED, avc_frame=AVC, sbp_mmhg=20.0, dbp_mmhg=200.0)
        assert result.cycles == ()
        assert "systolic_out_of_range" in result.warnings
        assert "diastolic_out_of_range" in result.warnings
        assert result.gwi_mmhg_pct is None

    def test_dbp_not_below_sbp_is_refused(self) -> None:
        result = compute_myocardial_work(_normal_beat(), ed_frame=ED, avc_frame=AVC, sbp_mmhg=80.0, dbp_mmhg=80.0)
        assert "diastolic_not_below_systolic" in result.warnings
        assert result.cycles == ()

    def test_flat_strain_yields_no_cycles(self) -> None:
        result = compute_myocardial_work(np.zeros(N), ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert result.cycles == ()
        assert "no_shortening" in result.warnings

    def test_tiny_curve_yields_no_strain(self) -> None:
        result = compute_myocardial_work(np.zeros(3), ed_frame=0, avc_frame=2, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert result.cycles == ()
        assert "no_strain" in result.warnings

    def test_invalid_pressure_refuses_before_any_loop_is_built(self) -> None:
        result = compute_myocardial_work(np.full(N, np.nan), ed_frame=ED, avc_frame=AVC, sbp_mmhg=20.0, dbp_mmhg=200.0)
        # The pressure gate fires before the (all-NaN) strain is even looked at.
        assert result.cycles == ()
        assert result.warnings == ("diastolic_not_below_systolic", "diastolic_out_of_range", "systolic_out_of_range")

    def test_garbage_input_degrades_without_raising(self) -> None:
        curve = np.full(N, np.nan)
        result = compute_myocardial_work(curve, ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert isinstance(result, WorkResult)

    def test_nan_holes_are_interpolated_and_reported(self) -> None:
        curve = _normal_beat()
        curve[12:15] = np.nan
        result = compute_myocardial_work(curve, ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert result.cycles
        assert "strain_gaps_interpolated" in result.warnings

    def test_low_gwe_is_flagged(self) -> None:
        curve = _normal_beat(gls=-20.0, onset=8, fill_start=AVC + 1)
        curve[20:25] = np.linspace(-10.0, 2.0, 5)
        curve[25 : AVC + 1] = np.linspace(2.0, -20.0, AVC + 1 - 25)
        result = compute_myocardial_work(curve, ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert "low_work_efficiency" in result.warnings
        assert result.gwe_percent is not None and result.gwe_percent < 80.0


class TestSerializationAndBridge:
    def test_round_trip(self) -> None:
        result = compute_myocardial_work(_normal_beat(), ed_frame=ED, avc_frame=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        restored = WorkResult.from_dict(result.to_dict())
        assert restored.gwi_mmhg_pct == result.gwi_mmhg_pct
        assert restored.gwe_percent == result.gwe_percent
        assert restored.warnings == result.warnings
        assert restored.cycles[0].mvo_frame == result.cycles[0].mvo_frame

    def test_empty_result_round_trips(self) -> None:
        empty = WorkResult(warnings=("no_strain",))
        restored = WorkResult.from_dict(empty.to_dict())
        assert restored.cycles == ()
        assert restored.gwi_mmhg_pct is None
        assert restored.warnings == ("no_strain",)

    def test_bridge_from_analysis_fields(self) -> None:
        result = myocardial_work_from_analysis(
            _normal_beat(),
            ed_index=ED,
            avc_index=AVC,
            sbp_mmhg=SBP,
            dbp_mmhg=DBP,
        )
        assert result.cycles
        assert result.gwe_percent is not None and result.gwe_percent > 95.0

    def test_bridge_without_curve_warns(self) -> None:
        result = myocardial_work_from_analysis(None, ed_index=ED, avc_index=AVC, sbp_mmhg=SBP, dbp_mmhg=DBP)
        assert result.cycles == ()
        assert result.warnings == ("no_strain",)
