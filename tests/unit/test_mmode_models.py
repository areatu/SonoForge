import dataclasses

import pytest

from echo_personal_tool.domain.models.mmode import (
    MModeCaliperMeasurement,
    MModeScanLine,
    MModeState,
)


def test_mmode_scan_line_creation() -> None:
    line = MModeScanLine(start=(10.0, 20.0), end=(100.0, 200.0))
    assert line.start == (10.0, 20.0)
    assert line.end == (100.0, 200.0)
    assert line.num_samples == 256


def test_mmode_scan_line_custom_samples() -> None:
    line = MModeScanLine(start=(0.0, 0.0), end=(50.0, 50.0), num_samples=128)
    assert line.num_samples == 128


def test_mmode_state_defaults() -> None:
    state = MModeState()
    assert state.active is False
    assert state.scan_line is None
    assert state.buffer_width == 512
    assert state.sweep_x == 0


def test_mmode_state_active() -> None:
    line = MModeScanLine(start=(10.0, 20.0), end=(100.0, 200.0))
    state = MModeState(active=True, scan_line=line)
    assert state.active is True
    assert state.scan_line is line


def test_mmode_caliper_distance() -> None:
    cal = MModeCaliperMeasurement(kind="distance", start=(10.0, 5.0), end=(10.0, 50.0))
    assert cal.kind == "distance"
    assert cal.value_mm is None


def test_mmode_caliper_with_values() -> None:
    cal = MModeCaliperMeasurement(kind="time", start=(10.0, 0.0), end=(100.0, 0.0), value_ms=320.0)
    assert cal.value_ms == 320.0


def test_mmode_caliper_frozen() -> None:
    cal = MModeCaliperMeasurement(kind="distance", start=(0.0, 0.0), end=(10.0, 10.0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        cal.kind = "time"  # type: ignore[misc]


def test_teichholz_mmode_result_creation() -> None:
    from echo_personal_tool.domain.models.mmode import TeichholzMModeResult

    result = TeichholzMModeResult(
        ivsd_mm=10.0, lvidd_mm=45.0, lvpwd_mm=9.0, edv_ml=120.0,
    )
    assert result.ivsd_mm == 10.0
    assert result.lvidd_mm == 45.0
    assert result.lvpwd_mm == 9.0
    assert result.edv_ml == 120.0
    assert result.esv_ml is None
    assert result.lvef_percent is None
    assert result.rwt is None
    assert result.lvm_g is None
    assert result.lvmi_g_m2 is None


def test_teichholz_mmode_result_populated() -> None:
    from echo_personal_tool.domain.models.mmode import TeichholzMModeResult

    result = TeichholzMModeResult(
        ivsd_mm=11.0, lvidd_mm=48.0, lvpwd_mm=10.0, edv_ml=135.0,
        esv_ml=50.0, lvef_percent=63.0, rwt=0.42, lvm_g=180.0, lvmi_g_m2=95.0,
    )
    assert result.esv_ml == 50.0
    assert result.lvef_percent == 63.0
    assert result.lvmi_g_m2 == 95.0


def test_teichholz_mmode_result_frozen() -> None:
    from echo_personal_tool.domain.models.mmode import TeichholzMModeResult

    result = TeichholzMModeResult(ivsd_mm=10.0, lvidd_mm=45.0, lvpwd_mm=9.0, edv_ml=120.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.edv_ml = 200.0  # type: ignore[misc]
