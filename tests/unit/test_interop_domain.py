"""Pure-domain tests for the #625 interop builders (stdlib only, no Qt)."""

from __future__ import annotations

import base64
import json

import pytest

from echo_personal_tool.domain.services.interop_fhir import (
    FhirBuildError,
    build_fhir_bundle,
    bundle_to_json,
    fhir_signature_entry,
)
from echo_personal_tool.domain.services.interop_hl7 import (
    Hl7BuildError,
    InteropObservation,
    InteropPatient,
    InteropReport,
    build_ack,
    build_oru_r01,
    encode_message,
    escape_hl7,
    frame_mlp,
    hl7_date,
    hl7_datetime,
    parse_ack,
)
from echo_personal_tool.domain.terminology import (
    ConversionError,
    canonical_ucum_unit,
    code_for,
    code_for_ase_row,
    convert_value,
    ucum_for_display_unit,
)


def _report(**overrides) -> InteropReport:
    base = dict(
        patient=InteropPatient(
            patient_id="P-1",
            name="Иванов Иван Иванович",
            birth_date="1980-01-01",
            sex="M",
            study_date="2026-11-18",
            institution="Клиника №1",
        ),
        study_uid="1.2.840.1",
        physician="Петров П.П., врач УЗД",
        conclusion="Без патологии\nСинусовый ритм",
        observations=(
            InteropObservation(
                measurement_id="lv.lvedd", label="КДР ЛЖ", value="52", unit="mm", quantity="length", norm="35–56"
            ),
            InteropObservation(
                measurement_id="mv.e",
                label="E",
                value="80",
                unit="cm/s",
                quantity="velocity",
                norm="60–130",
                pathological=True,
            ),
        ),
        pdf_bytes=b"%PDF-1.4 signed",
        status="F",
    )
    base.update(overrides)
    return InteropReport(**base)


class TestTerminology:
    def test_known_measurement_carries_loinc(self) -> None:
        code = code_for("lv.lvedd")
        assert code.loinc == "8625-6"
        assert code.verified
        assert ("LN", "8625-6", "http://loinc.org") in code.coding_systems()

    def test_unknown_measurement_falls_back_to_local_code(self) -> None:
        code = code_for("some.unknown.parameter")
        assert code.loinc is None
        assert code.coding_systems()[-1][0] == "99SONOFORGE"

    def test_ase_row_lookup(self) -> None:
        assert code_for_ase_row("lv.lvedd").loinc == "8625-6"
        assert code_for_ase_row(None) is None
        assert code_for_ase_row("no.such.row") is None


class TestUnits:
    def test_ucum_codes(self) -> None:
        assert ucum_for_display_unit("mm") == "mm"
        assert ucum_for_display_unit("mmHg") == "mm[Hg]"
        assert ucum_for_display_unit("cm/s") == "cm/s"
        assert ucum_for_display_unit("%") == "%"
        assert canonical_ucum_unit("velocity") == "m/s"
        assert canonical_ucum_unit("pressure") == "mm[Hg]"

    def test_explicit_conversion(self) -> None:
        assert convert_value("52", "mm", "cm") == "5.2"
        assert convert_value("80", "cm/s", "m/s") == "0.8"
        assert convert_value("0.8", "m/s", "cm/s") == "80"
        assert convert_value("1.5", "s", "ms") == "1500"
        with pytest.raises(ConversionError):
            convert_value("52", "mm", "m/s")
        with pytest.raises(ConversionError):
            convert_value("abc", "mm", "cm")
        with pytest.raises(ConversionError):
            ucum_for_display_unit("furlongs")


