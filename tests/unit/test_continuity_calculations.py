"""Continuity-equation formulas (Э11а) on hand-checkable etalons.

Worked example used throughout (computable by hand, matches the textbook
continuity example): LVOTd 2.0 cm → CSA π·1² = 3.1416 cm²; LVOT VTI 20 cm →
SV 62.83 mL; HR 70 → CO 4.398 L/min; AV VTI 100 cm → AVA 0.628 cm², DVI 0.20.
"""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.domain.calculations.continuity import (
    ava_continuity_cm2,
    cardiac_output_l_min,
    dimensionless_index,
    indexed_to_bsa,
    lvot_area_cm2,
    stroke_volume_ml,
)


def test_lvot_area_is_circle_of_the_diameter() -> None:
    assert lvot_area_cm2(2.0) == pytest.approx(math.pi)
    assert lvot_area_cm2(2.2) == pytest.approx(3.801, abs=1e-3)


def test_stroke_volume_and_cardiac_output_etalon() -> None:
    sv = stroke_volume_ml(lvot_area_cm2(2.0), 20.0)
    assert sv == pytest.approx(62.83, abs=0.01)
    co = cardiac_output_l_min(sv, 70.0)
    assert co == pytest.approx(4.398, abs=1e-3)
    assert indexed_to_bsa(co, 1.9) == pytest.approx(2.315, abs=1e-3)
    assert indexed_to_bsa(sv, 1.9) == pytest.approx(33.07, abs=0.01)


def test_aortic_valve_area_vti_and_vmax_forms() -> None:
    area = lvot_area_cm2(2.0)
    assert ava_continuity_cm2(area, 20.0, 100.0) == pytest.approx(0.628, abs=1e-3)
    # Vmax form: same unit for both velocities (cm/s here).
    assert ava_continuity_cm2(area, 100.0, 450.0) == pytest.approx(0.698, abs=1e-3)
    assert dimensionless_index(20.0, 100.0) == pytest.approx(0.20)
    assert dimensionless_index(100.0, 450.0) == pytest.approx(0.222, abs=1e-3)


def test_severe_as_example_from_guideline_thresholds() -> None:
    """LVOTd 2.1 cm, LVOT VTI 18 cm, AV VTI 95 cm → AVA ≈ 0.66 cm² (< 1.0 severe)."""
    ava = ava_continuity_cm2(lvot_area_cm2(2.1), 18.0, 95.0)
    assert ava == pytest.approx(0.656, abs=1e-3)
    assert ava < 1.0
    assert dimensionless_index(18.0, 95.0) < 0.25


@pytest.mark.parametrize("bad", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_missing_or_meaningless_inputs_give_none(bad) -> None:
    assert lvot_area_cm2(bad) is None
    assert stroke_volume_ml(bad, 20.0) is None
    assert stroke_volume_ml(3.14, bad) is None
    assert cardiac_output_l_min(60.0, bad) is None
    assert indexed_to_bsa(60.0, bad) is None
    assert ava_continuity_cm2(3.14, 20.0, bad) is None
    assert dimensionless_index(bad, 100.0) is None
