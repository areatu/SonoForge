"""Tests for Teichholz M-mode LV function calculation."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.teichholz_mmode import compute_teichholz_from_mmode


class TestTeichholzMMode:
    def test_basic_calculation(self) -> None:
        result = compute_teichholz_from_mmode(
            ivsd_mm=10.0,
            lvidd_mm=50.0,
            lvpwd_mm=10.0,
            lvesd_mm=35.0,
            height_cm=170.0,
            weight_kg=70.0,
        )
        assert result.ivsd_mm == 10.0
        assert result.lvidd_mm == 50.0
        assert result.lvpwd_mm == 10.0
        assert result.edv_ml > 0
        assert result.esv_ml is not None
        assert result.esv_ml > 0
        assert result.lvef_percent is not None
        assert 0 < result.lvef_percent < 100
        assert result.rwt is not None
        assert result.lvm_g > 0
        assert result.lvmi_g_m2 is not None
        assert result.lvmi_g_m2 > 0

    def test_ed_only(self) -> None:
        result = compute_teichholz_from_mmode(
            ivsd_mm=8.0,
            lvidd_mm=45.0,
            lvpwd_mm=8.0,
        )
        assert result.edv_ml > 0
        assert result.esv_ml is None
        assert result.lvef_percent is None

    def test_teichholz_volume_formula(self) -> None:
        """Verify Teichholz cube formula: V = 7/(2.4+D) * D^3."""
        result = compute_teichholz_from_mmode(
            ivsd_mm=10.0,
            lvidd_mm=50.0,
            lvpwd_mm=10.0,
        )
        # D = 5.0 cm, V = 7/(2.4+5.0) * 5.0^3 = 7/7.4 * 125 = 118.2
        assert abs(result.edv_ml - 118.2) < 0.1

    def test_rwt_formula(self) -> None:
        """Verify RWT = 2*LVPWd/LVEDD."""
        result = compute_teichholz_from_mmode(
            ivsd_mm=10.0,
            lvidd_mm=50.0,
            lvpwd_mm=10.0,
        )
        # RWT = 2*10/50 = 0.4
        assert abs(result.rwt - 0.4) < 0.01

    def test_lvm_formula(self) -> None:
        """Verify LV mass ASE cube formula."""
        result = compute_teichholz_from_mmode(
            ivsd_mm=10.0,
            lvidd_mm=50.0,
            lvpwd_mm=10.0,
        )
        # LVM = 0.8 * 1.04 * ((1+5+1)^3 - 5^3) + 0.6
        # = 0.8 * 1.04 * (343 - 125) + 0.6
        # = 0.8 * 1.04 * 218 + 0.6 = 182.0
        assert abs(result.lvm_g - 182.0) < 0.1
