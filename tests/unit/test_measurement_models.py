"""Unit tests for measurement result domain models."""

from __future__ import annotations

import dataclasses

import pytest

from echo_personal_tool.domain.models import (
    ChamberSimpsonResult,
    DopplerResults,
    IndexedMeasurements,
    LaVolumeResult,
    LinearMeasurement,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
    TeichholzResult,
)
from echo_personal_tool.domain.models.measurements import PlanimeterResult


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


# ── LaVolumeResult ─────────────────────────────────────────────────


class TestLaVolumeResult:
    def test_defaults(self) -> None:
        result = LaVolumeResult()
        assert result.volume_ml is None
        assert result.area_cm2 is None
        assert result.length_cm is None
        assert result.method == "area_length"

    def test_populated(self) -> None:
        result = LaVolumeResult(volume_ml=55.0, area_cm2=18.0, length_cm=4.5)
        assert result.volume_ml == 55.0
        assert result.area_cm2 == 18.0
        assert result.length_cm == 4.5

    def test_frozen(self) -> None:
        result = LaVolumeResult()
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.volume_ml = 100.0  # type: ignore[misc]


# ── ChamberSimpsonResult ───────────────────────────────────────────


class TestChamberSimpsonResult:
    def test_minimal(self) -> None:
        result = ChamberSimpsonResult(chamber="LA")
        assert result.chamber == "LA"
        assert result.a4c is None
        assert result.a2c is None
        assert result.area_cm2 is None
        assert result.max_volume_ml is None
        assert result.ef_percent is None
        assert result.method is None

    def test_populated(self) -> None:
        result = ChamberSimpsonResult(
            chamber="LV",
            a4c=LvViewMetrics(edv_ml=120.0, esv_ml=45.0),
            a2c=LvViewMetrics(edv_ml=115.0, esv_ml=42.0),
            area_cm2=25.0,
            max_volume_ml=120.0,
            ef_percent=62.5,
            method="simpson_biplan",
        )
        assert result.chamber == "LV"
        assert result.a4c.edv_ml == 120.0
        assert result.ef_percent == 62.5

    def test_frozen(self) -> None:
        result = ChamberSimpsonResult(chamber="RA")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.chamber = "RV"  # type: ignore[misc]


# ── IndexedMeasurements ────────────────────────────────────────────


class TestIndexedMeasurements:
    def test_minimal(self) -> None:
        result = IndexedMeasurements(bsa_m2=1.8)
        assert result.bsa_m2 == 1.8
        assert result.simpson_edvi_ml_m2 is None
        assert result.lvmi_g_m2 is None
        assert result.linear_index_mm_m2 == ()

    def test_populated(self) -> None:
        result = IndexedMeasurements(
            bsa_m2=1.9,
            simpson_edvi_ml_m2=65.0,
            simpson_esvi_ml_m2=25.0,
            lvmi_g_m2=95.0,
            linear_index_mm_m2=(("IVSd", 5.0), ("LVIDd", 25.0)),
        )
        assert result.bsa_m2 == 1.9
        assert result.simpson_edvi_ml_m2 == 65.0
        assert result.lvmi_g_m2 == 95.0
        assert len(result.linear_index_mm_m2) == 2

    def test_frozen(self) -> None:
        result = IndexedMeasurements(bsa_m2=1.8)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.bsa_m2 = 2.0  # type: ignore[misc]


# ── PlanimeterResult ───────────────────────────────────────────────


class TestPlanimeterResult:
    def test_creation(self) -> None:
        result = PlanimeterResult(label="LA", kind="area", value=18.5, unit="cm2")
        assert result.label == "LA"
        assert result.kind == "area"
        assert result.value == 18.5
        assert result.unit == "cm2"

    def test_frozen(self) -> None:
        result = PlanimeterResult(label="LV", kind="volume", value=120.0, unit="ml")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.value = 200.0  # type: ignore[misc]


# ── MeasurementSnapshot additional fields ──────────────────────────


class TestMeasurementSnapshotExtended:
    def test_with_la_volume(self) -> None:
        la = LaVolumeResult(volume_ml=55.0)
        snapshot = MeasurementSnapshot(la_volume=la)
        assert snapshot.la_volume.volume_ml == 55.0

    def test_with_chamber_simpson(self) -> None:
        simpson = ChamberSimpsonResult(chamber="LA", ef_percent=55.0)
        snapshot = MeasurementSnapshot(la_simpson=simpson)
        assert snapshot.la_simpson.chamber == "LA"
        assert snapshot.la_simpson.ef_percent == 55.0

    def test_with_indexed(self) -> None:
        indexed = IndexedMeasurements(bsa_m2=1.8, lvmi_g_m2=90.0)
        snapshot = MeasurementSnapshot(indexed=indexed)
        assert snapshot.indexed.bsa_m2 == 1.8

    def test_with_planimeter(self) -> None:
        p1 = PlanimeterResult(label="LA", kind="area", value=18.0, unit="cm2")
        p2 = PlanimeterResult(label="LV", kind="volume", value=120.0, unit="ml")
        snapshot = MeasurementSnapshot(planimeter=(p1, p2))
        assert len(snapshot.planimeter) == 2

    def test_diastology_and_rv_fac(self) -> None:
        snapshot = MeasurementSnapshot(
            diastology_grade="Grade II",
            rv_fac_percent=45.0,
            lvm_g=180.0,
            rwt=0.42,
        )
        assert snapshot.diastology_grade == "Grade II"
        assert snapshot.rv_fac_percent == 45.0
        assert snapshot.lvm_g == 180.0
        assert snapshot.rwt == 0.42

    def test_height_weight(self) -> None:
        snapshot = MeasurementSnapshot(height_cm=175.0, weight_kg=70.0)
        assert snapshot.height_cm == 175.0
        assert snapshot.weight_kg == 70.0
