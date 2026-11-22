"""Non-invasive Myocardial Work from pressure-strain loops (plan А.9, issue #647).

The Eckert/Russell MW method: the ECG's only contribution to the
pressure-strain loop was *timing* — when the valves opened and closed. The
А.3 phase field through the А.4 router supplies exactly that timing from the
image (ED ≈ MVc, the mechanical ES ≈ AVc), so the loop can be built with no
ECG at all: a normalized LV pressure template is pinned to the four valve
events, its amplitude comes from the cuff brachial pressure
(LVESP = 0.9·SBP, the method's own approximation), and work is the
pressure-strain integral.

Definitions (mmHg·% — strain in percent):

* **GWI** — the net loop area, GCW − GWW;
* **GCW** — constructive work: the ``−P·dε`` sum over shortening segments
  (strain becoming more negative while pressure is high);
* **GWW** — wasted work: the ``P·dε`` sum over lengthening segments
  (strain increasing under non-trivial pressure — postsystolic shortening
  followed by stretch, dys-synchrony);
* **GWE** — 100·GCW / (GCW + GWW): the work efficiency, scale-invariant (a
  global error in the pressure amplitude cancels; only the *shape* of P(t)
  matters).

Honest limits, stated where a vendor would state them: the pressure curve is
a cuff-pressure-anchored template, not a measured LV pressure; LVEDP is a
fixed 5 mmHg assumption (it shifts GWI/GCW/GWW by an offset, GWE not at
all); valve events are image-derived estimates with a stated source, not
Doppler-measured times. A bad input never raises: the result carries
warnings, and without strain, a cycle, or plausible cuff pressure the work
is simply ``None`` — never a fabricated number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import PchipInterpolator

SCHEMA_VERSION = "1.0"

#: LV pressure at MVc (the method's LVEDP assumption; see module docstring).
DEFAULT_LVEDP_MMHG = 5.0
#: LV pressure at AVc ≈ end-systolic pressure (Russell 2019).
LVESP_SBP_FACTOR = 0.9
#: Fallback φ-fractions for the isovolumetric intervals when the strain
#: morphology cannot resolve an onset (fractions of the ED→AVc systole for
#: ICT, of the AVc→ED diastole for IVRT).
ICT_SYSTOLE_FRACTION = 0.10
IVRT_DIASTOLE_FRACTION = 0.25
#: Fraction of the beat's total shortening/lengthening that must accumulate
#: before the morphology declares a valve event — noise-robust onset.
ONSET_FRACTION = 0.05
#: Plausible cuff ranges (mmHg); outside them the input is refused, not used.
MIN_SBP_MMHG, MAX_SBP_MMHG = 60.0, 260.0
MIN_DBP_MMHG, MAX_DBP_MMHG = 30.0, 160.0
#: A loop shorter than this cannot hold four valve events.
MIN_CYCLE_FRAMES = 6
#: GWE below this is abnormal even for a template-based method (the normal
#: band is ~90-96 %) — reported with a warning instead of silently printed.
LOW_GWE_PERCENT = 80.0
#: Total systolic shortening (percentage points) below which the beat carries
#: no measurable contraction — a flat curve must not produce a zero loop.
MIN_SHORTENING_PP = 1.0

_MV_C = "mvc"
_AV_O = "avo"
_AV_C = "avc"
_MV_O = "mvo"


@dataclass(frozen=True)
class ValveEvents:
    """The four valve-event frames one loop is pinned to.

    ``avo_source``/``mvo_source`` state how each event was found
    ("strain" — the morphology onset, "phase" — the φ-fraction fallback):
    a report states provenance, and the confidence of the loop inherits the
    weakest link.
    """

    mvc_frame: int
    avo_frame: int
    avc_frame: int
    mvo_frame: int
    avo_source: str = "phase"
    mvo_source: str = "phase"

    @property
    def confidence(self) -> float:
        """Both morphology events = 0.9; each φ fallback costs 0.2."""
        confidence = 0.9
        confidence -= 0.2 * (self.avo_source == "phase")
        confidence -= 0.2 * (self.mvo_source == "phase")
        return round(confidence, 2)


def _smoothed(strain: np.ndarray) -> np.ndarray:
    """NaN-interpolated strain; NaN heads/tails stay NaN (no invented frames)."""
    arr = np.asarray(strain, dtype=np.float64).copy()
    finite = np.isfinite(arr)
    if finite.all() or not finite.any():
        return arr
    index = np.arange(arr.size)
    arr[~finite] = np.interp(index[~finite], index[finite], arr[finite])
    return arr


def _onset_frame(
    curve: np.ndarray,
    start: int,
    end: int,
    direction: int,
) -> int | None:
    """First frame where |Δstrain| accumulates ``ONSET_FRACTION`` of the beat.

    ``direction`` +1 looks for lengthening (strain rising), −1 for
    shortening. Returns ``None`` when the segment is too short or the
    accumulated change never reaches the fraction — then the caller falls
    back to the phase fraction instead of guessing.
    """
    lo, hi = int(start), int(end)
    if hi - lo < 2 or direction not in (-1, 1):
        return None
    segment = curve[lo : hi + 1]
    total = float(segment[-1] - segment[0])
    if direction * total < 1e-9:  # no net change in the searched direction
        return None
    threshold = ONSET_FRACTION * abs(total)
    delta = np.diff(segment) * direction
    cumulative = np.cumsum(np.clip(delta, 0.0, None))  # only the wanted direction
    reached = np.nonzero(cumulative >= threshold)[0]
    if reached.size == 0:
        return None
    return lo + int(reached[0]) + 1


def detect_valve_events(
    strain_curve: np.ndarray,
    *,
    ed_frame: int,
    avc_frame: int | None = None,
    es_frame: int | None = None,
) -> ValveEvents | None:
    """Pin the four valve events of one beat from the phase anchors + strain.

    MVc ≈ the ED anchor (φ = 0, the ventricle full). AVc comes from the
    caller's doctrine chain (manual → ECG → area nadir → strain peak → ES —
    the ``strain_metrics.detect_avc_frame`` result; the strain minimum inside
    the cycle confirms it when it agrees within 2 frames). AVo/MVo are the
    strain-morphology onsets of shortening/lengthening; when the morphology
    cannot resolve them (flat or noisy segment), the isovolumetric-fraction
    fallback of the systole/diastole spans is used and *stated* in the
    source fields. Returns ``None`` when the beat is too short to hold four
    events.
    """
    curve = _smoothed(strain_curve)
    n = int(curve.size)
    mvc = int(ed_frame)
    if not 0 <= mvc < n:
        return None
    anchor = int(avc_frame if avc_frame is not None else (es_frame if es_frame is not None else mvc))
    anchor = int(np.clip(anchor, mvc + 1, n - 1))
    if anchor - mvc + 1 < MIN_CYCLE_FRAMES:
        return None

    # Strain minimum inside the cycle confirms the AVc anchor when close.
    window_end = min(anchor + 2, n)
    window = curve[mvc:window_end]
    cycle_min = mvc + int(np.argmin(np.where(np.isfinite(window), window, np.inf)))
    if abs(cycle_min - anchor) <= 2:
        avc = cycle_min
    else:
        avc = anchor

    systole = curve[mvc : avc + 1]
    shortening = float(systole[-1] - systole[0])
    avo = _onset_frame(curve, mvc, avc, -1) if shortening < -1e-9 else None
    if avo is None:
        avo = mvc + max(1, int(round(ICT_SYSTOLE_FRACTION * (avc - mvc))))
        avo = min(avo, avc - 1)
        avo_source = "phase"
    else:
        avo_source = "strain"

    # The diastole the caller knows ends where the curve ends (one cycle);
    # MVo is the lengthening onset inside [avc, end].
    mvo = _onset_frame(curve, avc, n - 1, 1)
    if mvo is None:
        diastole_span = max(1, (n - 1) - avc)
        mvo = avc + max(1, int(round(IVRT_DIASTOLE_FRACTION * diastole_span)))
        mvo = min(mvo, n - 1)
        mvo_source = "phase"
    else:
        mvo_source = "strain"
    if mvo <= avc:
        mvo = min(avc + 1, n - 1)
    return ValveEvents(
        mvc_frame=mvc,
        avo_frame=int(avo),
        avc_frame=int(avc),
        mvo_frame=int(mvo),
        avo_source=avo_source,
        mvo_source=mvo_source,
    )


def build_pressure_curve(
    n_frames: int,
    events: ValveEvents,
    *,
    sbp_mmhg: float,
    dbp_mmhg: float,
    lvedp_mmhg: float = DEFAULT_LVEDP_MMHG,
) -> np.ndarray:
    """LV pressure template pinned to the valve events (mmHg per frame).

    Knots: MVc = LVEDP (the method's assumption), AVo ≈ DBP (LV meets the
    aorta at the aortic diastolic pressure), mid-ejection ≈ SBP, AVc =
    0.9·SBP (LVESP), MVo back near the filling pressure. Monotone PCHIP
    between the knots — no overshoot, no negative pressure; outside
    [MVc, MVo] the curve holds the diastolic level.
    """
    pressure = np.full(int(n_frames), float(lvedp_mmhg), dtype=np.float64)
    esp = LVESP_SBP_FACTOR * float(sbp_mmhg)
    mid = (int(events.avo_frame) + int(events.avc_frame)) // 2
    knots_x = [
        int(events.mvc_frame),
        int(events.avo_frame),
        mid,
        int(events.avc_frame),
        int(events.mvo_frame),
    ]
    knots_y = [float(lvedp_mmhg), float(dbp_mmhg), float(sbp_mmhg), esp, max(float(lvedp_mmhg), 0.15 * float(dbp_mmhg))]
    # PCHIP needs strictly increasing x; events guarantee mvc < avo < avc < mvo
    # in a sane beat, but degenerate anchors are clipped by the caller anyway.
    interpolator = PchipInterpolator(np.asarray(knots_x, dtype=np.float64), np.asarray(knots_y, dtype=np.float64))
    lo = max(0, int(events.mvc_frame))
    hi = min(int(n_frames) - 1, int(events.mvo_frame))
    if hi > lo:
        pressure[lo : hi + 1] = np.clip(np.asarray(interpolator(np.arange(lo, hi + 1)), dtype=np.float64), 0.0, None)
    return pressure


@dataclass(frozen=True)
class WorkCycle:
    """One beat's pressure-strain loop reduced to the four MW numbers."""

    mvc_frame: int
    mvo_frame: int
    gwi_mmhg_pct: float
    gcw_mmhg_pct: float
    gww_mmhg_pct: float
    gwe_percent: float
    esp_mmhg: float
    edp_mmhg: float
    confidence: float


