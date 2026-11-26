"""Two-machine collection without network, real pixels or trained weights."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.ml_workbench import LocalMLWorkbench, configure_collection
from echo_personal_tool.application.training_archive import MeasurementArchiveCapture
from echo_personal_tool.application.training_archive_runtime import local_archive_capture
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.training_archive import ArchiveContext, ArchiveWriteError
from echo_personal_tool.domain.services.ml_data_readiness import combine_sources, data_readiness
from echo_personal_tool.infrastructure import ml_archive_transfer
from echo_personal_tool.infrastructure.local_ml_storage import external_path
from echo_personal_tool.infrastructure.ml_archive_transfer import verify_snapshot


def collect(bench, *, patient="patient-1", chamber="LV", offset=0, instance="sop-1"):
    capture = MeasurementArchiveCapture(bench.archive, lambda: None)
    context = ArchiveContext(patient, f"study-{patient}", "series", instance, "test")
    contour = Contour(
        "ED",
        points=[(2.0 + offset, 12.0), (7.0, 2.0), (12.0, 12.0)],
        chamber=chamber,
        mitral_annulus=((2.0, 12.0), (12.0, 12.0)),
        apex_landmark=(7.0, 2.0),
        frame_index=0,
    )
    pixels = np.arange(256, dtype=np.uint16).reshape(16, 16) + offset
    capture.observe([contour], pixels, 0, context)
    capture.confirm(instance, 0)
    assert capture.saved_count == 1
    return capture, contour, pixels, context


@pytest.fixture
def pair(tmp_path):
    windows = LocalMLWorkbench(tmp_path / "windows")
    debian = LocalMLWorkbench(tmp_path / "debian")
    key = tmp_path / "sensitive-identity.json"
    windows.export_identity(key)
    debian.import_identity(key)
    return windows, debian


def test_roundtrip_shared_identity_idempotency_and_offline_pixels(pair, tmp_path):
    windows, debian = pair
    _, _, pixels, _ = collect(windows)
    collect(debian, patient="patient-2", chamber="RV", instance="sop-2", offset=1)
    package = tmp_path / "usb" / "work-1"
    exported = windows.export_material(package)
    assert exported["privacy"] == "LOCAL_NOT_ANONYMISED"
    imported = debian.import_material(package)
    assert debian.import_material(package) == imported
    inventory = debian.inventory()
    assert len(inventory["records"]) == 2
    assert len(inventory["namespaces"]) == 1
    assert inventory["conflicts"] == []
    record = next(r for r in inventory["records"] if r["chamber"] == "LV")
    np.testing.assert_array_equal(debian.preview(record["origins"][0], record["frame_hash"]), pixels)
    assert "patient-1" not in json.dumps(inventory)
    assert "BLOCKED" in inventory["report"]["release_status"]


def test_latest_snapshot_replaces_old_source_and_carries_tombstones(pair, tmp_path):
    windows, debian = pair
    capture, contour, pixels, context = collect(windows)
    windows.export_material(tmp_path / "one")
    debian.import_material(tmp_path / "one")
    capture.observe([], pixels, 0, context)
    windows.export_material(tmp_path / "two")
    debian.import_material(tmp_path / "two")
    debian.import_material(tmp_path / "one")  # old media cannot resurrect a deleted sample
    result = debian.inventory()
    assert len(result["records"]) == 1
    assert result["records"][0]["excluded"]
    assert result["report"]["selected_records"] == 0
    assert (tmp_path / "one" / "archive.sqlite3").exists()


def test_cross_device_edits_are_conflicts_not_local_revision_wins(pair, tmp_path):
    windows, debian = pair
    collect(windows)
    collect(debian, offset=1)
    windows.export_material(tmp_path / "fork")
    debian.import_material(tmp_path / "fork")
    result = debian.inventory()
    assert len(result["conflicts"]) == 1
    assert "conflicting_cross_device_revisions" in result["report"]["preparation_blockers"]


def test_shared_patient_groups_and_exact_duplicate_dedup(pair, tmp_path):
    windows, debian = pair
    collect(windows)
    collect(debian)
    windows.export_material(tmp_path / "copy")
    debian.import_material(tmp_path / "copy")
    result = debian.inventory()
    assert len(result["records"]) == 1
    assert len(result["records"][0]["origins"]) == 2
    assert not result["conflicts"]
    assert result["report"]["patient_groups"] == 1


def test_independent_keys_block_unproven_patient_split(tmp_path):
    one, two = LocalMLWorkbench(tmp_path / "one"), LocalMLWorkbench(tmp_path / "two")
    collect(one)
    collect(two, patient="patient-2")
    one.export_material(tmp_path / "package")
    two.import_material(tmp_path / "package")
    assert "cross_namespace_patient_linkage_unverified" in two.inventory()["report"]["preparation_blockers"]


def test_cannot_change_identity_after_collection_or_export(pair, tmp_path):
    windows, debian = pair
    key = tmp_path / "key.json"
    windows.export_identity(key)
    collect(debian)
    with pytest.raises(ArchiveWriteError):
        debian.import_identity(key)
    windows.export_material(tmp_path / "empty-snapshot")
    with pytest.raises(ArchiveWriteError):
        windows.import_identity(key)


@pytest.mark.parametrize(
    "field,value",
    [("origin", "../../escape"), ("sequence", 0), ("namespace", "bad"), ("bytes", -1), ("sha256", "0" * 64)],
)
def test_manifest_tamper_is_rejected(pair, tmp_path, field, value):
    windows, debian = pair
    package = tmp_path / "package"
    windows.export_material(package)
    data = json.loads((package / "transfer.json").read_text())
    data[field] = value
    (package / "transfer.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        debian.import_material(package)
    assert not (debian.directory / "imports").exists()


def test_changed_database_and_same_sequence_fork_rejected(pair, tmp_path):
    windows, debian = pair
    collect(windows)
    package = tmp_path / "package"
    windows.export_material(package)
    debian.import_material(package)
    # A valid second snapshot altered to claim the same sequence must not replace first.
    other = tmp_path / "other"
    windows.export_material(other)
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(other / "archive.sqlite3")) as db, db:
        db.execute("UPDATE settings SET value='1' WHERE key='export_sequence'")
    data = json.loads((other / "transfer.json").read_text())
    data.update(sequence=1, sha256=ml_archive_transfer.file_digest(other / "archive.sqlite3"))
    (other / "transfer.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="origin_sequence_conflict"):
        debian.import_material(other)
    with (package / "archive.sqlite3").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError):
        verify_snapshot(package)


def test_disk_full_import_does_not_publish_partial_package(pair, tmp_path, monkeypatch):
    windows, debian = pair
    package = tmp_path / "package"
    windows.export_material(package)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(ml_archive_transfer.shutil, "disk_usage", lambda _: usage._replace(free=0))
    with pytest.raises(ValueError, match="disk"):
        debian.import_material(package)
    assert list((debian.directory / "imports").glob("*/*")) == []


def test_failed_copy_reverification_does_not_publish(pair, tmp_path, monkeypatch):
    windows, debian = pair
    package = tmp_path / "package"
    windows.export_material(package)
    original = shutil.copyfile

    def corrupt(source, destination):
        original(source, destination)
        with Path(destination).open("ab") as stream:
            stream.write(b"changed during I/O")

    monkeypatch.setattr(ml_archive_transfer.shutil, "copyfile", corrupt)
    with pytest.raises(ValueError):
        debian.import_material(package)
    assert list((debian.directory / "imports").glob("*/*")) == []


def test_current_revision_curation_invalidates_on_edit_and_does_not_change_clinical_archive(tmp_path):
    bench = LocalMLWorkbench(tmp_path / "bench")
    capture, contour, pixels, context = collect(bench)
    first = bench.inventory()["records"][0]
    bench.decide(first["fingerprint"], excluded=False, reviewed=True)
    assert bench.inventory()["report"]["reviewed_current_records"] == 1
    bench.decide(first["fingerprint"], excluded=True, reviewed=False)
    assert bench.inventory()["report"]["selected_records"] == 0
    assert len(bench.archive.records()) == 1  # curation does not delete clinical measurements
    edited = replace(contour, points=[(3.0, 12.0), (7.0, 2.0), (12.0, 12.0)])
    capture.observe([edited], pixels, 0, context)
    capture.confirm(context.instance_key, 0)
    report = bench.inventory()["report"]
    assert report["reviewed_current_records"] == 0
    assert report["selected_records"] == 1
    bench.export_report(tmp_path / "aggregate.json")
    text = (tmp_path / "aggregate.json").read_text()
    assert first["patient_key"] not in text
    assert "BLOCKED" in text


def test_quota_pause_counts_and_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.delenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE", raising=False)
    monkeypatch.delenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE_DIR", raising=False)
    assert local_archive_capture(permitted=True) is None
    configure_collection(enabled=True, directory=tmp_path / "collection", quota_bytes=16 * 1024**2)
    capture = local_archive_capture(permitted=True)
    assert capture is not None
    assert capture.archive.quota_bytes == 16 * 1024**2
    assert local_archive_capture(permitted=False) is None
    monkeypatch.setenv("SONOFORGE_LOCAL_TRAINING_ARCHIVE", "0")
    assert local_archive_capture(permitted=True) is None
    bench = LocalMLWorkbench(tmp_path / "bench")
    capture, contour, pixels, context = collect(bench)
    capture.set_paused(True)
    capture.observe([replace(contour, phase="ES")], pixels, 0, context)
    capture.confirm(context.instance_key, 0)
    assert len(bench.archive.records()) == capture.saved_count == 1
    capture.set_paused(False)
    capture.archive.quota_bytes = 1
    capture.observe([contour, replace(contour, phase="ES")], pixels, 0, context)
    capture.confirm(context.instance_key, 0)
    assert capture.skipped_count == 1
    assert len(bench.archive.records()) == 1
    with pytest.raises(ArchiveWriteError, match="quota"):
        # Pending failed sample remains available for a deliberate retry.
        capture.archive.save(next(iter(capture.pending.values())))


def test_path_guards_and_invalid_key(pair, tmp_path):
    windows, _ = pair
    with pytest.raises(ValueError):
        external_path(Path("relative"))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(ValueError):
        windows.export_material(repo / "patient-pixels")
    with pytest.raises(ValueError):
        windows.export_identity(repo / "key.json")
    bad_key = tmp_path / "bad-key.json"
    bad_key.write_text('{"format":"sonoforge-local-identity-v1","salt":"bad"}')
    with pytest.raises(ValueError):
        windows.import_identity(bad_key)


def test_inventory_unknown_patient_partial_labels_ra_and_weak_prior(tmp_path):
    bench = LocalMLWorkbench(tmp_path / "bench")
    collect(bench, patient="", chamber="RA")
    record = bench.inventory()["records"][0]
    # Eligibility reports the real unsupported adapter, without pretending RA vanished.
    source = dict(record, split="train")
    inventory = combine_sources([("namespace", "origin", [source])])
    decisions = {inventory["records"][0]["fingerprint"]: {"reviewed": True}}
    report = data_readiness(inventory, decisions)
    assert "patient_identity_unknown" in report["preparation_blockers"]
    assert report["patient_groups"] == 0
    assert report["strata"][0]["chamber"] == "RA"
    assert "BLOCKED" in report["release_status"]


def test_cli_uses_same_local_workbench_and_safe_errors(tmp_path, capsys):
    from scripts.local_ml_workbench import main

    workspace = tmp_path / "cli-workspace"
    base = ["--workspace", str(workspace), "--acknowledge-local-phi"]
    assert main([*base, "status"]) == 0
    assert "BLOCKED" in capsys.readouterr().out
    assert main([*base, "export-key", str(tmp_path / "identity.json")]) == 0
    assert main([*base, "export", str(tmp_path / "cli.sfarchive")]) == 0
    assert verify_snapshot(tmp_path / "cli.sfarchive")["sequence"] == 1
    assert main([*base, "import", str(tmp_path / "secret-patient-path")]) == 2
    assert "secret-patient-path" not in capsys.readouterr().err


def test_frame_payload_corruption_rejected_even_with_new_outer_hash(pair, tmp_path):
    import sqlite3
    from contextlib import closing

    windows, debian = pair
    collect(windows)
    package = tmp_path / "bad-frame.sfarchive"
    windows.export_material(package)
    database = package / "archive.sqlite3"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE frames SET pixels=?", (b"not a valid NPY",))
    manifest = json.loads((package / "transfer.json").read_text())
    manifest["sha256"] = ml_archive_transfer.file_digest(database)
    manifest["bytes"] = database.stat().st_size
    (package / "transfer.json").write_text(json.dumps(manifest))
    with pytest.raises((ValueError, ArchiveWriteError)):
        debian.import_material(package)


def test_symlink_import_root_cannot_escape_workspace(pair, tmp_path):
    windows, debian = pair
    if not hasattr(Path, "symlink_to"):
        pytest.skip("symlinks unavailable")
    target = tmp_path / "elsewhere"
    target.mkdir()
    debian.directory.mkdir(exist_ok=True)
    try:
        (debian.directory / "imports").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform")
    windows.export_material(tmp_path / "package")
    with pytest.raises(ValueError):
        debian.import_material(tmp_path / "package")
    assert list(target.iterdir()) == []
