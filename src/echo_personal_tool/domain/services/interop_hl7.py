"""HL7 v2 ``ORU^R01`` builder and ACK parser (#625) — pure domain, stdlib only.

Builds an unsolicited observation message (v2.5.1, with v2.3.1/v2.4
compatibility: no fields beyond v2.3.1 are required by receivers in common
use) from a plain interop DTO.  Segments: ``MSH``, ``PID``, ``PV1``, ``ORC``,
``OBR`` (the signing physician in ``OBR-32``), one ``OBX|NM`` per measured
value (LOINC identifier, UCUM units, reference range, abnormal flag,
observation status ``P``/``F``/``C``), ``OBX|TX`` for the conclusion and an
optional ``OBX|ED`` carrying the signed PDF as Base64.

MLLP framing bytes and the ACK wire parse live here too, so a loopback test
can exercise frame → message → ACK without sockets.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from echo_personal_tool.domain.terminology import TerminologyCode, code_for
from echo_personal_tool.domain.terminology.units import ConversionError, to_canonical_ucum

#: HL7 v2 delimiters.
FIELD_SEP = "|"
COMPONENT_SEP = "^"
SUBCOMP_SEP = "&"
REP_SEP = "~"
ESCAPE_CHAR = "\\"

#: MLLP framing bytes.
MLLP_START = b"\x0b"
MLLP_END = b"\x1c"
MLLP_CR = b"\x0d"

#: HL7 v2 versions this builder targets (MSH-12).
SUPPORTED_HL7_VERSIONS: tuple[str, ...] = ("2.5.1", "2.4", "2.3.1")
DEFAULT_HL7_VERSION = "2.5.1"

#: Encodings allowed for outbound messages (MSH-18 is always UTF-8-capable;
#: cp1251 is the legacy Cyrillic fallback some RIS still require).
SUPPORTED_ENCODINGS: tuple[str, ...] = ("utf-8", "cp1251")

_UTC = timezone.utc  # noqa: UP017 - aligned with ruff target py310


class Hl7BuildError(ValueError):
    """The interop DTO cannot be rendered as HL7 (safe code, no PHI)."""


@dataclass(frozen=True)
class InteropPatient:
    """PID/PV1 source data (already de-identified to the level the user chose)."""

    patient_id: str = ""
    name: str = ""  # «Family Given» or as displayed
    birth_date: str = ""  # YYYY-MM-DD
    sex: str = ""  # M / F / U
    study_date: str = ""  # YYYY-MM-DD
    institution: str = ""


@dataclass(frozen=True)
class InteropObservation:
    """One OBX|NM row."""

    measurement_id: str
    label: str
    value: str
    unit: str  # display unit, converted to canonical UCUM on build
    quantity: str
    norm: str = ""
    pathological: bool = False
    status: str = "F"  # HL7 OBX-11: P / F / C

    def terminology(self) -> TerminologyCode:
        return code_for(self.measurement_id)


@dataclass(frozen=True)
class InteropReport:
    """Everything one ORU^R01 carries."""

    patient: InteropPatient
    study_uid: str = ""
    order_id: str = ""
    message_id: str = ""
    observation_datetime: str = ""  # ISO-8601 UTC
    physician: str = ""  # OBR-32 principal interpreter / signer
    conclusion: str = ""
    observations: tuple[InteropObservation, ...] = ()
    pdf_bytes: bytes | None = None  # signed report PDF for OBX|ED
    pdf_title: str = "Signed report PDF"
    status: str = "F"


@dataclass(frozen=True)
class AckResult:
    """Parsed HL7 ACK: ``AA`` accept, ``AE``/``AR`` application error/reject."""

    code: str  # MSA-1
    control_id: str  # MSA-2 echoed MSH-10
    text: str = ""

    @property
    def accepted(self) -> bool:
        return self.code == "AA"


def escape_hl7(text: str) -> str:
    """Apply HL7 v2 escape sequences to *text* (``& ^ ~ \ |`` and newlines)."""
    return (
        text.replace(ESCAPE_CHAR, f"{ESCAPE_CHAR}E{ESCAPE_CHAR}")
        .replace("&", f"{ESCAPE_CHAR}F{ESCAPE_CHAR}")
        .replace("^", f"{ESCAPE_CHAR}S{ESCAPE_CHAR}")
        .replace("~", f"{ESCAPE_CHAR}T{ESCAPE_CHAR}")
        .replace("|", f"{ESCAPE_CHAR}R{ESCAPE_CHAR}")
        .replace("\r", f"{ESCAPE_CHAR}.br{ESCAPE_CHAR}")
        .replace("\n", f"{ESCAPE_CHAR}.br{ESCAPE_CHAR}")
    )


def hl7_datetime(iso: str, *, now: datetime | None = None) -> str:
    """ISO-8601 → HL7 ``YYYYMMDDHHMMSS`` (UTC when *iso* has an offset)."""
    text = iso or (now or datetime.now(_UTC)).isoformat()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise Hl7BuildError("invalid_datetime") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_UTC)
    return parsed.strftime("%Y%m%d%H%M%S")


def hl7_date(iso_date: str) -> str:
    """``YYYY-MM-DD`` → HL7 ``YYYYMMDD``; empty stays empty."""
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso_date.strip())
    if not match:
        return ""
    return "".join(match.groups())


def _sex_code(sex: str) -> str:
    value = sex.strip().upper()
    if value in ("M", "F"):
        return value
    return "U"


def _name_xpn(name: str) -> str:
    """«Family Given Middle» → HL7 XPN ``FAMILY^GIVEN^MIDDLE`` (escaped)."""
    parts = [part for part in name.strip().split() if part]
    if not parts:
        return ""
    family = parts[0]
    given = parts[1] if len(parts) > 1 else ""
    middle = " ".join(parts[2:]) if len(parts) > 2 else ""
    return COMPONENT_SEP.join(escape_hl7(p) for p in (family, given, middle))


def _ce(code: str, text: str, system: str) -> str:
    return COMPONENT_SEP.join((escape_hl7(code), escape_hl7(text), system))


def build_oru_r01(
    report: InteropReport,
    *,
    version: str = DEFAULT_HL7_VERSION,
    sending_app: str = "SONOFORGE",
    sending_facility: str = "",
    receiving_app: str = "RIS",
    receiving_facility: str = "",
    now: datetime | None = None,
) -> str:
    """Render the ORU^R01 message text (segments joined by ``\\r``)."""
    if version not in SUPPORTED_HL7_VERSIONS:
        raise Hl7BuildError("unsupported_version")
    current = now or datetime.now(_UTC)
    timestamp = hl7_datetime(report.observation_datetime, now=current)
    message_id = report.message_id or f"MSG{current.strftime('%Y%m%d%H%M%S')}{current.microsecond % 100000:05d}"
    order_id = report.order_id or f"ORD{current.strftime('%Y%m%d%H%M%S')}"
    facility = escape_hl7(report.patient.institution or sending_facility)

    msh = FIELD_SEP.join(
        [
            f"MSH{FIELD_SEP}^~{ESCAPE_CHAR}&",  # MSH-1 is the field sep, MSH-2 the raw encoding characters
            escape_hl7(sending_app),
            facility or escape_hl7(sending_facility),
            escape_hl7(receiving_app),
            escape_hl7(receiving_facility),
            timestamp,
            "",
            f"ORU{COMPONENT_SEP}R01",
            escape_hl7(message_id),
            "P",
            version,
        ]
    )
    pid = FIELD_SEP.join(
        [
            "PID",
            "1",
            "",
            escape_hl7(report.patient.patient_id) + f"{COMPONENT_SEP}{COMPONENT_SEP}{COMPONENT_SEP}HIS",
            _name_xpn(report.patient.name),
            hl7_date(report.patient.birth_date),
            _sex_code(report.patient.sex),
        ]
    )
    pv1 = FIELD_SEP.join(["PV1", "1", "I"])
    orc = FIELD_SEP.join(["ORC", "NW", escape_hl7(order_id)])
    obr = FIELD_SEP.join(
        [
            "OBR",
            "1",
            escape_hl7(order_id),
            "",
            _ce("ECHO-RPT", "Echocardiography report", "99SONOFORGE"),
            "",
            "",
            timestamp,
            *[""] * 24,  # OBR-8 … OBR-31 stay empty
            escape_hl7(report.physician),  # OBR-32 principal interpreter
        ]
    )

    segments = [msh, pid, pv1, orc, obr]
    sequence = 1
    for obs in report.observations:
        code = obs.terminology()
        try:
            canonical_value, ucum = to_canonical_ucum(obs.value, obs.unit, obs.quantity)
        except ConversionError:  # any conversion failure keeps the raw value with its own UCUM
            canonical_value, ucum = obs.value, obs.unit
        identifier = _ce(
            code.loinc or code.measurement_id, code.text or obs.label, "LN" if code.loinc else "99SONOFORGE"
        )
        flag = "L" if obs.pathological and obs.norm else ("H" if obs.pathological else "N")
        obx = FIELD_SEP.join(
            [
                "OBX",
                str(sequence),
                "NM",
                identifier,
                "",
                escape_hl7(canonical_value),
                _ce(ucum, ucum, "UCUM"),
                escape_hl7(obs.norm),
                flag,
                "",
                "",
                obs.status or report.status,
                "",
                timestamp,
            ]
        )
        segments.append(obx)
        sequence += 1

    if report.conclusion.strip():
        segments.append(
            FIELD_SEP.join(
                [
                    "OBX",
                    str(sequence),
                    "TX",
                    _ce("CONCL", "Conclusion", "99SONOFORGE"),
                    "",
                    escape_hl7(report.conclusion.strip()),
                    "",
                    "",
                    "",
                    "",
                    "",
                    report.status,
                    "",
                    timestamp,
                ]
            )
        )
        sequence += 1

    if report.pdf_bytes:
        payload = base64.b64encode(report.pdf_bytes).decode("ascii")
        segments.append(
            FIELD_SEP.join(
                [
                    "OBX",
                    str(sequence),
                    "ED",
                    _ce("PDF", escape_hl7(report.pdf_title), "99SONOFORGE"),
                    "",
                    f"application/pdf{COMPONENT_SEP}PDF{COMPONENT_SEP}Base64{COMPONENT_SEP}{payload}",
                    "",
                    "",
                    "",
                    "",
                    "",
                    report.status,
                    "",
                    timestamp,
                ]
            )
        )

    return "\r".join(segments) + "\r"


def encode_message(message: str, *, encoding: str = "utf-8") -> bytes:
    """Encode a message for the wire; only allowlisted encodings, strict."""
    if encoding not in SUPPORTED_ENCODINGS:
        raise Hl7BuildError("unsupported_encoding")
    try:
        return message.encode(encoding)
    except UnicodeEncodeError as exc:
        raise Hl7BuildError("unencodable") from exc


def frame_mlp(payload: bytes) -> bytes:
    """Wrap *payload* in MLLP framing (SB … EB CR)."""
    if MLLP_START in payload or MLLP_END in payload:
        raise Hl7BuildError("framing-bytes-in-payload")
    return MLLP_START + payload + MLLP_END + MLLP_CR


def parse_ack(payload: bytes, *, encoding: str = "utf-8") -> AckResult:
    """Parse a raw ACK message payload (without MLLP framing)."""
    try:
        text = payload.decode(encoding)
    except UnicodeDecodeError as exc:
        raise Hl7BuildError("ack-undecodable") from exc
    code = ""
    control_id = ""
    ack_text = ""
    for segment in text.split("\r"):
        fields = segment.split(FIELD_SEP)
        if not fields:
            continue
        if fields[0] == "MSA" and len(fields) > 2:
            code = fields[1].strip()
            control_id = fields[2].strip() if len(fields) > 2 else ""
        elif fields[0] == "MSH" and len(fields) > 9:
            control_id = control_id or fields[9].strip()
        if fields[0] == "ERR" and len(fields) > 1:
            ack_text = fields[1].strip()
    if code not in ("AA", "AE", "AR"):
        raise Hl7BuildError("ack-unknown")
    return AckResult(code=code, control_id=control_id, text=ack_text)


def build_ack(
    message_control_id: str, accept: bool = True, *, version: str = DEFAULT_HL7_VERSION, now: datetime | None = None
) -> str:
    """Render an ACK for *message_control_id* (used by tests and loopback peers)."""
    if version not in SUPPORTED_HL7_VERSIONS:
        raise Hl7BuildError("unsupported_version")
    current = now or datetime.now(_UTC)
    code = "AA" if accept else "AE"
    msh = FIELD_SEP.join(
        [
            f"MSH{FIELD_SEP}^~{ESCAPE_CHAR}&",
            "RIS",
            "RECVFAC",
            "SONOFORGE",
            "FACILITY",
            hl7_datetime("", now=current),
            "",
            f"ACK{COMPONENT_SEP}R01",
            f"ACK{current.strftime('%H%M%S%f')}",
            "P",
            version,
        ]
    )
    msa = FIELD_SEP.join(["MSA", code, escape_hl7(message_control_id)])
    return "\r".join([msh, msa]) + "\r"
