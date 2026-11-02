"""Saved-record listing: one honest projection for the start page and the manager.

QH-1a (spec 2026-10-13-quality-safety-hardening): the window used to read saved
records through the RAM session store (`store.entries()`), which does not exist —
the whole block silently became «нет сохранённых исследований» even with healthy
files on disk. These tests pin the replacement contract:

* a record written by the real repository is listed through the persistence API;
* one unreadable file never hides its readable neighbours (S-06/S-07);
* a failed listing is distinguishable from an empty store (S-07);
* rows carry an opaque key and allowlisted codes only (S-09).
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
from echo_personal_tool.application.saved_records import (
    STATUS_CORRUPT,
    STATUS_READABLE,
    STATUS_UNAVAILABLE,
    STATUS_UNSUPPORTED,
    read_saved_records,
    summarize_record,
)
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, StudyMeasurementSessionStore
from echo_personal_tool.domain.models import LinearMeasurement
from echo_personal_tool.infrastructure.measurement_codec import VERSION, study_key
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

UID = "1.2.3"
OTHER_UID = "1.2.9"
SOP = "1.2.3.4"
SOURCES = {SOP: {"fingerprint": "a" * 64, "frames": 4, "spacing": [0.5, 0.5]}}
KEY = study_key(UID)
pytestmark = pytest.mark.gui


def _data():
    return replace(
        StudyMeasurementData(),
        height_cm=175.0,
        height_source="manual",
        weight_kg=72.0,
        weight_source="manual",
        linear_measurements=(LinearMeasurement("LVEDD", 20, 10, 0, sop_instance_uid=SOP),),
    )


def _write_record(root, uid=UID):
    repository = MeasurementRepository(root)
    return repository.save(uid, _data(), SOURCES, 0)


def _entry(root, uid):
    return root / (study_key(uid) + ".json")


# ─────────────────────────────────────────────────────────────────────────────
#  Pure projection
# ─────────────────────────────────────────────────────────────────────────────


def test_reader_lists_a_real_record_with_counts_and_an_opaque_key(tmp_path):
    _write_record(tmp_path)
    listing = read_saved_records(MeasurementRepository(tmp_path))
    assert not listing.failed
    assert listing.unreadable == 0
    (record,) = listing.records
    assert record.status == STATUS_READABLE
    assert record.key == KEY
    # Only counts and allowlisted codes cross this boundary: no study UID, no path.
    assert UID not in repr(record)
    assert str(tmp_path) not in repr(record)
    assert record.source_count == 1
    assert record.measurement_count == 1
    assert record.kinds == ("linear", "metrics")
    assert record.has_metrics is True
    assert record.revision == 1
    assert record.saved_at
    assert record.size_bytes > 0


def test_newest_record_is_first_and_limit_keeps_the_newest(tmp_path):
    repository = MeasurementRepository(tmp_path)
    repository.save(UID, _data(), SOURCES, 0)
    repository.save(OTHER_UID, _data(), SOURCES, 0)
    listed = read_saved_records(MeasurementRepository(tmp_path))
    assert {record.key for record in listed.records} == {study_key(UID), study_key(OTHER_UID)}
    (newest,) = read_saved_records(MeasurementRepository(tmp_path), limit=1).records
    assert newest.key == listed.records[0].key


def test_corrupt_neighbour_does_not_hide_a_readable_record(tmp_path):
    _write_record(tmp_path)
    _entry(tmp_path, OTHER_UID).write_bytes(b'{"format": "sonoforge.study-measurements", "nope": 1}')
    future = json.loads(_entry(tmp_path, UID).read_bytes())
    future["schema_version"] = VERSION + 1
    (tmp_path / (study_key("1.2.10") + ".json")).write_text(json.dumps(future), encoding="utf-8")

    listing = read_saved_records(MeasurementRepository(tmp_path))
    assert not listing.failed
    by_status = {record.status for record in listing.records}
    assert by_status == {STATUS_READABLE, STATUS_CORRUPT, STATUS_UNSUPPORTED}
    assert listing.unreadable == 2
    readable = [record for record in listing.records if record.readable]
    assert [record.key for record in readable] == [KEY]
    assert readable[0].measurement_count == 1
    # The unreadable rows never claim contents they could not parse.
    for record in listing.records:
        if not record.readable:
            assert record.measurement_count == 0
            assert record.error in {"invalid", "version"}


#: os.geteuid() does not exist on Windows; the permission case is POSIX-only.
_POSIX_PERMISSIONS = os.name != "nt"
_IS_ROOT = getattr(os, "geteuid", lambda: 1)() == 0


@pytest.mark.skipif(
    not _POSIX_PERMISSIONS or _IS_ROOT,
    reason="needs POSIX file permissions and a non-root user",
)
def test_unreadable_file_is_its_own_row(tmp_path):
    _write_record(tmp_path)
    blocked = _entry(tmp_path, OTHER_UID)
    blocked.write_bytes(b"{}")
    blocked.chmod(0)
    try:
        listing = read_saved_records(MeasurementRepository(tmp_path))
    finally:
        blocked.chmod(0o600)
    statuses = [record.status for record in listing.records]
    assert STATUS_READABLE in statuses
    assert STATUS_UNAVAILABLE in statuses
    assert listing.unreadable == 1


def test_listing_failure_is_not_an_empty_store(tmp_path, monkeypatch):
    repository = MeasurementRepository(tmp_path)
    monkeypatch.setattr(repository, "entries", lambda: (_ for _ in ()).throw(OSError(13, "denied")))
    failed = read_saved_records(repository)
    assert failed.failed is True
    assert failed.error == "scan"
    assert failed.records == ()

    empty = read_saved_records(MeasurementRepository(tmp_path))
    assert empty.failed is False
    assert empty.records == ()


def test_summarize_record_never_raises_and_keeps_codes_allowlisted():
    assert summarize_record("k", b"not json at all").status == STATUS_CORRUPT
    assert summarize_record("k", b"not json at all").error == "invalid"
    assert summarize_record("k", b"x" * (32 * 1024 * 1024 + 1)).status == STATUS_CORRUPT


# ─────────────────────────────────────────────────────────────────────────────
#  Application API on the persistence worker
# ─────────────────────────────────────────────────────────────────────────────


def _enable(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr("echo_personal_tool.application.measurement_persistence.describe_study", lambda _: SOURCES)
    store = StudyMeasurementSessionStore()
    persistence = MeasurementPersistence(tmp_path, store, enabled=True)
    done = []
    persistence.load([SimpleNamespace(study_uid=UID)], lambda: done.append(True))
    assert persistence.flush()
    assert done == [True]
    return persistence


def test_persistence_api_lists_a_saved_record(tmp_path, monkeypatch, qapp, qtbot):
    persistence = _enable(tmp_path, monkeypatch, qapp)
    persistence.store.set_patient_metrics(UID, 175.0, 72.0)
    persistence.store.set_linear_measurements_for_instance(
        UID, SOP, (LinearMeasurement("LVEDD", 20, 10, 0, sop_instance_uid=SOP),)
    )
    assert persistence.flush()

    results = []
    persistence.list_saved_records(results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    listing = results[0]
    assert not listing.failed
    (record,) = listing.records
    assert record.key == KEY
    assert record.status == STATUS_READABLE
    assert record.measurement_count == 1
    assert record.has_metrics is True
    assert persistence.close()


def test_persistence_api_reports_a_failed_listing_instead_of_an_empty_one(tmp_path, monkeypatch, qapp, qtbot):
    persistence = _enable(tmp_path, monkeypatch, qapp)
    monkeypatch.setattr(persistence.repository, "entries", lambda: (_ for _ in ()).throw(PermissionError(13, "denied")))
    results = []
    persistence.list_saved_records(results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results[0].failed is True
    assert results[0].records == ()
    assert persistence.close()


def test_persistence_api_is_safe_after_close(tmp_path, monkeypatch, qapp):
    persistence = _enable(tmp_path, monkeypatch, qapp)
    assert persistence.close()
    results = []
    persistence.list_saved_records(results.append)
    assert results and results[0].failed is True
