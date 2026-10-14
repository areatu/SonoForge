"""Provenance and freshness contract for derived results (QH-1b.1).

Spec §5.2: every derived result carries stable identity, verified source,
input refs with revisions, calibration, method/config/model, units/definitions,
QC/coverage, freshness and reason codes. Timestamp is metadata only.

This module is pure — no Qt, no infrastructure, no httpx/pynetdicom.
It expands existing measurements/StrainAnalysis/StudyMeasurementData, not
duplicates them. Names are chosen in this first design PR; semantics are
mandatory per spec.

Compatibility:
- Old documents (v1/v2) without provenance load as UNVERIFIED.
- New documents (v3) store provenance as an optional field; missing field
  keeps default (empty tuple) so old code still reads new docs as valid
  primary data, but derived results are UNVERIFIED until provenance is present.
- Adding a field to a dataclass with a default keeps codec backward compatible
  (optional field handling in measurement_codec._decode).

Freshness is separate from QC:
- FRESH: required inputs available/compatible, revisions and method match result
- STALE: significant input/calibration/method changed
- UNVERIFIED: old import/schema without sufficient provenance
- UNAVAILABLE: required source/input missing

QC valid/review/invalid stays a separate dimension.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Freshness(str, Enum):
    """Freshness of a derived result, independent from QC."""

    FRESH = "fresh"
    STALE = "stale"
    UNVERIFIED = "unverified"
    UNAVAILABLE = "unavailable"


# Reason codes for freshness transitions — stable, non-localized, allowlisted.
REASON_INPUT_CHANGED = "input_changed"
REASON_CALIBRATION_CHANGED = "calibration_changed"
REASON_METHOD_CHANGED = "method_changed"
REASON_ALGORITHM_CHANGED = "algorithm_changed"
REASON_MODEL_CHANGED = "model_changed"
REASON_CONFIG_CHANGED = "config_changed"
REASON_SOURCE_MISSING = "source_missing"
REASON_INPUT_MISSING = "input_missing"
REASON_LEGACY_NO_PROVENANCE = "legacy_no_provenance"
REASON_FUTURE_SCHEMA = "future_schema"
REASON_PARTIAL_RESTORE = "partial_restore"
REASON_LATE_CALLBACK_DISCARDED = "late_callback_discarded"
REASON_MANUAL_OVERRIDE = "manual_override"
REASON_HEIGHT_WEIGHT_CHANGED = "height_weight_changed"

FRESHNESS_REASONS = frozenset(
    {
        REASON_INPUT_CHANGED,
        REASON_CALIBRATION_CHANGED,
        REASON_METHOD_CHANGED,
        REASON_ALGORITHM_CHANGED,
        REASON_MODEL_CHANGED,
        REASON_CONFIG_CHANGED,
        REASON_SOURCE_MISSING,
        REASON_INPUT_MISSING,
        REASON_LEGACY_NO_PROVENANCE,
        REASON_FUTURE_SCHEMA,
        REASON_PARTIAL_RESTORE,
        REASON_LATE_CALLBACK_DISCARDED,
        REASON_MANUAL_OVERRIDE,
        REASON_HEIGHT_WEIGHT_CHANGED,
    }
)


class QCStatus(str, Enum):
    """QC status, separate from freshness (spec §5.2)."""

    VALID = "valid"
    REVIEW = "review"
    INVALID = "invalid"
    UNVERIFIED = "unverified"


# Where the BSA behind a BSA-normalised result came from (QH-1b.2, slice 1).
BSA_SOURCE_DERIVED = "derived"  # Du Bois from patient height and weight
BSA_SOURCE_MANUAL = "manual"  # typed by the user in the calculators (overrides derived)
BSA_SOURCE_MISSING = "missing"  # no BSA could be computed


@dataclass(frozen=True)
class BsaBasis:
    """The body surface area a BSA-dependent result was normalised by.

    Recorded next to the result so a later change of height, weight or the
    manual BSA can be detected without recomputing the old number. ``value``
    is in m²; ``height_cm``/``weight_kg`` are the patient metrics the value
    was taken from (``None`` when they were absent or not used).
    """

    value: float | None
    source: str = BSA_SOURCE_MISSING
    height_cm: float | None = None
    weight_kg: float | None = None


@dataclass(frozen=True)
class BsaRecordStatus:
    """Freshness of the BSA-dependent results *stored with a study* (QH-1b.2, slice 2).

    ``recorded`` is the basis the saved record was normalised by, ``current``
    the basis the open study provides now. The two differ only while the open
    study has edits the record does not have — or when the record predates the
    schema that started writing the basis, which is the ``unverified`` case.

    The DTO carries numbers, not sentences: the panel, the text report and the
    PDF render it through the same helper so the three can not disagree.
    """

    freshness: str
    reasons: tuple[str, ...] = ()
    recorded: BsaBasis | None = None
    current: BsaBasis | None = None

    @property
    def needs_attention(self) -> bool:
        """True whenever the record must not be presented as simply current."""
        return self.freshness != Freshness.FRESH.value


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_result_id() -> str:
    """Stable result ID — UUID4 hex, opaque, no PHI."""
    return uuid.uuid4().hex


def stable_id_for_content(*parts: str) -> str:
    """Deterministic stable ID from content parts (e.g., contour points)."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


