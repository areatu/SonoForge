"""Pure-domain tests for Stage-4 inbound interop (#626): HL7 ORM/ADT parsers,
FHIR inbound parsers, the TID 5200 SR tree and the CDA R2 document."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from echo_personal_tool.domain.models.worklist import (
    AdtEvent,
    MppsUpdate,
    OrderControl,
    WorklistItem,
    WorklistStatus,
)
from echo_personal_tool.domain.services import interop_fhir_inbound, interop_inbound_hl7
from echo_personal_tool.domain.services.interop_cda import build_cda_r2
from echo_personal_tool.domain.services.interop_hl7 import InteropObservation, InteropPatient, InteropReport
from echo_personal_tool.domain.services.interop_inbound_hl7 import Hl7ParseError
from echo_personal_tool.domain.services.interop_sr import build_sr_tree

ORM_NEW = (
    "MSH|^~\\&|RIS|HOSP|SonoForge|US|20261118120000||ORM^O01|MSG1|P|2.5\r"
    "PID|1||P1^^^HOSP^MR||Ivanov^Ivan||19800101|M\r"
    "PV1|1|O|USLAB\r"
    "ORC|NW|ORD1\r"
    "OBR|1|ORD1|ACC42|ECHO^Echocardiography||||20261118130000||||||||||||Dr. Who\r"
    "NTE|1||dyspnea"
)

ORM_CANCEL = ORM_NEW.replace("ORM^O01", "ORM^O01").replace("ORC|NW", "ORC|CA")

ADT_UPDATE = (
    "MSH|^~\\&|HIS|HOSP|SonoForge|US|20261118120000||ADT^A08|MSG2|P|2.5\rPID|1||P1^^^HOSP^MR||Ivanov^Ivan||19800101|M"
)

ADT_MERGE = (
    "MSH|^~\\&|HIS|HOSP|SonoForge|US|20261118120000||ADT^A40|MSG3|P|2.5\r"
    "MRG|P1^^^HOSP^MR||||||P2^^^HOSP^MR\r"
    "PID|1||P2^^^HOSP^MR||Petrov^Petr||19900202|F"
)


def _report() -> InteropReport:
    return InteropReport(
        patient=InteropPatient(patient_id="P1", name="Ivanov Ivan", birth_date="1980-01-01", sex="M"),
        conclusion="Normal study.",
        observations=(
            InteropObservation(
                measurement_id="lv.lvedd", label="LVEDD", value="52", unit="mm", quantity="length", norm="35-56"
            ),
            InteropObservation(
                measurement_id="hr",
                label="Heart rate",
                value="70",
                unit="bpm",
                quantity="frequency",
                pathological=False,
            ),
        ),
    )


class TestHl7Inbound:
    def test_orm_new_order(self):
        event = interop_inbound_hl7.parse_orm(ORM_NEW)
        assert event.message_type == "ORM^O01"
        assert event.control is OrderControl.NEW
        assert event.accession_number == "ACC42"
        assert event.procedure_code == "ECHO"
        assert event.procedure_description == "Echocardiography"
        assert event.scheduled_datetime == "2026-11-18T13:00:00"
        assert event.scheduled_station_ae == "USLAB"
        assert event.indications == "dyspnea"
        assert event.patient is not None
        assert event.patient.patient_id == "P1"
        assert event.patient.name == "Ivanov Ivan"
        assert event.patient.birth_date == "1980-01-01"
        assert event.patient.sex == "M"

    def test_orm_cancel_control(self):
        event = interop_inbound_hl7.parse_orm(ORM_CANCEL)
        assert event.control is OrderControl.CANCEL

    def test_adt_update(self):
        event = interop_inbound_hl7.parse_adt(ADT_UPDATE)
        assert event.event == AdtEvent.UPDATE.value
        assert event.patient is not None and event.patient.patient_id == "P1"
        assert event.merge is None

    def test_adt_merge(self):
        event = interop_inbound_hl7.parse_adt(ADT_MERGE)
        assert event.event == "A40"
        assert event.merge is not None
        assert event.merge.source_id == "P1"
        assert event.merge.target_id == "P2"
        assert event.patient is not None and event.patient.patient_id == "P2"

    def test_dispatch_and_rejects(self):
        assert interop_inbound_hl7.parse_inbound(ORM_NEW).order_control == "NW"
        with pytest.raises(Hl7ParseError):
            interop_inbound_hl7.parse_inbound("MSH|^~\\&|A|B|C|D|20261118||QRY^A19|X|P|2.5\r")
        with pytest.raises(Hl7ParseError):
            interop_inbound_hl7.parse_adt(ORM_NEW)


class TestFhirInbound:
    def test_bundle_split(self):
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "P9",
                        "name": [{"family": "Sidorov", "given": ["Sidr"]}],
                        "birthDate": "1970-05-05",
                        "gender": "male",
                    }
                },
                {
                    "resource": {
                        "resourceType": "ServiceRequest",
                        "id": "SR1",
                        "subject": {"reference": "Patient/P9"},
                        "code": {"coding": [{"code": "ECHO", "system": "http://example.org/fhir"}], "text": "Echo"},
                        "occurrenceDateTime": "2026-11-18T13:00:00",
                        "identifier": [{"value": "ACC9"}],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "O1",
                        "subject": {"reference": "Patient/P9"},
                        "code": {"coding": [{"code": "8625-6", "system": "http://loinc.org"}]},
                        "valueQuantity": {"value": 52, "code": "mm"},
                        "effectiveDateTime": "2026-11-01T10:00:00",
                    }
                },
            ],
        }
        orders, patients, priors = interop_fhir_inbound.parse_bundle(bundle)
        assert len(orders) == 1 and orders[0].accession_number == "ACC9"
        assert orders[0].patient is not None and orders[0].patient.patient_id == "P9"
        assert len(patients) == 1 and patients[0].name == "Sidorov Sidr" and patients[0].sex == "M"
        assert len(priors) == 1 and priors[0].loinc == "8625-6" and priors[0].unit == "mm"

    def test_rejects_non_bundle(self):
        with pytest.raises(interop_fhir_inbound.FhirParseError):
            interop_fhir_inbound.parse_bundle({"resourceType": "Patient"})


class TestSrAndCda:
    def test_sr_tree_uses_loinc_and_ucum(self):
        tree = build_sr_tree(_report())
        assert tree.value_type == "CONTAINER"
        assert tree.concept.value == "126000"
        sections = tree.children
        assert len(sections) == 2
        measurements = sections[0]
        first = measurements.children[0]
        assert first.concept.value == "8625-6"  # LOINC for lv.lvedd
        num = first.children[0]
        assert num.value_type == "NUM"
        assert num.num is not None and num.num.unit_code == "mm"  # canonical UCUM for length
        assert num.num.value == "52"

    def test_cda_document(self):
        xml = build_cda_r2(_report())
        root = ET.fromstring(xml)
        assert root.tag == "{urn:hl7-org:v3}ClinicalDocument"
        codes = [el.get("code") for el in root.iter("{urn:hl7-org:v3}code")]
        assert "8625-6" in codes  # LOINC coded observation
        values = [el for el in root.iter("{urn:hl7-org:v3}value")]
        assert any(v.get("unit") == "mm" for v in values)
        assert "Normal study." in xml


class TestWorklistModels:
    def test_status_roundtrip(self):
        item = WorklistItem(accession_number="A1", patient_id="P1")
        clone = WorklistItem.from_dict(item.to_dict())
        assert clone.status is WorklistStatus.SCHEDULED
        assert clone.accession_number == "A1"

    def test_mpps_update(self):
        update = MppsUpdate(accession_number="A1", status=WorklistStatus.IN_PROGRESS)
        assert update.status is WorklistStatus.IN_PROGRESS