@dataclass(frozen=True)
class WorkResult:
    """Myocardial Work of a clip: per-cycle loops + the median summary.

    ``gwi/gcw/gww/gwe`` are ``None`` when no cycle could be integrated —
    the summary never invents a number. ``warnings`` explains why (the same
    never-raises contract as the phase field).
    """

    cycles: tuple[WorkCycle, ...] = ()
    gwi_mmhg_pct: float | None = None
    gcw_mmhg_pct: float | None = None
    gww_mmhg_pct: float | None = None
    gwe_percent: float | None = None
    sbp_mmhg: float | None = None
    dbp_mmhg: float | None = None
    warnings: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        """JSON-serialisable record (the report projection stores this)."""
        return {
            "schema_version": self.schema_version,
            "cycles": [
                {
                    "mvc_frame": c.mvc_frame,
                    "mvo_frame": c.mvo_frame,
                    "gwi_mmhg_pct": c.gwi_mmhg_pct,
                    "gcw_mmhg_pct": c.gcw_mmhg_pct,
                    "gww_mmhg_pct": c.gww_mmhg_pct,
                    "gwe_percent": c.gwe_percent,
                    "esp_mmhg": c.esp_mmhg,
                    "edp_mmhg": c.edp_mmhg,
                    "confidence": c.confidence,
                }
                for c in self.cycles
            ],
            "gwi_mmhg_pct": self.gwi_mmhg_pct,
            "gcw_mmhg_pct": self.gcw_mmhg_pct,
            "gww_mmhg_pct": self.gww_mmhg_pct,
            "gwe_percent": self.gwe_percent,
            "sbp_mmhg": self.sbp_mmhg,
            "dbp_mmhg": self.dbp_mmhg,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkResult:
        """Round-trip of :meth:`to_dict` (unknown fields are ignored)."""
        cycles = tuple(
            WorkCycle(
                mvc_frame=int(item.get("mvc_frame", 0)),
                mvo_frame=int(item.get("mvo_frame", 0)),
                gwi_mmhg_pct=float(item.get("gwi_mmhg_pct", 0.0)),
                gcw_mmhg_pct=float(item.get("gcw_mmhg_pct", 0.0)),
                gww_mmhg_pct=float(item.get("gww_mmhg_pct", 0.0)),
                gwe_percent=float(item.get("gwe_percent", 0.0)),
                esp_mmhg=float(item.get("esp_mmhg", 0.0)),
                edp_mmhg=float(item.get("edp_mmhg", 0.0)),
                confidence=float(item.get("confidence", 0.0)),
            )
            for item in data.get("cycles", [])
        )
        summary = data.get("gwi_mmhg_pct")
        return cls(
            cycles=cycles,
            gwi_mmhg_pct=None if summary is None else float(summary),
            gcw_mmhg_pct=None if data.get("gcw_mmhg_pct") is None else float(data["gcw_mmhg_pct"]),
            gww_mmhg_pct=None if data.get("gww_mmhg_pct") is None else float(data["gww_mmhg_pct"]),
            gwe_percent=None if data.get("gwe_percent") is None else float(data["gwe_percent"]),
            sbp_mmhg=None if data.get("sbp_mmhg") is None else float(data["sbp_mmhg"]),
            dbp_mmhg=None if data.get("dbp_mmhg") is None else float(data["dbp_mmhg"]),
            warnings=tuple(data.get("warnings", ())),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )


def _validate_pressure(sbp: float, dbp: float) -> tuple[str, ...]:
    """Cuff-range validation warnings; empty means the input is usable."""
    warnings: list[str] = []
    if not MIN_SBP_MMHG <= sbp <= MAX_SBP_MMHG:
        warnings.append("systolic_out_of_range")
    if not MIN_DBP_MMHG <= dbp <= MAX_DBP_MMHG:
        warnings.append("diastolic_out_of_range")
    if dbp >= sbp:
        warnings.append("diastolic_not_below_systolic")
    return tuple(warnings)


def _integrate_loop(
    strain: np.ndarray,
    pressure: np.ndarray,
    start: int,
    end: int,
) -> tuple[float, float, float]:
    """Net/constructive/wasted work of [start, end) — mmHg·%, strain in %.

    ``w = −P·dε``: shortening under pressure is constructive (positive),
    lengthening under pressure is wasted (the loop's negative-area part).
    """
    net = 0.0
    constructive = 0.0
    wasted = 0.0
    for i in range(int(start), int(end)):
        d_eps = float(strain[i + 1] - strain[i])
        p_mid = 0.5 * (float(pressure[i]) + float(pressure[i + 1]))
        work = -p_mid * d_eps
        net += work
        if work >= 0.0:
            constructive += work
        else:
            wasted -= work
    return net, constructive, wasted


def compute_myocardial_work(
    strain_curve: np.ndarray,
    *,
    ed_frame: int,
    sbp_mmhg: float,
    dbp_mmhg: float,
    avc_frame: int | None = None,
    es_frame: int | None = None,
    lvedp_mmhg: float = DEFAULT_LVEDP_MMHG,
) -> WorkResult:
    """One beat's MW from the strain curve, the phase anchors and cuff BP.

    The integration window is [MVc, MVo) — the loop's own span, so diastolic
    lengthening after MVo (low pressure, by design of the template) does not
    inflate GWW. Returns a :class:`WorkResult` that always exists; without
    strain, a usable beat or plausible pressure the cycles are empty and the
    warnings say what was missing.
    """
    warnings = list(_validate_pressure(sbp_mmhg, dbp_mmhg))
    if warnings:
        # An implausible cuff pressure would only make the loop look precise.
        return WorkResult(sbp_mmhg=sbp_mmhg, dbp_mmhg=dbp_mmhg, warnings=tuple(sorted(set(warnings))))
    curve = _smoothed(strain_curve)
    if curve.size < MIN_CYCLE_FRAMES + 2 or not np.isfinite(curve).any():
        warnings.append("no_strain")
        return WorkResult(sbp_mmhg=sbp_mmhg, dbp_mmhg=dbp_mmhg, warnings=tuple(sorted(set(warnings))))
    events = detect_valve_events(curve, ed_frame=ed_frame, avc_frame=avc_frame, es_frame=es_frame)
    if events is None:
        warnings.append("no_cycle")
        return WorkResult(sbp_mmhg=sbp_mmhg, dbp_mmhg=dbp_mmhg, warnings=tuple(sorted(set(warnings))))
    shortening = float(curve[events.avc_frame] - curve[events.mvc_frame])
    if not np.isfinite(shortening) or abs(shortening) < MIN_SHORTENING_PP:
        warnings.append("no_shortening")
        return WorkResult(sbp_mmhg=sbp_mmhg, dbp_mmhg=dbp_mmhg, warnings=tuple(sorted(set(warnings))))
    if not bool(np.isfinite(np.asarray(strain_curve, dtype=np.float64)).all()):
        # The smoothed curve no longer shows the holes — report that they were
        # filled, on the original array.
        warnings.append("strain_gaps_interpolated")

    pressure = build_pressure_curve(
        curve.size,
        events,
        sbp_mmhg=sbp_mmhg,
        dbp_mmhg=dbp_mmhg,
        lvedp_mmhg=lvedp_mmhg,
    )
    net, constructive, wasted = _integrate_loop(
        strain=curve, pressure=pressure, start=events.mvc_frame, end=events.mvo_frame
    )
    if not (np.isfinite(net) and np.isfinite(constructive) and np.isfinite(wasted)):
        warnings.append("no_strain")
        return WorkResult(sbp_mmhg=sbp_mmhg, dbp_mmhg=dbp_mmhg, warnings=tuple(sorted(set(warnings))))
    total = constructive + wasted
    gwe = 100.0 * constructive / total if total > 1e-9 else 0.0
    if gwe < LOW_GWE_PERCENT:
        warnings.append("low_work_efficiency")
    cycle = WorkCycle(
        mvc_frame=events.mvc_frame,
        mvo_frame=events.mvo_frame,
        gwi_mmhg_pct=round(net, 2),
        gcw_mmhg_pct=round(constructive, 2),
        gww_mmhg_pct=round(wasted, 2),
        gwe_percent=round(gwe, 2),
        esp_mmhg=round(LVESP_SBP_FACTOR * sbp_mmhg, 2),
        edp_mmhg=round(lvedp_mmhg, 2),
        confidence=events.confidence,
    )
    return WorkResult(
        cycles=(cycle,),
        gwi_mmhg_pct=cycle.gwi_mmhg_pct,
        gcw_mmhg_pct=cycle.gcw_mmhg_pct,
        gww_mmhg_pct=cycle.gww_mmhg_pct,
        gwe_percent=cycle.gwe_percent,
        sbp_mmhg=float(sbp_mmhg),
        dbp_mmhg=float(dbp_mmhg),
        warnings=tuple(sorted(set(warnings))),
    )


def myocardial_work_from_analysis(
    global_curve: np.ndarray | None,
    *,
    ed_index: int,
    avc_index: int,
    sbp_mmhg: float,
    dbp_mmhg: float,
) -> WorkResult:
    """MW from the stored analysis record (the report's projection input).

    ``StrainAnalysis`` carries exactly the frames and the curve this needs;
    the report coordinator calls this when the header holds a cuff pressure
    and re-projects the study into the protocol with the result attached.
    """
    curve = np.asarray(global_curve, dtype=np.float64) if global_curve is not None else None
    if curve is None or curve.size == 0:
        return WorkResult(sbp_mmhg=sbp_mmhg, dbp_mmhg=dbp_mmhg, warnings=("no_strain",))
    return compute_myocardial_work(
        curve,
        ed_frame=ed_index,
        avc_frame=avc_index,
        sbp_mmhg=sbp_mmhg,
        dbp_mmhg=dbp_mmhg,
    )
