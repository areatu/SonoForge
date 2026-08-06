"""Tests for ASE reference norm checks."""

from __future__ import annotations

from echo_personal_tool.domain.services.ase_reference_norms import (
    LAVI_MLM2,
    LV_IVSD_MM,
    LVMI_GM2,
    is_outside_norm,
    should_show_indexed_linear,
)


def test_is_outside_norm_two_sided() -> None:
    assert is_outside_norm(5.0, LV_IVSD_MM)
    assert is_outside_norm(12.0, LV_IVSD_MM)
    assert not is_outside_norm(8.0, LV_IVSD_MM)


def test_lavi_upper_limit() -> None:
    assert not is_outside_norm(30.0, LAVI_MLM2)
    assert is_outside_norm(40.0, LAVI_MLM2)


def test_should_show_aorta_index_when_annulus_large() -> None:
    assert should_show_indexed_linear("Annulus", 40.0)
    assert not should_show_indexed_linear("Annulus", 24.0)


def test_lvmi_upper_limit() -> None:
    assert is_outside_norm(150.0, LVMI_GM2)
