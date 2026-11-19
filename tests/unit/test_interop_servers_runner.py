"""Behavioral tests for the Stage-4 runner/settings/autofill modules (issue 626)."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestListenerSettingsModel:
    def test_defaults_are_loopback_and_disabled(self):
        from echo_personal_tool.domain.models.listener_settings import (
            DEFAULT_HL7_PORT,
            DEFAULT_MWL_PORT,
            ListenerSettings,
        )

        settings = ListenerSettings()
        assert not settings.hl7_enabled and not settings.mwl_enabled
        assert settings.hl7_host == "127.0.0.1" and settings.mwl_host == "127.0.0.1"
        assert settings.hl7_port == DEFAULT_HL7_PORT == 6761
        assert settings.mwl_port == DEFAULT_MWL_PORT == 11113
        assert settings.allowed_hosts_list() == ()

    def test_allowed_hosts_list_parses_csv(self):
        from echo_personal_tool.domain.models.listener_settings import ListenerSettings

        settings = ListenerSettings(allowed_hosts=" 10.0.0.5, ,example.local ,")
        assert settings.allowed_hosts_list() == ("10.0.0.5", "example.local")


class _FakeStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def value(self, key: str, defaultValue=None):
        return self.values.get(key, defaultValue)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        pass


class TestListenerSettingsPersistence:
    def test_save_and_load_roundtrip(self, monkeypatch: pytest.MonkeyPatch):
        from echo_personal_tool.domain.models.listener_settings import ListenerSettings
        from echo_personal_tool.infrastructure import listener_settings as ls

        fake = _FakeStore()
        monkeypatch.setattr(ls, "_store", lambda: fake)
        settings = ListenerSettings(hl7_enabled=True, hl7_port=16761, allowed_hosts="10.0.0.5")
        ls.save_listener_settings(settings)
        loaded = ls.load_listener_settings()
        assert loaded.hl7_enabled is True
        assert loaded.hl7_port == 16761
        assert loaded.allowed_hosts == "10.0.0.5"

    def test_load_falls_back_to_defaults_on_garbage(self, monkeypatch: pytest.MonkeyPatch):
        from echo_personal_tool.infrastructure import listener_settings as ls

        fake = _FakeStore()
        fake.values["hl7/port"] = "not-a-number"
        fake.values["mwl/enabled"] = "yes"
        monkeypatch.setattr(ls, "_store", lambda: fake)
        loaded = ls.load_listener_settings()
        assert loaded.hl7_port == 6761
        assert loaded.mwl_enabled is True


class TestDicomSr:
    def test_sr_bytes_are_a_parseable_tid5200_object(self):
        pydicom = pytest.importorskip("pydicom")
        import io

        from echo_personal_tool.domain.services.interop_hl7 import (
            InteropObservation,
            InteropPatient,
            InteropReport,
        )
        from echo_personal_tool.domain.services.interop_sr import build_sr_tree
        from echo_personal_tool.infrastructure.dicom_sr import sr_bytes

        tree = build_sr_tree(
            InteropReport(
                patient=InteropPatient(patient_id="P1", name="Ivanov Ivan"),
                conclusion="Normal",
                observations=(
                    InteropObservation(
                        measurement_id="lv.lvedd", label="LVEDD", value="52", unit="mm", quantity="length"
                    ),
                ),
            )
        )
        blob = sr_bytes(tree, patient_id="P1", patient_name="Ivanov^Ivan", study_uid="1.2.3.4.5", accession="ACC1")
        parsed = pydicom.dcmread(io.BytesIO(blob))
        assert parsed.SOPClassUID == "1.2.840.10008.5.1.4.1.1.88.65"
        assert parsed.ContentSequence[0].ContentTemplateSequence[0].TemplateIdentifier == "1.2.840.10008.6.1.5200"


class TestInteropServerRunner:
    def test_disabled_settings_start_and_stop_cleanly(self, tmp_path: Path):
        from echo_personal_tool.application.interop_servers import InteropServerRunner
        from echo_personal_tool.domain.models.listener_settings import ListenerSettings

        runner = InteropServerRunner(settings=ListenerSettings(), store_path=tmp_path / "wl.db")
        runner.start()
        assert runner.running is False
        runner.stop()
        runner.close()

    def test_rejects_remote_plaintext_bind(self, tmp_path: Path):
        from echo_personal_tool.application.interop_servers import InteropServerRunner
        from echo_personal_tool.domain.models.listener_settings import ListenerSettings
        from echo_personal_tool.domain.services.listener_policy import TransportPolicyError

        settings = ListenerSettings(hl7_enabled=True, hl7_host="192.0.2.10", hl7_port=16761)
        runner = InteropServerRunner(settings=settings, store_path=tmp_path / "wl.db")
        with pytest.raises(TransportPolicyError):
            runner.start()
        runner.stop()
        runner.close()


class TestWorklistAutofill:
    def _store(self, path: Path):
        from echo_personal_tool.infrastructure.worklist_repository import WorklistRepository

        return WorklistRepository(path)

    def test_autofill_returns_none_for_unknown_study(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from echo_personal_tool.application import worklist_autofill

        monkeypatch.setattr(worklist_autofill, "worklist_db_path", lambda: tmp_path / "wl.db")
        assert worklist_autofill.autofill_patient_for_study("1.2.3.999") is None
        assert worklist_autofill.autofill_patient_for_study("") is None

    def test_autofill_maps_worklist_item_to_patient_info(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from echo_personal_tool.application import worklist_autofill
        from echo_personal_tool.application.worklist_service import WorklistService
        from echo_personal_tool.domain.models.worklist import OrderEvent, PatientDemographics

        db = tmp_path / "wl.db"
        store = self._store(db)
        service = WorklistService(store=store)
        service.apply_order(
            OrderEvent(
                message_type="ORM^O01",
                order_control="NW",
                accession_number="ACC7",
                patient=PatientDemographics(patient_id="P7", name="Petrov^Petr", birth_date="1980-01-02", sex="M"),
                scheduled_datetime="2026-11-18T13:00:00",
                study_instance_uid="1.2.3.7",
                source="hl7",
            )
        )
        store.close()
        monkeypatch.setattr(worklist_autofill, "worklist_db_path", lambda: db)
        info = worklist_autofill.autofill_patient_for_study("1.2.3.7")
        assert info is not None
        assert info.patient_id == "P7" and info.name == "Petrov^Petr" and info.sex == "M"
