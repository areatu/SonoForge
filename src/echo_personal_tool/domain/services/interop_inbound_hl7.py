"""Pure HL7 v2 inbound parsers: ORM^O01 / OMG^O19 orders, ADT events (#626) and
ORU^R01 result reports (full report import).

Parsing only — no sockets, no I/O. The MLLP listener (infrastructure) hands a
decoded message string here and gets back normalized domain events; the ACK
is built with :func:`interop_hl7.build_ack`.
"""

from __future__ import annotations

import base64
import binascii
import re

from echo_personal_tool.domain.models.imported_report import ImportedMeasurement, ImportedReport
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


def parse_inbound(message: str) -> OrderEvent | DemographicsEvent | ImportedReport:
    """Dispatch on MSH-9: ORM/OMG -> order, ADT -> demographics, ORU -> report."""
    code, _trigger = message_type(message)
    if code in ("ORM", "OMG"):
        return parse_orm(message)
    if code == "ADT":
        return parse_adt(message)
    if code == "ORU":
        return parse_oru_r01(message)
    raise Hl7ParseError(f"unsupported_message:{code}")


# ── ORU^R01 result reports (full report import) ──────────────────────

_ESCAPE = "\\"


def unescape_hl7(text: str) -> str:
    """Reverse :func:`interop_hl7.escape_hl7` for inbound text fields."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == _ESCAPE and i + 1 < len(text):
            seq = text[i + 1]
            if seq == "E":
                out.append(_ESCAPE)
            elif seq == "F":
                out.append("&")
            elif seq == "S":
                out.append("^")
            elif seq == "T":
                out.append("~")
            elif seq == "R":
                out.append("|")
            elif text.startswith(".br", i + 1):
                out.append("\n")
                i += 3
            else:
                out.append(text[i])
            i += 2
            # HL7 escape sequences are ESC-letter-ESC; drop the closing ESC.
            if i < len(text) and text[i] == _ESCAPE:
                i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _hl7_dt_to_iso(raw: str) -> str:
    """``YYYYMMDDHHMMSS[.ZZZZ][+/-ZZZZ]`` → ISO-8601; date-only → ``YYYY-MM-DD``."""
    raw = raw.strip()
    if len(raw) >= 14:
        base = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}T{raw[8:10]}:{raw[10:12]}:{raw[12:14]}"
        rest = raw[14:]
        if rest.startswith("."):
            frac, _, rest = rest[1:].partition("+")
            base += f".{frac[:6]}"
            if rest or "-" in raw[14:]:
                base += f"+{rest}" if rest else ""
        elif rest.startswith(("+", "-")):
            base += rest
        return base
    if len(raw) >= 8:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _parse_oru_obx(fields: list[str]) -> tuple[str, str, str, str, str, str, str, str, str] | None:
    """Return (sub_type, code, text, value, unit, norm, flag, status, datetime) for an OBX."""
    sub_type = _field(fields, 2)
    identifier = _field(fields, 3)
    value = _field(fields, 5)
    unit = _component(_field(fields, 6), 0)
    norm = _field(fields, 7)
    flag = _field(fields, 8)
    status = _field(fields, 11)
    stamp = _hl7_dt_to_iso(_field(fields, 14))
    return sub_type, _component(identifier, 0), _component(identifier, 1), value, unit, norm, flag, status, stamp


def parse_oru_r01(message: str) -> ImportedReport:
    """Parse an ORU^R01 result message into an :class:`ImportedReport`.

    Reads PID (patient), OBR (accession/procedure/physician OBR-32), OBX|NM
    rows (measurements), OBX|TX with code CONCL (conclusion) and OBX|ED
    (embedded PDF, Base64 payload in OBX-5 component 4).
    """
    code, trigger = message_type(message)
    if code != "ORU":
        raise Hl7ParseError(f"not_a_result:{code}^{trigger}")
    patient: PatientDemographics | None = None
    accession = ""
    procedure_code = ""
    procedure_description = ""
    physician = ""
    observed_at = ""
    status = "F"
    conclusion = ""
    pdf_bytes: bytes | None = None
    pdf_title = ""
    measurements: list[ImportedMeasurement] = []
    report_id = ""
    for fields in split_segments(message):
        if not fields:
            continue
        name = fields[0]
        if name == "MSH":
            report_id = _field(fields, 10)
        elif name == "PID":
            patient = _parse_pid(fields)
        elif name == "OBR":
            accession = _component(_field(fields, 3), 0) or _component(_field(fields, 2), 0)
            procedure_code = _component(_field(fields, 4), 0)
            procedure_description = _component(_field(fields, 4), 1)
            observed_at = _hl7_dt_to_iso(_field(fields, 7) or _field(fields, 32))
            status = _field(fields, 25) or status
            physician = unescape_hl7(_field(fields, 32))
        elif name == "OBX":
            parsed = _parse_oru_obx(fields)
            if parsed is None:
                continue
            sub_type, obx_code, obx_text, value, unit, norm, flag, obx_status, stamp = parsed
            if sub_type == "NM":
                measurements.append(
                    ImportedMeasurement(
                        code=obx_code,
                        text=unescape_hl7(obx_text),
                        value=unescape_hl7(value),
                        unit=unit,
                        norm=unescape_hl7(norm),
                        flag=flag,
                        status=obx_status or status,
                        datetime=stamp or observed_at,
                    )
                )
            elif sub_type == "TX" and obx_code == "CONCL":
                conclusion = unescape_hl7(value)
            elif sub_type == "ED":
                pdf_title = unescape_hl7(obx_text)
                payload = _component(value, 3)
                if payload:
                    try:
                        pdf_bytes = base64.b64decode(payload.encode("ascii"), validate=True)
                    except (ValueError, binascii.Error) as exc:
                        raise Hl7ParseError("bad_embedded_payload") from exc
    if not report_id and not accession:
        raise Hl7ParseError("oru_without_ids")
    return ImportedReport(
        report_id=report_id or accession,
        source="hl7",
        patient=patient,
        accession_number=accession,
        procedure_code=procedure_code,
        procedure_description=unescape_hl7(procedure_description),
        physician=physician,
        conclusion=conclusion,
        status=status,
        observed_at=observed_at,
        measurements=measurements,
        pdf_bytes=pdf_bytes,
        pdf_title=pdf_title,
    )