@dataclass(frozen=True)
class SourceIdentity:
    """Verified study/source identity, frame/cycle/ROI/ED/ES where used.

    Uses WP4 descriptors (study_uid + instance_uid + frame_index + fingerprint),
    not current path or tab name (S-01). For non-DICOM, fingerprint is content hash;
    ambiguous remap requires refusal/choice, not heuristic auto-restore.
    """

    study_uid: str
    sop_instance_uid: str = ""
    series_uid: str = ""
    frame_index: int | None = None
    # Content fingerprint of the source (e.g., sha256 of pixel data or DICOM file)
    fingerprint: str = ""
    # ED/ES/ROI/cycle where relevant
    ed_index: int | None = None
    es_index: int | None = None
    cycle_start: int | None = None
    cycle_end: int | None = None
    roi: tuple[float, float, float, float] | None = None
    # View/chamber for context
    view: str = ""
    chamber: str = ""


@dataclass(frozen=True)
class CalibrationRef:
    """Spatial/temporal/velocity calibration and its normalization version."""

    kind: str  # pixel | time | velocity | doppler_roi | mmode
    # Value: pixel_spacing (row,col), time_ms_per_pixel, velocity_span, etc.
    value: tuple[float, ...] | float | None = None
    version: str = ""  # normalization version
    source_instance_uid: str = ""
    # Whether this calibration is manual override
    manual: bool = False


@dataclass(frozen=True)
class MethodIdentity:
    """Algorithm/measurement-semantics version, config digest, model identity."""

    method_id: str
    semantics_version: int = 1
    algorithm_version: str = ""
    config_digest: str = ""
    model_id: str = ""
    model_hash: str = ""
    # Human-readable definition, e.g., "GLS = peak of global longitudinal strain"
    definition: str = ""
    units: str = ""


@dataclass(frozen=True)
class InputReference:
    """Reference to an input measurement ID and its content revision."""

    measurement_id: str
    revision: int = 0
    kind: str = ""  # contour | linear | doppler | vessel | height | weight | ...
    label: str = ""  # optional label for debugging, not for identity


@dataclass(frozen=True)
class ResultQC:
    """QC/coverage, reasons, declared fallback — separate from freshness."""

    status: str = QCStatus.UNVERIFIED.value
    coverage: float = 0.0
    reasons: tuple[str, ...] = ()
    fallback: str = ""  # declared fallback, e.g., "segment_mean"
    interpolated_fraction: float = 0.0
    rejected_fraction: float = 0.0


