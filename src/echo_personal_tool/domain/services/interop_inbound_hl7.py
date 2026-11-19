"""Pure HL7 v2 inbound parsers: ORM^O01 / OMG^O19 orders and ADT events (#626).

Parsing only — no sockets, no I/O. The MLLP listener (infrastructure) hands a
decoded message string here and gets back normalized domain events; the ACK
is built with :func:`interop_hl7.build_ack`.
"""

from __future__ import annotations

import re

from echo_personal_tool.domain.models.worklist import (
    AdtEvent,
    DemographicsEvent,
    OrderEvent,
    PatientDemographics,
    PatientMerge,
)

_UID_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")


class Hl7ParseError(ValueError):
    """Raised when an inbound message cannot be parsed into domain events."""


def split_segments(message: str) -> list[list[str]]:
    """Split a raw HL7 v2 message into segments of fields (MSH field numbering kept)."""
    segments: list[list[str]] = []
    for raw_line in message.replace("\r\n", "\r").split("\r"):
        line = raw_line.strip("\n")
        if not line:
            continue
        segments.append(line.split("|"))
    return segments


def _field(fields: list[str], index: int) -> str:
    """1-based HL7 field access.

    For regular segments field N is ``fields[N]``. For MSH the separator is
    MSH-1 itself, so MSH-N is ``fields[N - 1]`` (MSH-2 == ``fields[1]``).
    """
    if fields and fields[0] == "MSH":
        return fields[index - 1] if len(fields) >= index else ""
    return fields[index] if len(fields) > index else ""


def _component(field: str, index: int) -> str:
    parts = field.split("^")
    return parts[index] if len(parts) > index else ""


def message_type(message: str) -> tuple[str, str]:
    """Return (message code, trigger event), e.g. ("ORM", "O01") from MSH-9."""
    for fields in split_segments(message):
        if fields and fields[0] == "MSH":
            msh9 = _field(fields, 9)
            code, _, trigger = msh9.partition("^")
            return code, trigger
    raise Hl7ParseError("missing_msh")


def _parse_pid(fields: list[str]) -> PatientDemographics:
    pid_id = _component(_field(fields, 3), 0)
    family = _component(_field(fields, 5), 0)
    given = _component(_field(fields, 5), 1)
    name = f"{family} {given}".strip() or family or given
    birth = _field(fields, 7)
    sex = _field(fields, 8)
    return PatientDemographics(
        patient_id=pid_id,
        name=name,
        birth_date=f"{birth[0:4]}-{birth[4:6]}-{birth[6:8]}" if len(birth) >= 8 else birth,
        sex={"M": "M", "F": "F"}.get(sex, "O" if sex else ""),
        mrn=pid_id,
    )


def _parse_order(message: str, msg_type: str) -> OrderEvent:
    control = ""
    accession = ""
    placer = ""
    procedure_code = ""
    procedure_description = ""
    scheduled = ""
    station = ""
    referring = ""
    indications = ""
    patient: PatientDemographics | None = None
    for fields in split_segments(message):
        if not fields:
            continue
        name = fields[0]
        if name == "PID":
            patient = _parse_pid(fields)
        elif name == "ORC":
            control = _field(fields, 1)
            placer = _component(_field(fields, 2), 0)
        elif name == "OBR":
            # OBR-2 placer order number, OBR-3 filler order number (accession)
            accession = _component(_field(fields, 3), 0) or _component(_field(fields, 2), 0)
            procedure_code = _component(_field(fields, 4), 0)
            procedure_description = _component(_field(fields, 4), 1)
            # OBR-7 observation date/time (v2.5), OBR-6 requested date/time, OBR-8 end date/time
            scheduled = _field(fields, 7) or _field(fields, 6) or _field(fields, 8)
            # OBR-16 ordering provider (v2.5), OBR-15/14 orderer fallbacks
            referring = ""
            for idx in (16, 15, 14):
                referring = _component(_field(fields, idx), 1) or _component(_field(fields, idx), 0)
                if referring:
                    break
            # OBR-18 carries the Study Instance UID in the local profile when UID-shaped
            candidate = _component(_field(fields, 18), 0)
            if candidate and _UID_RE.match(candidate):
                study_uid = candidate
        elif name == "PV1":
            station = _component(_field(fields, 3), 0)
        elif name == "NTE":
            indications = _field(fields, 3)
    study_uid = ""
    scheduled_iso = ""
    if len(scheduled) >= 14:
        scheduled_iso = f"{scheduled[0:4]}-{scheduled[4:6]}-{scheduled[6:8]}T{scheduled[8:10]}:{scheduled[10:12]}:{scheduled[12:14]}"
    elif len(scheduled) >= 8:
        scheduled_iso = f"{scheduled[0:4]}-{scheduled[4:6]}-{scheduled[6:8]}"
    return OrderEvent(
        message_type=msg_type,
        order_control=control,
        accession_number=accession,
        placer_order_number=placer,
        patient=patient,
        procedure_code=procedure_code,
        procedure_description=procedure_description,
        scheduled_datetime=scheduled_iso,
        scheduled_station_ae=station,
        referring_physician=referring,
        indications=indications,
        study_instance_uid=study_uid,
        source="hl7",
    )


def parse_orm(message: str) -> OrderEvent:
    """Parse an ORM^O01 or OMG^O19 order message into an :class:`OrderEvent`."""
    code, trigger = message_type(message)
    if code not in ("ORM", "OMG"):
        raise Hl7ParseError(f"not_an_order:{code}^{trigger}")
    return _parse_order(message, f"{code}^{trigger}")


def parse_adt(message: str) -> DemographicsEvent:
    """Parse an ADT^A01/A04/A08/A31/A40 message into a :class:`DemographicsEvent`."""
    code, trigger = message_type(message)
    if code != "ADT":
        raise Hl7ParseError(f"not_adt:{code}^{trigger}")
    if trigger not in {e.value for e in AdtEvent}:
        raise Hl7ParseError(f"unsupported_adt:{trigger}")
    patient: PatientDemographics | None = None
    merge: PatientMerge | None = None
    for fields in split_segments(message):
        if not fields:
            continue
        if fields[0] == "PID":
            patient = _parse_pid(fields)
        elif fields[0] == "MRG":
            # MRG-1 prior patient identifier (source), MRG-7 current patient id (target)
            merge = PatientMerge(source_id=_component(_field(fields, 1), 0), target_id=_component(_field(fields, 7), 0))
    if patient is None and merge is None:
        raise Hl7ParseError("adt_without_pid_or_mrg")
    return DemographicsEvent(event=trigger, patient=patient, merge=merge, source="hl7")


def parse_inbound(message: str) -> OrderEvent | DemographicsEvent:
    """Dispatch on MSH-9: ORM/OMG -> order, ADT -> demographics."""
    code, _trigger = message_type(message)
    if code in ("ORM", "OMG"):
        return parse_orm(message)
    if code == "ADT":
        return parse_adt(message)
    raise Hl7ParseError(f"unsupported_message:{code}")
