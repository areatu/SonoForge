"""v0.4.0 recovery preserves and validates the original build evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release"))
import build_record  # noqa: E402
import package_matrix  # noqa: E402
import recover_040  # noqa: E402

from tests.unit.test_release_evidence import _build_release  # noqa: E402


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    original = _build_release(tmp_path, profiles=("full", "presenter"), version="0.4.0", tag="v0.4.0")
    shutil.copyfile(tmp_path / "smoke.json", original / "smoke.json")
    (original / "release-verification.json").write_text(
        json.dumps({"kind": "sonoforge.release-verification", "failed": ["sboms", "records"]})
    )
    lock = (ROOT / "uv.lock").read_bytes()
    crlf = hashlib.sha256(lock.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")).hexdigest()
    for path in original.glob("*.sbom.cdx.json"):
        data = json.loads(path.read_text())
        data["metadata"]["component"].pop("version")
        path.write_text(json.dumps(data))
    for path in original.glob("build-record-*.json"):
        record = json.loads(path.read_text())
        record["source"].update(
            {
                "commit": recover_040.COMMIT,
                "ref": "refs/tags/v0.4.0",
                "run_id": recover_040.RUNS[record["profile"]],
                "run_attempt": "1",
                "workflow": "Release" if record["profile"] == "full" else "Presenter (lite portable build)",
            }
        )
        if record["platform"] == "windows-x64":
            record["source"]["runner_os"] = "Windows"
            record["lock"]["sha256"] = crlf
        record["sboms"] = list({entry["name"]: entry for entry in record["sboms"]}.values())
        for entry in record["sboms"]:
            sbom = original / entry["name"]
            entry["sha256"] = build_record.sha256_of(sbom)
            entry["size"] = sbom.stat().st_size
        build_record.write(record, path)
    published = tmp_path / "published"
    shutil.copytree(original, published)
    return original, published


def _prepare(tmp_path: Path, original: Path, published: Path) -> Path:
    out = tmp_path / "out"
    recover_040.prepare(original, published, out, ROOT / "uv.lock", ROOT / ".github/package-matrix.yml")
    return out


def test_recovery_keeps_binaries_and_links_original_record(tmp_path: Path) -> None:
    original, published = _fixture(tmp_path)
    out = _prepare(tmp_path, original, published)
    matrix = package_matrix.load(ROOT / ".github/package-matrix.yml")
    for asset in package_matrix.assets_for(matrix, "0.4.0"):
        assert (out / asset["name"]).read_bytes() == (original / asset["name"]).read_bytes()
    old = original / "build-record-full-windows-x64-0.4.0.json"
    new = json.loads((out / old.name).read_text())
    assert new["lock"] == json.loads(old.read_text())["lock"]
    assert new["evidence_amendment"]["original_record_sha256"] == build_record.sha256_of(old)
    with zipfile.ZipFile(out / recover_040.BACKUP) as archive:
        assert archive.read(old.name) == old.read_bytes()
        assert archive.read("uv.lock") == (ROOT / "uv.lock").read_bytes()
        assert archive.read("smoke.json") == (original / "smoke.json").read_bytes()
        sbom_name = "SonoForge-0.4.0-windows-x64.sbom.cdx.json"
        assert archive.read(sbom_name) == (original / sbom_name).read_bytes()
    assert new["sboms"][0]["sha256"] == build_record.sha256_of(out / sbom_name)
    assert json.loads((out / sbom_name).read_text())["metadata"]["component"]["version"] == "0.4.0"


@pytest.mark.parametrize("failure", ["binary", "sbom", "smoke", "source", "lock", "published"])
def test_recovery_rejects_altered_evidence(tmp_path: Path, failure: str) -> None:
    original, published = _fixture(tmp_path)
    if failure == "binary":
        (original / "SonoForge-0.4.0-portable.exe").write_bytes(b"tampered")
    elif failure == "sbom":
        (original / "SonoForge-0.4.0-linux-amd64.sbom.cdx.json").write_bytes(b"tampered")
    elif failure == "smoke":
        (original / "smoke.json").write_text('{"ok": false}')
    elif failure in ("source", "lock"):
        path = original / "build-record-full-windows-x64-0.4.0.json"
        data = json.loads(path.read_text())
        if failure == "source":
            data["source"]["commit"] = "0" * 40
        else:
            data["lock"]["sha256"] = "0" * 64
        build_record.write(data, path)
    else:
        (published / "SonoForge-0.4.0-portable.exe").write_bytes(b"tampered")
    with pytest.raises((ValueError, KeyError)):
        _prepare(tmp_path, original, published)


def test_recovery_can_be_repeated_after_partial_publication(tmp_path: Path) -> None:
    original, published = _fixture(tmp_path)
    first = _prepare(tmp_path, original, published)
    for path in first.iterdir():
        if path.name.endswith(".json") or path.name.endswith(".zip") or path.name == "SHA256SUMS-presenter.txt":
            shutil.copyfile(path, published / path.name)
    second = tmp_path / "second"
    recover_040.prepare(original, published, second, ROOT / "uv.lock", ROOT / ".github/package-matrix.yml")
    assert (first / recover_040.BACKUP).read_bytes() == (second / recover_040.BACKUP).read_bytes()
    assert (first / "build-record-full-windows-x64-0.4.0.json").read_bytes() == (
        second / "build-record-full-windows-x64-0.4.0.json"
    ).read_bytes()


def test_windows_crlf_exception_is_scoped_to_the_original_tag_and_commit(tmp_path: Path) -> None:
    import verify_release

    original, published = _fixture(tmp_path)
    out = _prepare(tmp_path, original, published)
    record = out / "build-record-full-windows-x64-0.4.0.json"
    data = json.loads(record.read_text())
    data["source"]["commit"] = "0" * 40
    build_record.write(data, record)
    report = verify_release.verify(out, tag="v0.4.0", version="0.4.0", profiles=["full"], lock_path=ROOT / "uv.lock")
    assert not report.ok
    assert any("uv.lock hash differs" in item["detail"] for item in report.entries if item["check"] == "records")


def test_recovery_workflow_defaults_to_no_publication() -> None:
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/recover-0.4.0.yml").read_text())
    assert workflow[True]["workflow_dispatch"]["inputs"]["publish"]["default"] is False
    steps = workflow["jobs"]["recover"]["steps"]
    prepare = next(
        i for i, step in enumerate(steps) if step.get("name") == "Prepare recovery without changing the release"
    )
    upload = next(
        i for i, step in enumerate(steps) if step.get("name") == "Publish recovered evidence and Presenter assets"
    )
    assert prepare < upload
    assert steps[upload]["if"] == "${{ inputs.publish }}"
    assert "original-release-evidence.zip" in steps[upload]["run"]
    assert "staged/SonoForge-0.4.0-portable.exe" not in steps[upload]["run"]
