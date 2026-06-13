"""Domain result models for computed echocardiography measurements."""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement


@dataclass(frozen=True)
class DopplerResults:
    """Computed Doppler indices; fields are set only when computable."""

    e_cm_s: float | None = None
    a_cm_s: float | None = None
    e_a_ratio: float | None = None
    dt_ms: float | None = None
    ivrt_ms: float | None = None
    at_ms: float | None = None
    e_prime_sept_cm_s: float | None = None
    e_prime_lat_cm_s: float | None = None
    e_prime_avg_cm_s: float | None = None
    e_over_e_prime: float | None = None
    vti_cm: float | None = None
    vpeak_cm_s: float | None = None
    vmean_cm_s: float | None = None
    pgpeak_mmhg: float | None = None
    pgmean_mmhg: float | None = None


@dataclass(frozen=True)
class LvViewMetrics:
    length_ed_mm: float | None = None
    length_es_mm: float | None = None
    edv_ml: float | None = None
    esv_ml: float | None = None


@dataclass(frozen=True)
class LvefResult:
    a4c: LvViewMetrics | None = None
    a2c: LvViewMetrics | None = None
    lvef_percent: float | None = None
    method: str | None = None  # simpson_monoplan / simpson_biplan


@dataclass(frozen=True)
class TeichholzResult:
    edv_ml: float
    esv_ml: float
    lvef_percent: float


@dataclass(frozen=True)
class LaVolumeResult:
    """Left atrial area-length result; fields set only when computable."""

    volume_ml: float | None = None
    area_cm2: float | None = None
    length_cm: float | None = None
    method: str = "area_length"


@dataclass(frozen=True)
class MeasurementSnapshot:
    doppler: DopplerResults | None = None
    lvef: LvefResult | None = None
    teichholz: TeichholzResult | None = None
    la_volume: LaVolumeResult | None = None
    linear_measurements: tuple[LinearMeasurement, ...] = ()
    spacing_calibrated: bool = True