@dataclass(frozen=True)
class ResultProvenance:
    """Full provenance for one derived result (spec §5.2).

    - stable result ID and method ID
    - verified study/source identity, frame/cycle/ROI/ED/ES where really used
    - references to input measurement IDs and their content revisions
    - spatial/temporal/velocity calibration and version of its normalization
    - algorithm/measurement-semantics version, config values digest, model id/hash
    - units and definitions
    - QC/coverage, reasons, fallback
    - freshness and reason codes
    - timestamp as metadata, not replacing identity/revision
    """

    result_id: str
    method: MethodIdentity
    source: SourceIdentity | None = None
    inputs: tuple[InputReference, ...] = ()
    calibration: tuple[CalibrationRef, ...] = ()
    units: str = ""
    definition: str = ""
    qc: ResultQC = field(default_factory=ResultQC)
    freshness: str = Freshness.UNVERIFIED.value
    freshness_reasons: tuple[str, ...] = ()
    timestamp: str = field(default_factory=_utc_now_iso)
    revision: int = 0
    # Optional: result family for dependency map (simpson, strain, doppler, etc.)
    family: str = ""

    def is_fresh(self) -> bool:
        return self.freshness == Freshness.FRESH.value

    def is_stale(self) -> bool:
        return self.freshness == Freshness.STALE.value

    def is_unverified(self) -> bool:
        return self.freshness == Freshness.UNVERIFIED.value

    def is_unavailable(self) -> bool:
        return self.freshness == Freshness.UNAVAILABLE.value

    def with_freshness(self, freshness: str, *, reasons: tuple[str, ...] = ()) -> ResultProvenance:
        """Return copy with new freshness and reasons (immutable)."""
        if freshness not in {f.value for f in Freshness}:
            raise ValueError(f"Invalid freshness: {freshness}")
        return ResultProvenance(
            result_id=self.result_id,
            method=self.method,
            source=self.source,
            inputs=self.inputs,
            calibration=self.calibration,
            units=self.units,
            definition=self.definition,
            qc=self.qc,
            freshness=freshness,
            freshness_reasons=tuple(reasons),
            timestamp=self.timestamp,
            revision=self.revision + 1,
            family=self.family,
        )


def make_provenance(
    *,
    result_id: str | None = None,
    method_id: str,
    family: str,
    source: SourceIdentity | None = None,
    inputs: tuple[InputReference, ...] = (),
    calibration: tuple[CalibrationRef, ...] = (),
    units: str = "",
    definition: str = "",
    qc: ResultQC | None = None,
    freshness: str = Freshness.FRESH.value,
    reasons: tuple[str, ...] = (),
    revision: int = 0,
    semantics_version: int = 1,
    algorithm_version: str = "",
    config_digest: str = "",
    model_id: str = "",
    model_hash: str = "",
) -> ResultProvenance:
    """Convenience factory for ResultProvenance."""
    method = MethodIdentity(
        method_id=method_id,
        semantics_version=semantics_version,
        algorithm_version=algorithm_version,
        config_digest=config_digest,
        model_id=model_id,
        model_hash=model_hash,
        definition=definition,
        units=units,
    )
    return ResultProvenance(
        result_id=result_id or new_result_id(),
        method=method,
        source=source,
        inputs=inputs,
        calibration=calibration,
        units=units,
        definition=definition,
        qc=qc or ResultQC(),
        freshness=freshness,
        freshness_reasons=tuple(reasons),
        timestamp=_utc_now_iso(),
        revision=revision,
        family=family,
    )


# ── Legacy handling ──────────────────────────────────────────────────────


def legacy_unverified_provenance(*, result_id: str, family: str, method_id: str = "legacy") -> ResultProvenance:
    """Provenance for old derived results without reliable lineage (spec §5.3.3).

    Old derived result without достоверного происхождения становится unverified,
    а не автоматически fresh; совместимые первичные измерения сохраняются.
    """
    return make_provenance(
        result_id=result_id,
        method_id=method_id,
        family=family,
        freshness=Freshness.UNVERIFIED.value,
        reasons=(REASON_LEGACY_NO_PROVENANCE,),
        qc=ResultQC(status=QCStatus.UNVERIFIED.value),
    )
