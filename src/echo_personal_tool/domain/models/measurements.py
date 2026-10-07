"""Domain result models for computed echocardiography measurements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement

if TYPE_CHECKING:  # runtime import would be circular (calculators → calculations → this module)
    from echo_personal_tool.domain.calculators.models import CalculationsSnapshot


@dataclass(frozen=True)
class DopplerFlowResult:
    """Computed spectral-Doppler values for one valve or flow region.

    When a parameter was measured more than once (D-23), the reported value is
    the mean of the most recent measurements (``doppler_repeats.REPORT_WINDOW``)
    and the ``*_repeats`` counters tell how many measurements exist in total.
    """

    site: str
    vmax_cm_s: float | None = None
    pgmax_mmhg: float | None = None
    vti_cm: float | None = None
    vmean_cm_s: float | None = None
    pgmean_mmhg: float | None = None
    #: Number of stored Vmax measurements of this site (``0`` when the value
    #: came from a trace fallback).
    vmax_repeats: int = 0
    #: Number of stored VTI traces of this site that were averaged.
    vti_repeats: int = 0
    #: Acquisition mode of the newest measurement of this site
    #: (``CW`` | ``PW`` | ``TDI``, empty when unknown).  Display-only: it
    #: selects m/s vs cm/s for the velocities, storage stays in cm/s.
    mode: str = ""


@dataclass(frozen=True)
class DopplerResults:
    """Computed Doppler indices; fields are set only when computable.

    ``flow_results`` is the authoritative valve/flow-specific representation.
    The historical generic fields remain populated for compatibility with old
    persisted data and integrations, but new UI code must label them Vmax and
    PGmax (never Vpeak/PGpeak).
    """

    e_cm_s: float | None = None
    a_cm_s: float | None = None
    e_a_ratio: float | None = None
    dt_ms: float | None = None
    ivrt_ms: float | None = None
    at_ms: float | None = None
    et_ms: float | None = None
    e_prime_sept_cm_s: float | None = None
    e_prime_lat_cm_s: float | None = None
    e_prime_avg_cm_s: float | None = None
    e_over_e_prime: float | None = None
    e_over_e_prime_sept: float | None = None
    e_over_e_prime_lat: float | None = None
    e_prime_over_a_prime: float | None = None
    a_prime_sept_cm_s: float | None = None
    a_prime_lat_cm_s: float | None = None
    s_prime_sept_cm_s: float | None = None
    s_prime_lat_cm_s: float | None = None
    s_prime_rv_cm_s: float | None = None
    tr_vmax_cm_s: float | None = None
    vti_cm: float | None = None
    vpeak_cm_s: float | None = None
    vmean_cm_s: float | None = None
    pgpeak_mmhg: float | None = None
    pgmean_mmhg: float | None = None
    # Valve/flow-specific values used by current overlays, worksheets/reports.
    flow_results: tuple[DopplerFlowResult, ...] = ()
    mv_pht_ms: float | None = None
    tv_pht_ms: float | None = None
    ar_pht_ms: float | None = None
    pr_pht_ms: float | None = None
    av_at_ms: float | None = None
    av_et_ms: float | None = None
    rvot_at_ms: float | None = None
    #: Δt of the MR jet rising 1 → 3 m/s and of the TR jet rising 1 → 2 m/s
    #: (``MR dP/dt`` / ``TR dP/dt`` intervals), inputs of the dP/dt calculator.
    mr_dpdt_ms: float | None = None
    tr_dpdt_ms: float | None = None

    def flow(self, site: str) -> DopplerFlowResult | None:
        """Return one site result using case-insensitive lookup."""

        wanted = site.strip().upper()
        return next((item for item in self.flow_results if item.site.upper() == wanted), None)


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
    edv_bi_ml: float | None = None
    esv_bi_ml: float | None = None


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
class ChamberSimpsonResult:
    """Simpson monoplane/biplane volume metrics for LA, RA, or RV."""

    chamber: str
    a4c: LvViewMetrics | None = None
    a2c: LvViewMetrics | None = None
    area_cm2: float | None = None
    max_volume_ml: float | None = None
    ef_percent: float | None = None
    method: str | None = None


@dataclass(frozen=True)
class IndexedMeasurements:
    """BSA-normalized volumes (mL/m²) and linear sizes (mm/m²)."""

    bsa_m2: float
    simpson_edvi_ml_m2: float | None = None
    simpson_esvi_ml_m2: float | None = None
    teichholz_edvi_ml_m2: float | None = None
    teichholz_esvi_ml_m2: float | None = None
    lav_4c_index_ml_m2: float | None = None
    lav_bi_index_ml_m2: float | None = None
    lav_area_length_index_ml_m2: float | None = None
    rav_index_ml_m2: float | None = None
    lvmi_g_m2: float | None = None
    simpson_a4c_edvi_ml_m2: float | None = None
    simpson_a4c_esvi_ml_m2: float | None = None
    simpson_a2c_edvi_ml_m2: float | None = None
    simpson_a2c_esvi_ml_m2: float | None = None
    linear_index_mm_m2: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class StrainReport:
    """Study-level speckle-tracking result as the protocol needs to state it.

    The strain window keeps the full :class:`StrainStudy` (curves, kernels,
    per-segment records); a protocol line needs far less, but it must never
    show a number without the method and the quality that produced it. This
    record is therefore the *reporting projection* of the study: per-view GLS
    with the QC status of each view, the average over the views that passed QC,
    and the declarations (definition, layer, AVC source) that make the number
    comparable with a vendor report (plan §3.1, §5.3 п.6).

    Every field is a plain tuple/scalar so the snapshot stays comparable with
    ``==`` — the viewer refreshes on snapshot change.
    """

    #: ``(view, GLS %)`` for every analysed view, in ``A4C, A2C, A3C`` order.
    gls_by_view: tuple[tuple[str, float], ...] = ()
    #: ``(view, "valid"|"review"|"invalid")`` — the status travels with the value.
    qc_by_view: tuple[tuple[str, str], ...] = ()
    #: Mean of the per-view GLS values that passed QC (``GLS_AV``); ``None``
    #: when no view is valid — never a silent average over rejected views.
    gls_average: float | None = None
    #: Views that entered ``gls_average``.
    views_valid: tuple[str, ...] = ()
    #: Segment model behind the numbers, e.g. ``"AHA-18"``. The report renders
    #: the method line from this, so switching the interface language
    #: re-translates the protocol instead of freezing the wording that happened
    #: to be active when the clip was analysed.
    segmentation: str = ""
    #: Where end-systole came from per view, e.g. ``(("A4C", "ecg"),)``.
    avc_source_by_view: tuple[tuple[str, str], ...] = ()
    #: Segments the analysed views could not measure (never fabricated).
    segments_missing: int = 0
    #: Whether the ED contour was drawn by hand ("gold") or produced as a draft.
    contour_source: str = "manual"

    @property
    def has_values(self) -> bool:
        return bool(self.gls_by_view)


@dataclass(frozen=True)
class PlanimeterResult:
    label: str
    kind: str  # area | volume
    value: float
    unit: str


@dataclass(frozen=True)
class MeasurementSnapshot:
    doppler: DopplerResults | None = None
    display_doppler: DopplerResults | None = None
    lvef: LvefResult | None = None
    teichholz: TeichholzResult | None = None
    la_volume: LaVolumeResult | None = None
    la_simpson: ChamberSimpsonResult | None = None
    ra_simpson: ChamberSimpsonResult | None = None
    rv_simpson: ChamberSimpsonResult | None = None
    lvm_g: float | None = None
    rwt: float | None = None
    rv_fac_percent: float | None = None
    diastology_grade: str | None = None
    linear_measurements: tuple[LinearMeasurement, ...] = ()
    spacing_calibrated: bool = True
    height_cm: float | None = None
    weight_kg: float | None = None
    indexed: IndexedMeasurements | None = None
    planimeter: tuple[PlanimeterResult, ...] = ()
    vessel_measurements: tuple[VesselMeasurement, ...] = ()
    #: Speckle-tracking result of the study (plan §5.3 п.6). ``None`` until a
    #: view has been analysed — the report then simply has no strain section.
    strain: StrainReport | None = None
    #: Calculators (Э11) evaluated over study-wide inputs with provenance.
    #: ``None`` when nothing could be resolved; outputs without inputs stay empty.
    calculations: CalculationsSnapshot | None = None