class TestHl7Builder:
    def test_oru_r01_structure(self) -> None:
        message = build_oru_r01(_report(), version="2.5.1")
        segments = [s for s in message.split("\r") if s]
        names = [s.split("|")[0] for s in segments]
        assert names[:5] == ["MSH", "PID", "PV1", "ORC", "OBR"]
        msh = segments[0].split("|")
        assert msh[1] == "^~\\&"
        assert msh[8] == "ORU^R01"
        assert msh[11] == "2.5.1"
        obr = segments[4].split("|")
        assert obr[32] == "Петров П.П., врач УЗД"  # OBR-32 signing physician
        obx = [s.split("|") for s in segments if s.startswith("OBX")]
        nm = next(f for f in obx if f[2] == "NM")
        assert nm[3].startswith("8625-6^")  # LOINC identifier
        assert nm[5] == "52"  # mm is canonical for length
        assert nm[6].startswith("mm^") and nm[6].endswith("^UCUM")
        assert nm[7] == "35–56"
        assert nm[11] == "F"
        # cm/s converted to canonical m/s
        vel = [f for f in obx if f[2] == "NM" and f[3].startswith("8633-0")]
        assert vel[0][5] == "0.8"
        assert vel[0][6].startswith("m/s^")
        assert vel[0][8] in ("H", "L")  # pathological flag
        tx = next(f for f in obx if f[2] == "TX")
        assert "Без патологии" in tx[5]
        ed = next(f for f in obx if f[2] == "ED")
        assert ed[5].startswith("application/pdf^PDF^Base64^")
        assert base64.b64decode(ed[5].split("^")[-1]) == b"%PDF-1.4 signed"

    def test_escaping_and_encoding(self) -> None:
        assert escape_hl7("a|b^c~d&e\\f") == "a\\R\\b\\S\\c\\T\\d\\F\\e\\E\\f"
        message = build_oru_r01(_report(conclusion="строка | с | разделителями"))
        assert "\\R\\" in message
        payload = encode_message(message, encoding="cp1251")
        assert payload.decode("cp1251") == message
        with pytest.raises(Hl7BuildError):
            encode_message(message, encoding="utf-16")

    def test_version_guard(self) -> None:
        with pytest.raises(Hl7BuildError):
            build_oru_r01(_report(), version="2.9")
        for version in ("2.3.1", "2.4", "2.5.1"):
            assert ("|" + version + chr(13)) in build_oru_r01(_report(), version=version)

    def test_dates(self) -> None:
        assert hl7_date("2026-11-18") == "20261118"
        assert hl7_date("") == ""
        assert hl7_datetime("2026-11-18T10:00:00+00:00") == "20261118100000"

    def test_ack_roundtrip_and_mlp_frame(self) -> None:
        ack = build_ack("MSG123", accept=True)
        result = parse_ack(ack.encode("utf-8"))
        assert result.accepted and result.code == "AA" and result.control_id == "MSG123"
        reject = parse_ack(build_ack("MSG9", accept=False).encode())
        assert not reject.accepted and reject.code == "AE"
        framed = frame_mlp(b"MSH|^~\\&|x")
        assert framed[:1] == b"\x0b" and framed[-2:] == b"\x1c\x0d"
        with pytest.raises(Hl7BuildError):
            parse_ack(b"garbage")
        with pytest.raises(Hl7BuildError):
            frame_mlp(b"\x0b embedded")


class TestFhirBuilder:
    def test_bundle_contents(self) -> None:
        bundle = build_fhir_bundle(_report(), report_hash="a" * 64)
        types = [entry["resource"]["resourceType"] for entry in bundle["entry"]]
        assert types == [
            "Patient",
            "Practitioner",
            "ImagingStudy",
            "Observation",
            "Observation",
            "DiagnosticReport",
            "Provenance",
        ]
        obs = bundle["entry"][3]["resource"]
        assert obs["code"]["coding"][0]["system"] == "http://loinc.org"
        assert obs["code"]["coding"][0]["code"] == "8625-6"
        assert obs["valueQuantity"]["system"] == "http://unitsofmeasure.org"
        assert obs["valueQuantity"]["code"] == "mm"
        assert obs["referenceRange"][0]["text"] == "35–56"
        dr = bundle["entry"][5]["resource"]
        assert dr["presentedForm"][0]["contentType"] == "application/pdf"
        assert base64.b64decode(dr["presentedForm"][0]["data"]) == b"%PDF-1.4 signed"
        assert dr["conclusion"].startswith("Без патологии")
        prov = bundle["entry"][6]["resource"]
        assert prov["note"][0]["text"].endswith("a" * 64)

    def test_bundle_json_is_deterministic(self) -> None:
        def _stable() -> bytes:
            bundle = build_fhir_bundle(_report())
            bundle["meta"].pop("lastUpdated", None)
            for entry in bundle["entry"]:
                resource = entry["resource"]
                resource.pop("effectiveDateTime", None)
                resource.pop("issued", None)
                if resource["resourceType"] == "Provenance":
                    resource.pop("recorded", None)
            return bundle_to_json(bundle)

        assert _stable() == _stable()
        json.loads(bundle_to_json(build_fhir_bundle(_report())))

    def test_signature_entry_and_bundle_type_guard(self) -> None:
        sig = fhir_signature_entry(
            signed_at="2026-11-18T10:00:00+00:00",
            signer_reference="urn:uuid:practitioner",
            signature_b64="AAAA",
            key_id="0123456789abcdef",
        )
        assert sig["sigFormat"] == "application/ed25519+base64"
        bundle = build_fhir_bundle(_report(), bundle_type="transaction", signature=sig)
        assert bundle["type"] == "transaction"
        assert bundle["entry"][6]["resource"]["signature"][0]["data"] == "AAAA"
        with pytest.raises(FhirBuildError):
            build_fhir_bundle(_report(), bundle_type="searchset")
