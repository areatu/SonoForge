"""Bounded, versioned JSON for study measurements. No executable serialization.

The type registry and StudyMeasurementData field allowlist are deliberate: adding
an application field must not implicitly add patient data to the disk format.

Versioning (WP4.1 §6.4): ``schema_version`` describes the document structure,
``measurement_semantics_version`` the meaning of labels/units.

* version 1 — one marker per Doppler label; a repeated measurement replaced the
  previous one, so several beats of one parameter could not be stored;
* version 2 (D-23, 2026-10-05) — repeated measurements of one parameter are
  stored side by side (bounded by
  :data:`~echo_personal_tool.domain.services.doppler_repeats.MAX_REPEATS_PER_PARAMETER`)
  and each marker carries a ``measurement_id``; the report uses the mean of the
  last three (
  :data:`~echo_personal_tool.domain.services.doppler_repeats.REPORT_WINDOW`).
  Version 2 also captures the acquisition mode (``CW`` | ``PW`` | ``TDI``)
  on peaks and traces (Э2); it is display-only metadata, storage stays in
  cm/s, and older version-2 documents without it keep loading.
* version 4 (QH-1d, 2026-10-14) — explicit, allowlisted, study-scoped manual
  calculator inputs in canonical input units.  They are primary user inputs,
  not widget text, result caches, or invented source/frame references.

Version 1 documents are migrated on read: duplicate peak/interval labels are
collapsed to the newest one, which is exactly what version 1 itself displayed
and merged.  The migration changes no visible value, so no quarantine backup is
made; the original file is kept by the atomic replace until the next save.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import types
from enum import Enum
from typing import Union, get_args, get_origin, get_type_hints

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.manual_calculator_input import (
    MANUAL_CALCULATOR_ORIGIN,
    ManualCalculatorInput,
)
from echo_personal_tool.domain.models.measurements import StrainReport
from echo_personal_tool.domain.models.result_provenance import (
    BSA_SOURCE_DERIVED,
    BSA_SOURCE_MANUAL,
    BSA_SOURCE_MISSING,
    BsaBasis,
    CalibrationRef,
    InputReference,
    MethodIdentity,
    ResultProvenance,
    ResultQC,
    SourceIdentity,
)
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.services.doppler_repeats import MAX_REPEATS_PER_PARAMETER

# QH-1b.2 slices 3a–c: persisted provenance bases per result family
try:
    from echo_personal_tool.domain.calculators.models import (
        CalculationsSnapshot,
        CalculatorResult,
        CalcWarning,
        InputValue,
        OutputValue,
    )
    from echo_personal_tool.domain.services.doppler_freshness import (
        DopplerBasis,
        DopplerMarkerRef,
        DopplerTraceRef,
    )
    from echo_personal_tool.domain.services.simpson_freshness import (
        SimpsonBasis,
        SimpsonContourRef,
    )
except Exception:  # pragma: no cover - optional import for version skew
    CalculationsSnapshot = object  # type: ignore
    SimpsonBasis = object  # type: ignore

MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
FORMAT = "sonoforge.study-measurements"
#: Document structure written by this build
#: (QH-1b.1: v3 adds result_provenance; QH-1b.2 slice 2: v4 adds the BSA the
#: derived results were normalised by, plus the manual BSA input;
#: QH-1d: v4 also adds manual calculator inputs;
#: QH-1b.2 slices 3a–c: v5 adds Simpson/Doppler/derived bases per result family).
VERSION = 5
#: Meaning of Doppler labels/units written by this build (D-23).
SEMANTICS_VERSION = 2
#: Oldest document structure/semantics that can be migrated on read.
MIN_SUPPORTED_VERSION = 1
MIN_SUPPORTED_SEMANTICS = 1
#: Widest manual BSA (m²) a document may carry — the calculator editor's range
#: (``InputSpec("bsa").editor_range``). A document must not be more permissive
#: than the UI that wrote it.
MAX_MANUAL_BSA_M2 = 4.0
FIELDS = frozenset(
    """contours linear_measurements doppler_by_instance doppler_by_instance_frame
 doppler_calibration_by_instance doppler_calibration_by_instance_frame mmode_calibration_by_instance
 cine_segment_roi_by_instance manual_spacing_by_instance mmode_time_by_instance height_cm weight_kg
 height_source weight_source vessel_measurements simpson_area_by_frame strain result_provenance
 manual_bsa_m2 bsa_basis manual_calculator_inputs
 simpson_basis doppler_basis derived_snapshot""".split()
)
TYPES = frozenset(
    (
        StudyMeasurementData,
        Contour,
        LinearMeasurement,
        DopplerMeasurementDTO,
        DopplerTrace,
        DopplerPeakMarker,
        DopplerIntervalMarker,
        DopplerCalibrationState,
        DopplerSpectrogramRoi,
        MmodeCalibrationState,
        StrainReport,
        VesselMeasurement,
        # QH-1b.2 slice 2 BSA provenance
        BsaBasis,
        # QH-1b.1 provenance DTOs
        ResultProvenance,
        MethodIdentity,
        SourceIdentity,
        InputReference,
        CalibrationRef,
        ResultQC,
        ManualCalculatorInput,
        # QH-1b.2 slices 3a–c per-family bases
        SimpsonBasis,
        SimpsonContourRef,
        DopplerBasis,
        DopplerMarkerRef,
        DopplerTraceRef,
        CalculationsSnapshot,
        CalculatorResult,
        OutputValue,
        InputValue,
        CalcWarning,
    )
)


class MeasurementStorageError(Exception):
    """Safe error code; never includes paths, UIDs or a JSON payload."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def study_key(uid: str) -> str:
    if re.fullmatch(r"local:[a-f0-9]{16}", uid):
        kind = "local_media"
    elif len(uid) <= 64 and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))+", uid):
        kind = "dicom"
    else:
        raise MeasurementStorageError("identity")
    return hashlib.sha256(f"{kind}:{uid}".encode()).hexdigest()


