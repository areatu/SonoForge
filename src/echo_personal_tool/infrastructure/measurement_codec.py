"""Bounded, versioned JSON for study measurements. No executable serialization.

The type registry and StudyMeasurementData field allowlist are deliberate: adding
an application field must not implicitly add patient data to the disk format.
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
from echo_personal_tool.domain.models.measurements import StrainReport
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement

MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
FORMAT = "sonoforge.study-measurements"
VERSION = 1
FIELDS = frozenset(
    """contours linear_measurements doppler_by_instance doppler_by_instance_frame
 doppler_calibration_by_instance doppler_calibration_by_instance_frame mmode_calibration_by_instance
 cine_segment_roi_by_instance manual_spacing_by_instance mmode_time_by_instance height_cm weight_kg
 height_source weight_source vessel_measurements simpson_area_by_frame strain""".split()
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
        fields = FIELDS if hint is StudyMeasurementData else {f.name for f in dataclasses.fields(hint)}
        if not isinstance(value, dict) or set(value) != fields:
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
    for field in ("doppler_by_instance", "doppler_by_instance_frame"):
        for entry in getattr(data, field):
            dto = entry[-1]
            for values in (dto.peaks, dto.intervals, dto.traces):
                if len({item.label for item in values}) != len(values) or any(len(item.label) > 256 for item in values):
                    raise MeasurementStorageError("invalid")
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


def loads(payload: bytes) -> dict:
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise MeasurementStorageError("limit")
    try:
        record = json.loads(payload, object_pairs_hook=_unique)
        _limits(record)
        if not isinstance(record, dict) or record.get("format") != FORMAT:
            raise MeasurementStorageError("invalid")
        if type(record.get("schema_version")) is not int or record["schema_version"] != VERSION:
            raise MeasurementStorageError("version")
        if set(record) != {"format", "schema_version", "study_uid", "revision", "saved_at", "sources", "data"}:
            raise MeasurementStorageError("invalid")
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
        validate_data(record["data"], sources)
        return record
    except MeasurementStorageError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, AttributeError) as exc:
        raise MeasurementStorageError("invalid") from exc
