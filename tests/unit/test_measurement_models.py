"""Unit tests for measurement result domain models."""

from __future__ import annotations

import dataclasses

import pytest

from echo_personal_tool.domain.models import (
    DopplerResults,
    LinearMeasurement,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
    TeichholzResult,
)


def test_doppler_results_defaults() -> None:
    results = DopplerResults()

    assert results.e_cm_s is None
    assert results.a_cm_s is None
    assert results.e_a_ratio is None
    assert results.dt_ms is None
    assert results.ivrt_ms is None
    assert results.at_ms is None
    assert results.e_prime_sept_cm_s is None
    assert results.e_prime_lat_cm_s is None
    assert results.e_prime_avg_cm_s is None
    assert results.e_over_e_prime is None
    assert results.vti_cm is None
    assert results.vpeak_cm_s is None
    assert results.vmean_cm_s is None
    assert results.pgpeak_mmhg is None
    assert results.pgmean_mmhg is None


def test_doppler_results_populated() -> None:
    results = DopplerResults(
        e_cm_s=85.0,
        a_cm_s=60.0,
        e_a_ratio=1.42,
        dt_ms=180.0,
        ivrt_ms=80.0,
        at_ms=120.0,
        e_prime_sept_cm_s=8.0,
        e_prime_lat_cm_s=10.0,
        e_prime_avg_cm_s=9.0,
        e_over_e_prime=9.44,
        vti_cm=22.5,
        vpeak_cm_s=250.0,
        vmean_cm_s=150.0,
        pgpeak_mmhg=25.0,
        pgmean_mmhg=12.0,
    )

    assert results.e_cm_s == 85.0
    assert results.pgmean_mmhg == 12.0


def test_lv_view_metrics_defaults() -> None:
    metrics = LvViewMetrics()
    assert metrics.length_ed_mm is None
    assert metrics.length_es_mm is None
    assert metrics.edv_ml is None
    assert metrics.esv_ml is None


def test_lvef_result_partial_ed_only() -> None:
    result = LvefResult(
        a4c=LvViewMetrics(length_ed_mm=82.0, edv_ml=124.5),
        lvef_percent=None,
        method=None,
    )
    assert result.a4c is not None
    assert result.a4c.edv_ml == 124.5
    assert result.lvef_percent is None
    assert result.a2c is None


def test_lvef_result_creation() -> None:
    result = LvefResult(
        a4c=LvViewMetrics(edv_ml=120.0, esv_ml=45.0),
        lvef_percent=62.5,
        method="simpson_monoplan",
    )
    assert result.a4c is not None
    assert result.a4c.edv_ml == 120.0
    assert result.a4c.esv_ml == 45.0
    assert result.lvef_percent == 62.5


def test_teichholz_result_creation() -> None:
    result = TeichholzResult(edv_ml=110.0, esv_ml=50.0, lvef_percent=54.5)

    assert result.edv_ml == 110.0
    assert result.esv_ml == 50.0
    assert result.lvef_percent == 54.5


def test_measurement_snapshot_defaults() -> None:
    snapshot = MeasurementSnapshot()

    assert snapshot.doppler is None
    assert snapshot.lvef is None
    assert snapshot.teichholz is None
    assert snapshot.la_volume is None
    assert snapshot.linear_measurements == ()


def test_measurement_snapshot_populated() -> None:
    doppler = DopplerResults(e_cm_s=90.0, a_cm_s=55.0)
    lvef = LvefResult(
        a4c=LvViewMetrics(edv_ml=130.0, esv_ml=40.0),
        lvef_percent=69.2,
        method="simpson_biplan",
    )
    teichholz = TeichholzResult(edv_ml=125.0, esv_ml=55.0, lvef_percent=56.0)
    linear = LinearMeasurement(label="IVSd", pixel_length=100.0, millimeter_length=9.5)

    snapshot = MeasurementSnapshot(
        doppler=doppler,
        lvef=lvef,
        teichholz=teichholz,
        linear_measurements=(linear,),
    )

    assert snapshot.doppler is doppler
    assert snapshot.lvef is lvef
    assert snapshot.teichholz is teichholz
    assert snapshot.linear_measurements == (linear,)


@pytest.mark.parametrize(
    "instance",
    [
        DopplerResults(e_cm_s=80.0),
        LvefResult(
            a4c=LvViewMetrics(edv_ml=100.0, esv_ml=40.0),
            lvef_percent=60.0,
            method="simpson_monoplan",
        ),
        TeichholzResult(edv_ml=100.0, esv_ml=40.0, lvef_percent=60.0),
        MeasurementSnapshot(),
    ],
)
def test_measurement_models_are_frozen(instance: object) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.doppler = None  # type: ignore[attr-defined]