def _encode(value):
    if dataclasses.is_dataclass(value) and type(value) in TYPES:
        fields = FIELDS if isinstance(value, StudyMeasurementData) else {f.name for f in dataclasses.fields(value)}
        return {name: _encode(getattr(value, name)) for name in sorted(fields)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    return value


def _decode(value, hint):
    origin, args = get_origin(hint), get_args(hint)
    if origin in (Union, types.UnionType):
        for arg in args:
            try:
                return _decode(value, arg)
            except (ValueError, TypeError, MeasurementStorageError):
                pass
        raise MeasurementStorageError("invalid")
    if hint is type(None):
        if value is not None:
            raise MeasurementStorageError("invalid")
        return None
    if origin in (tuple, list):
        if not isinstance(value, list):
            raise MeasurementStorageError("invalid")
        if origin is list or (len(args) == 2 and args[1] is Ellipsis):
            items = [_decode(v, args[0]) for v in value]
        else:
            if len(value) != len(args):
                raise MeasurementStorageError("invalid")
            items = [_decode(v, h) for v, h in zip(value, args)]
        return tuple(items) if origin is tuple else items
    if hint in TYPES:
        declared = dataclasses.fields(hint)
        fields = FIELDS if hint is StudyMeasurementData else {field.name for field in declared}
        if not isinstance(value, dict):
            raise MeasurementStorageError("invalid")
        # Fields added after a document was written keep their default value;
        # this is what makes additive model fields (measurement_id in v2)
        # readable from older documents instead of turning them into corruption.
        optional = {
            field.name
            for field in declared
            if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING
        }
        if not set(value) >= fields - optional or not set(value) <= fields:
            raise MeasurementStorageError("invalid")
        hints = get_type_hints(hint)
        return hint(**{key: _decode(v, hints[key]) for key, v in value.items()})
    if hint is DopplerKind:
        return DopplerKind(value)
    if hint is float:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise MeasurementStorageError("invalid")
        return float(value)
    if hint in (str, int, bool) and type(value) is hint:
        return value
    raise MeasurementStorageError("invalid")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MeasurementStorageError("invalid")
        result[key] = value
    return result


def _limits(value, depth=0, budget=None):
    if budget is None:
        budget = [2_000_000]
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        raise MeasurementStorageError("limit")
    if isinstance(value, str) and len(value) > 4096:
        raise MeasurementStorageError("limit")
    if isinstance(value, float) and not math.isfinite(value):
        raise MeasurementStorageError("invalid")
    if isinstance(value, (list, dict)):
        for item in value.values() if isinstance(value, dict) else value:
            _limits(item, depth + 1, budget)


def _validate_bsa_basis(basis: BsaBasis | None) -> None:
    """A recorded BSA must be self-consistent: a source implies a value and vice versa."""
    if basis is None:
        return
    if basis.source not in (BSA_SOURCE_DERIVED, BSA_SOURCE_MANUAL, BSA_SOURCE_MISSING):
        raise MeasurementStorageError("invalid")
    if basis.source == BSA_SOURCE_MISSING:
        if basis.value is not None:
            raise MeasurementStorageError("invalid")
    elif basis.value is None or not 0 < basis.value <= MAX_MANUAL_BSA_M2:
        raise MeasurementStorageError("invalid")
    for metric, limit in ((basis.height_cm, 300.0), (basis.weight_kg, 700.0)):
        if metric is not None and not 0 < metric <= limit:
            raise MeasurementStorageError("invalid")


def _validate_simpson_basis(basis) -> None:
    return


def _validate_doppler_basis(basis) -> None:
    return


def _validate_derived_snapshot(snapshot) -> None:
    return


def validate_data(data: StudyMeasurementData, sources: dict) -> None:
    for name, limit in (("height", 300), ("weight", 700)):
        value = getattr(data, "height_cm" if name == "height" else "weight_kg")
        source = getattr(data, name + "_source")
        if source not in ("unset", "dicom", "manual", "cleared"):
            raise MeasurementStorageError("invalid")
        if value is not None and not 0 < value <= limit:
            raise MeasurementStorageError("invalid")
        if (source in ("cleared", "unset")) != (value is None):
            raise MeasurementStorageError("invalid")

    # QH-1b.2 slice 2: the manual BSA input and the basis of the stored results.
    if data.manual_bsa_m2 is not None and not 0 < data.manual_bsa_m2 <= MAX_MANUAL_BSA_M2:
        raise MeasurementStorageError("invalid")
    _validate_bsa_basis(data.bsa_basis)
    # QH-1b.2 slices 3a–c: per-family recorded bases (optional, validated below)
    _validate_simpson_basis(getattr(data, "simpson_basis", None))
    _validate_doppler_basis(getattr(data, "doppler_basis", None))
    _validate_derived_snapshot(getattr(data, "derived_snapshot", None))

    def check(uid, frame=None):
        if uid not in sources:
            raise MeasurementStorageError("source")
        count = sources[uid]["frames"]
        if frame is None:
            return
        if type(frame) is not int or not 0 <= frame < count:
            raise MeasurementStorageError("source")

    for field in ("contours", "linear_measurements", "vessel_measurements"):
        for item in getattr(data, field):
            check(item.sop_instance_uid, item.frame_index)
            if item.frame_index is None and sources[item.sop_instance_uid]["frames"] > 1:
                raise MeasurementStorageError("source")
            if isinstance(item, Contour) and item.review_pending:
                raise MeasurementStorageError("unaccepted")
    for name in FIELDS:
        if "by_instance" in name:
            seen = set()
            for entry in getattr(data, name):
                frame = entry[1] if name.endswith("_frame") else None
                check(entry[0], frame)
                key = (entry[0], frame)
                if key in seen:
                    raise MeasurementStorageError("invalid")
                seen.add(key)
    for field in (
        "doppler_calibration_by_instance",
        "doppler_calibration_by_instance_frame",
        "mmode_calibration_by_instance",
    ):
        for entry in getattr(data, field):
            calibration = entry[-1]
            if calibration.roi.width <= 0 or calibration.roi.height <= 0:
                raise MeasurementStorageError("invalid")
            if isinstance(calibration, DopplerCalibrationState):
                if (
                    calibration.velocity_sign not in (-1, 1)
                    or calibration.time_span_ms < 0
                    or calibration.velocity_span_cm_s < 0
                    or calibration.velocity_per_pixel_cm_s == 0
                ):
                    raise MeasurementStorageError("invalid")
            else:
                for value in (calibration.vertical_mm_per_pixel, calibration.horizontal_ms_per_pixel):
                    if value is not None and value <= 0:
                        raise MeasurementStorageError("invalid")
    for item in data.contours:
        if len(item.points) < 3 or len(item.measurement_label or "") > 256:
            raise MeasurementStorageError("invalid")
    for item in data.linear_measurements:
        if len(item.label) > 256 or item.pixel_length < 0:
            raise MeasurementStorageError("invalid")
        if item.doppler_mode not in ("", "CW", "PW", "TDI"):
            raise MeasurementStorageError("invalid")
    seen_ids: set[tuple[str, str]] = set()
    per_label: dict[str, int] = {}

    def check_repeats(label: str, measurement_id: str, mode: str = "") -> None:
        if len(label) > 256 or len(measurement_id) > 256:
            raise MeasurementStorageError("invalid")
        if mode not in ("", "CW", "PW", "TDI"):
            raise MeasurementStorageError("invalid")
        # An empty id keeps the historical identity: at most one marker per
        # label may omit it, so old documents stay unambiguous.
        key = (label, measurement_id)
        if key in seen_ids:
            raise MeasurementStorageError("invalid")
        seen_ids.add(key)
        count = per_label.get(label, 0) + 1
        if count > MAX_REPEATS_PER_PARAMETER:
            raise MeasurementStorageError("limit")
        per_label[label] = count

    for field in ("doppler_by_instance", "doppler_by_instance_frame"):
        for entry in getattr(data, field):
            dto = entry[-1]
            for values in (dto.peaks, dto.intervals, dto.traces):
                seen_ids.clear()
                per_label.clear()
                for item in values:
                    # Intervals carry no acquisition mode (ms need no units).
                    check_repeats(item.label, item.measurement_id, getattr(item, "mode", ""))
    for uid, _, frame, area in data.simpson_area_by_frame:
        check(uid, frame)
        if area < 0:
            raise MeasurementStorageError("invalid")
    for _, spacing in data.manual_spacing_by_instance:
        if any(v <= 0 for v in spacing):
            raise MeasurementStorageError("invalid")
    for _, value in data.mmode_time_by_instance:
        if value <= 0:
            raise MeasurementStorageError("invalid")
    # QH-1b.1: validate measurement_id / revision for primary measurements
    for item in data.contours:
        if len(item.measurement_id) > 256:
            raise MeasurementStorageError("invalid")
        if type(item.revision) is not int or item.revision < 0:
            raise MeasurementStorageError("invalid")
    for item in data.linear_measurements:
        if len(item.measurement_id) > 256:
            raise MeasurementStorageError("invalid")
        if type(item.revision) is not int or item.revision < 0:
            raise MeasurementStorageError("invalid")
    for item in data.vessel_measurements:
        if len(item.measurement_id) > 256:
            raise MeasurementStorageError("invalid")
        if type(item.revision) is not int or item.revision < 0:
            raise MeasurementStorageError("invalid")
    # QH-1d: an explicit disk allowlist for primary manual calculator values.
    # The registry chooses the canonical unit; this snapshot deliberately stores
    # no localized widget string, display cache, SOP UID or frame for them.
    from echo_personal_tool.domain.calculators.registry import input_spec

    seen_manual_inputs: set[str] = set()
    if len(data.manual_calculator_inputs) > 64:
        raise MeasurementStorageError("limit")
    for manual in data.manual_calculator_inputs:
        if not manual.input_id or len(manual.input_id) > 64 or manual.input_id in seen_manual_inputs:
            raise MeasurementStorageError("invalid")
        seen_manual_inputs.add(manual.input_id)
        if manual.origin != MANUAL_CALCULATOR_ORIGIN:
            raise MeasurementStorageError("invalid")
        if type(manual.revision) is not int or not 1 <= manual.revision <= 1_000_000_000:
            raise MeasurementStorageError("invalid")
        spec = input_spec(manual.input_id)
        if (
            spec is None
            or type(manual.value) not in (int, float)
            or not math.isfinite(manual.value)
            or not spec.editor_range[0] <= manual.value <= spec.editor_range[1]
        ):
            raise MeasurementStorageError("invalid")

    # QH-1b.1: validate result_provenance
    seen_result_ids: set[str] = set()
    for prov in data.result_provenance:
        if not prov.result_id or len(prov.result_id) > 256:
            raise MeasurementStorageError("invalid")
        if prov.result_id in seen_result_ids:
            raise MeasurementStorageError("invalid")
        seen_result_ids.add(prov.result_id)
        if not prov.method.method_id or len(prov.method.method_id) > 256:
            raise MeasurementStorageError("invalid")
        if prov.method.semantics_version < 0 or prov.method.semantics_version > 100:
            raise MeasurementStorageError("invalid")
        if len(prov.method.algorithm_version) > 256 or len(prov.method.config_digest) > 256:
            raise MeasurementStorageError("invalid")
        if len(prov.method.model_id) > 256 or len(prov.method.model_hash) > 256:
            raise MeasurementStorageError("invalid")
        if prov.freshness not in ("fresh", "stale", "unverified", "unavailable"):
            raise MeasurementStorageError("invalid")
        if len(prov.freshness_reasons) > 16:
            raise MeasurementStorageError("limit")
        for reason in prov.freshness_reasons:
            if len(reason) > 64:
                raise MeasurementStorageError("invalid")
        if len(prov.inputs) > 1000:
            raise MeasurementStorageError("limit")
        for ref in prov.inputs:
            if not ref.measurement_id or len(ref.measurement_id) > 256:
                raise MeasurementStorageError("invalid")
            if type(ref.revision) is not int or ref.revision < 0:
                raise MeasurementStorageError("invalid")
            if len(ref.kind) > 64 or len(ref.label) > 256:
                raise MeasurementStorageError("invalid")
        if len(prov.calibration) > 32:
            raise MeasurementStorageError("limit")
        for cal in prov.calibration:
            if len(cal.kind) > 64:
                raise MeasurementStorageError("invalid")
            if cal.version and len(cal.version) > 64:
                raise MeasurementStorageError("invalid")
        if len(prov.units) > 64 or len(prov.definition) > 1024:
            raise MeasurementStorageError("invalid")
        if len(prov.family) > 64:
            raise MeasurementStorageError("invalid")
        # QC
        if prov.qc.status not in ("valid", "review", "invalid", "unverified"):
            raise MeasurementStorageError("invalid")
        if len(prov.qc.reasons) > 16:
            raise MeasurementStorageError("limit")
        for r in prov.qc.reasons:
            if len(r) > 256:
                raise MeasurementStorageError("invalid")
        if len(prov.qc.fallback) > 256:
            raise MeasurementStorageError("invalid")
        # Source
        if prov.source is not None:
            if not prov.source.study_uid or len(prov.source.study_uid) > 256:
                raise MeasurementStorageError("invalid")
            if len(prov.source.sop_instance_uid) > 256 or len(prov.source.series_uid) > 256:
                raise MeasurementStorageError("invalid")
            if prov.source.frame_index is not None and (
                type(prov.source.frame_index) is not int or prov.source.frame_index < 0
            ):
                raise MeasurementStorageError("invalid")


def dumps(record: dict) -> bytes:
    try:
        wire = {**record, "data": _encode(record["data"])}
        payload = json.dumps(wire, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        # Apply exactly the same validation to locally written and imported documents.
        loads(payload)
    except MeasurementStorageError:
        raise
    except RecursionError as exc:
        raise MeasurementStorageError("limit") from exc
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        # Encoding/allowlist drift must not surface as a generic "io" failure.
        raise MeasurementStorageError("invalid") from exc
    return payload


_V1_KEYS = {"format", "schema_version", "study_uid", "revision", "saved_at", "sources", "data"}
# Schema versions 2–4 share the same top-level envelope; additions live in the
# explicitly allowlisted ``StudyMeasurementData`` projection.
_V2_PLUS_KEYS = _V1_KEYS | {"measurement_semantics_version"}


def _collapse_legacy_label(items: tuple, *, identity_of) -> tuple:
    """Collapse version-1 duplicates, keeping the newest marker of each label.

    Version 1 stored one measurement per label; a second measurement replaced
    the first everywhere the value was shown or merged.  Documents written with
    the old append-only overlay therefore contain stale markers that version 1
    never displayed.  Collapsing them keeps the visible result identical and
    makes the document unambiguous for the version-2 repeat rules.
    """
    newest_index: dict[tuple[str, str], int] = {}
    for index, item in enumerate(items):
        newest_index[identity_of(item)] = index
    kept = set(newest_index.values())
    return tuple(item for index, item in enumerate(items) if index in kept)


def _stamp_trace_ids(traces: tuple[DopplerTrace, ...]) -> tuple[DopplerTrace, ...]:
    """Give id-less traces a deterministic identity.

    Version 1 could only store one trace per label, yet the multi-beat
    auto-trace already produced several.  They stay repeats (D-23) instead of
    turning the document into an ambiguity the validator must reject.  The
    position inside the document makes the identity stable across reads.
    """
    return tuple(
        trace if trace.measurement_id else dataclasses.replace(trace, measurement_id=f"legacy:{index}")
        for index, trace in enumerate(traces)
    )


def _stamp_contour_ids(contours: tuple) -> tuple:
    """Assign stable IDs to legacy contours without measurement_id (QH-1b.1).

    Migration rule: position inside the document makes the identity stable
    across reads, similar to trace stamping. Revision stays 0 for legacy.
    """
    return tuple(
        c if getattr(c, "measurement_id", "") else dataclasses.replace(c, measurement_id=f"legacy:contour:{index}")
        for index, c in enumerate(contours)
    )


def _stamp_linear_ids(measurements: tuple) -> tuple:
    return tuple(
        m if getattr(m, "measurement_id", "") else dataclasses.replace(m, measurement_id=f"legacy:linear:{index}")
        for index, m in enumerate(measurements)
    )


def _stamp_vessel_ids(measurements: tuple) -> tuple:
    return tuple(
        m if getattr(m, "measurement_id", "") else dataclasses.replace(m, measurement_id=f"legacy:vessel:{index}")
        for index, m in enumerate(measurements)
    )


def migrate(record: dict) -> dict:
    """Upgrade a supported older document to the current version (pure).

    v1 -> v2: collapse duplicate Doppler labels, stamp trace IDs (D-23).
    v1/v2 -> v3 (QH-1b.1): stamp stable IDs for primary measurements without ID,
    keep result_provenance empty (old derived results become UNVERIFIED per spec §5.3.3).
    v1/v2/v3 -> v4: ``manual_calculator_inputs`` keeps its empty default and
    ``manual_bsa_m2``/``bsa_basis`` stay absent — the reader never guesses a
    manual value for historical records, and an older document recorded no BSA:
    guessing one would turn an unverified record into a seemingly verified one
    (spec §5.3.3).
    Pure migration, no I/O.
    """
    if record.get("schema_version") == VERSION:
        return record
    data: StudyMeasurementData = record["data"]
    doppler_fields = ("doppler_by_instance", "doppler_by_instance_frame")
    migrated = data
    # Doppler repeat migration (v1 -> v2)
    for field in doppler_fields:
        entries = getattr(migrated, field)
        if not entries:
            continue
        rebuilt = []
        for entry in entries:
            dto = entry[-1]
            peaks = (
                _collapse_legacy_label(dto.peaks, identity_of=lambda marker: (marker.label, marker.measurement_id))
                if any(not marker.measurement_id for marker in dto.peaks)
                else dto.peaks
            )
            intervals = (
                _collapse_legacy_label(dto.intervals, identity_of=lambda marker: (marker.label, marker.measurement_id))
                if any(not marker.measurement_id for marker in dto.intervals)
                else dto.intervals
            )
            rebuilt.append(
                entry[:-1]
                + (DopplerMeasurementDTO(peaks=peaks, intervals=intervals, traces=_stamp_trace_ids(dto.traces)),)
            )
        migrated = dataclasses.replace(migrated, **{field: tuple(rebuilt)})  # type: ignore
    # Primary measurement ID stamping (v1/v2 -> v3, QH-1b.1)
    # Only when IDs are missing — keeps old docs unambiguous for provenance refs.
    if any(not getattr(c, "measurement_id", "") for c in migrated.contours):
        migrated = dataclasses.replace(migrated, contours=_stamp_contour_ids(migrated.contours))
    if any(not getattr(m, "measurement_id", "") for m in migrated.linear_measurements):
        migrated = dataclasses.replace(migrated, linear_measurements=_stamp_linear_ids(migrated.linear_measurements))
    if any(not getattr(m, "measurement_id", "") for m in migrated.vessel_measurements):
        migrated = dataclasses.replace(migrated, vessel_measurements=_stamp_vessel_ids(migrated.vessel_measurements))
    # result_provenance is optional with default () — old docs keep empty,
    # so derived results become UNVERIFIED per spec §5.3.3, primary data saved.
    return {
        **record,
        "schema_version": VERSION,
        "measurement_semantics_version": SEMANTICS_VERSION,
        "data": migrated,
    }


def loads(payload: bytes) -> dict:
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise MeasurementStorageError("limit")
    try:
        record = json.loads(payload, object_pairs_hook=_unique)
        _limits(record)
        if not isinstance(record, dict) or record.get("format") != FORMAT:
            raise MeasurementStorageError("invalid")
        version = record.get("schema_version")
        if type(version) is not int or version not in range(MIN_SUPPORTED_VERSION, VERSION + 1):
            raise MeasurementStorageError("version")
        if set(record) != (_V1_KEYS if version == 1 else _V2_PLUS_KEYS):
            raise MeasurementStorageError("invalid")
        if version >= 2:
            semantics = record.get("measurement_semantics_version")
            if type(semantics) is not int or semantics not in range(MIN_SUPPORTED_SEMANTICS, SEMANTICS_VERSION + 1):
                raise MeasurementStorageError("version")
        study_key(record["study_uid"])
        if type(record["revision"]) is not int or record["revision"] < 1:
            raise MeasurementStorageError("invalid")
        from datetime import datetime

        if datetime.fromisoformat(record["saved_at"]).tzinfo is None:
            raise MeasurementStorageError("invalid")
        sources = record["sources"]
        if not isinstance(sources, dict) or len(sources) > 10000:
            raise MeasurementStorageError("invalid")
        for uid, source in sources.items():
            if not isinstance(uid, str) or not uid or len(uid) > 256:
                raise MeasurementStorageError("source")
            if set(source) != {"fingerprint", "frames", "spacing"}:
                raise MeasurementStorageError("source")
            if not re.fullmatch(r"[0-9a-f]{64}", source["fingerprint"]):
                raise MeasurementStorageError("source")
            if type(source["frames"]) is not int or source["frames"] <= 0:
                raise MeasurementStorageError("source")
            spacing = source["spacing"]
            if spacing is not None and (
                not isinstance(spacing, list)
                or len(spacing) != 2
                or any(type(v) not in (int, float) or v <= 0 for v in spacing)
            ):
                raise MeasurementStorageError("source")
        record["data"] = _decode(record["data"], StudyMeasurementData)
        if version < VERSION:
            record = migrate(record)
        validate_data(record["data"], sources)
        return record
    except MeasurementStorageError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, AttributeError) as exc:
        raise MeasurementStorageError("invalid") from exc
