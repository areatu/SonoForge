"""Published release bytes must match the matrix, manifests and records (QH-5a).

`QH-5a` slice 3 asks for evidence that the checksums, the SBOMs, the build
records and `latest.json` describe the bytes that were actually published
(A-17). The verification runs on a *downloaded release*, so these tests build a
small synthetic release directory (real digests, real record structure) and
then break it in the ways that matter: a tampered artifact, a missing asset, an
SBOM that belongs to another version, a record that forgot the smoke, a stale
download manifest.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "tools" / "release"
if str(RELEASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOLS))

import build_record  # noqa: E402,I001
import package_matrix  # noqa: E402,I001
import verify_release  # noqa: E402,I001

MATRIX_PATH = ROOT / ".github" / "package-matrix.yml"
VERSION = "0.3.3"
TAG = "v0.3.3"
REPO = "areatu/SonoForge"


def _write_sums(directory: Path, manifest: str, names: list[str]) -> None:
    lines = []
    for name in sorted(names):
        digest, _ = verify_release.file_digest_and_size(directory / name)
        lines.append(f"{digest}  {name}")
    (directory / manifest).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_release(
    tmp_path: Path,
    *,
    profiles: tuple[str, ...] = ("full",),
    version: str = VERSION,
    tag: str = TAG,
) -> Path:
    matrix = package_matrix.load(MATRIX_PATH)
    directory = tmp_path / "release"
    directory.mkdir()
    assets = package_matrix.assets_for(matrix, version, list(profiles))
    for asset in assets:
        (directory / asset["name"]).write_bytes(b"synthetic release bytes: " + asset["name"].encode())

    serial = verify_release.expected_sbom_serial(REPO, version)
    for name in package_matrix.sbom_names(matrix, version, list(profiles)):
        sbom = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "serialNumber": serial,
            "metadata": {"component": {"name": "Sonoforge", "version": version}},
            "components": [{"type": "library", "name": "numpy", "version": "1.26.4"}],
        }
        (directory / name).write_text(json.dumps(sbom), encoding="utf-8")

    smoke_evidence = tmp_path / "smoke.json"
    smoke_evidence.write_text(json.dumps({"ok": True}), encoding="utf-8")
    for profile in profiles:
        platforms = sorted({asset["platform"] for asset in assets if asset["profile"] == profile})
        for platform in platforms:
            owned = [asset for asset in assets if (asset["profile"], asset["platform"]) == (profile, platform)]
            packaged = [asset for asset in owned if asset["smoke"] != "none"]
            record = build_record.collect(
                profile=profile,
                platform=platform,
                artifacts=[directory / asset["name"] for asset in owned],
                sboms=[directory / asset["sbom"] for asset in owned if asset["sbom"]],
                # A source-only record has nothing to launch: `not-recorded` is the
                # honest status, and verification only requires `pass` for packaged
                # assets.
                smoke_evidence=smoke_evidence if packaged else None,
                tag=tag,
                version=version,
                root=ROOT,
                lock_path=ROOT / "uv.lock",
                environ={"GITHUB_SHA": "a" * 40, "GITHUB_REPOSITORY": REPO, "GITHUB_WORKFLOW": "release.yml"},
                created_at="2026-10-21T00:00:00Z",
            )
            build_record.write(record, directory / package_matrix.record_name(matrix, profile, platform, version))

    expectations = package_matrix.checksum_expectations(matrix, version, list(profiles))
    for manifest, names in expectations.items():
        _write_sums(directory, manifest, names)

    entries = []
    for name in sorted({name for names in expectations.values() for name in names}):
        digest, size = verify_release.file_digest_and_size(directory / name)
        entries.append({"name": name, "url": f"https://example.invalid/{name}", "size": size, "sha256": digest})
    (directory / "latest.json").write_text(
        json.dumps({"schema": 1, "tag": tag, "published_at": None, "assets": entries}), encoding="utf-8"
    )
    return directory


def _verify(directory: Path, profiles: tuple[str, ...] = ("full",), **overrides):
    kwargs = {
        "tag": TAG,
        "version": VERSION,
        "repo": REPO,
        "matrix_path": MATRIX_PATH,
        "profiles": list(profiles),
        "latest_json": directory / "latest.json",
        "lock_path": ROOT / "uv.lock",
    }
    kwargs.update(overrides)
    return verify_release.verify(directory, **kwargs)


def _failed(report) -> list[str]:
    return [entry["check"] for entry in report.entries if not entry["ok"]]


# ── a consistent release passes ───────────────────────────────────────


class TestConsistentRelease:
    def test_full_profile_release_passes(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        report = _verify(directory)
        assert report.ok, report.render()
        assert {entry["check"] for entry in report.entries} == set(verify_release.CHECK_ORDER) - {"attestations"}
        assert report.as_dict()["failed"] == []

    def test_presenter_profile_release_passes(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path, profiles=("presenter",))
        report = _verify(directory, profiles=("presenter",))
        assert report.ok, report.render()

    def test_combined_release_passes_for_both_profiles(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path, profiles=("full", "presenter"))
        assert _verify(directory, profiles=("full", "presenter")).ok
        assert _verify(directory, profiles=("full",)).ok

    def test_report_renders_pass_and_fail(self, tmp_path: Path) -> None:
        report = _verify(_build_release(tmp_path))
        assert "RESULT: PASS" in report.render()
        report.add("matrix", False, "nope")
        assert "RESULT: FAIL" in report.render()
        assert report.as_dict()["failed"] == ["matrix"]


# ── the checks fail when the published set lies ───────────────────────


class TestBrokenRelease:
    def test_tampered_artifact_fails_the_checksums(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        victim = directory / "sonoforge_0.3.3_amd64.deb"
        victim.write_bytes(victim.read_bytes() + b"tampered")
        report = _verify(directory)
        assert not report.ok
        assert "checksums" in _failed(report)
        assert any("digest mismatch" in entry["detail"] for entry in report.entries if entry["check"] == "checksums")

    def test_missing_asset_fails_the_matrix(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        (directory / "SonoForge-0.3.3-macos-arm64.dmg").unlink()
        report = _verify(directory)
        assert not report.ok
        assert "matrix" in _failed(report)

    def test_manifest_listing_an_unpublished_file_fails(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        sums = directory / "SHA256SUMS"
        sums.write_text(
            sums.read_text(encoding="utf-8") + f"{'0' * 64}  SonoForge-9.9.9-macos-arm64.dmg\n",
            encoding="utf-8",
        )
        report = _verify(directory)
        assert "checksums" in _failed(report)
        assert any("unexpected" in entry["detail"] for entry in report.entries if entry["check"] == "checksums")

    def test_sbom_from_another_version_fails(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        sbom_path = directory / "SonoForge-0.3.3-linux-amd64.sbom.cdx.json"
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        sbom["metadata"]["component"]["version"] = "0.3.2"
        sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
        report = _verify(directory)
        assert "sboms" in _failed(report)

    def test_sbom_serial_must_bind_to_the_tag(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        sbom_path = directory / "SonoForge-0.3.3-windows-x64.sbom.cdx.json"
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        sbom["serialNumber"] = "urn:uuid:" + str(uuid.uuid4())
        sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
        report = _verify(directory)
        assert "sboms" in _failed(report)
        assert any("serialNumber" in entry["detail"] for entry in report.entries if entry["check"] == "sboms")

    def test_sbom_component_list_must_not_be_empty(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        sbom_path = directory / "SonoForge-0.3.3-macos-arm64.sbom.cdx.json"
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        sbom["components"] = []
        sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
        assert "sboms" in _failed(_verify(directory))

    def test_missing_record_fails(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        (
            directory / package_matrix.record_name(package_matrix.load(MATRIX_PATH), "full", "macos-arm64", VERSION)
        ).unlink()
        report = _verify(directory)
        assert "records" in _failed(report)

    def test_record_smoke_status_must_be_pass(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        record_path = directory / package_matrix.record_name(
            package_matrix.load(MATRIX_PATH), "full", "linux-amd64", VERSION
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["smoke"]["status"] = "not-recorded"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        report = _verify(directory)
        assert "records" in _failed(report)
        assert any("package smoke" in entry["detail"] for entry in report.entries if entry["check"] == "records")

    def test_record_artifact_hash_must_match_the_published_bytes(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        record_path = directory / package_matrix.record_name(
            package_matrix.load(MATRIX_PATH), "full", "windows-x64", VERSION
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["artifacts"][0]["sha256"] = "b" * 64
        record_path.write_text(json.dumps(record), encoding="utf-8")
        assert "records" in _failed(_verify(directory))

    def test_record_must_come_from_the_same_lock(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        record_path = directory / package_matrix.record_name(
            package_matrix.load(MATRIX_PATH), "full", "macos-arm64", VERSION
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["lock"]["sha256"] = "c" * 64
        record_path.write_text(json.dumps(record), encoding="utf-8")
        assert "records" in _failed(_verify(directory))

    def test_invalid_record_structure_is_reported(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        record_path = directory / package_matrix.record_name(
            package_matrix.load(MATRIX_PATH), "full", "macos-arm64", VERSION
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["schema"] = 99
        record_path.write_text(json.dumps(record), encoding="utf-8")
        report = _verify(directory)
        assert "records" in _failed(report)

    def test_latest_json_missing_entry_fails(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        latest = json.loads((directory / "latest.json").read_text(encoding="utf-8"))
        latest["assets"] = [entry for entry in latest["assets"] if "macos" not in entry["name"]]
        (directory / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
        report = _verify(directory)
        assert "latest_json" in _failed(report)

    def test_latest_json_stale_hash_fails(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        latest = json.loads((directory / "latest.json").read_text(encoding="utf-8"))
        latest["assets"][0]["sha256"] = "d" * 64
        (directory / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
        assert "latest_json" in _failed(_verify(directory))

    def test_latest_json_pointing_at_an_unpublished_file_fails(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        latest = json.loads((directory / "latest.json").read_text(encoding="utf-8"))
        latest["assets"].append({"name": "ghost.bin", "url": "x", "size": 1, "sha256": "e" * 64})
        (directory / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
        assert "latest_json" in _failed(_verify(directory))

    def test_latest_json_of_another_tag_fails(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        latest = json.loads((directory / "latest.json").read_text(encoding="utf-8"))
        latest["tag"] = "v0.3.2"
        (directory / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
        assert "latest_json" in _failed(_verify(directory))

    def test_missing_latest_json_is_reported_when_requested(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        report = _verify(directory, latest_json=directory / "absent.json")
        assert "latest_json" in _failed(report)

    def test_unreadable_latest_json_is_reported(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        (directory / "latest.json").write_text("{not json", encoding="utf-8")
        assert "latest_json" in _failed(_verify(directory))


# ── attestations ──────────────────────────────────────────────────────


class TestAttestations:
    def test_checked_for_every_asset_and_every_declared_sbom(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)
        calls: list[tuple[str, str | None]] = []

        def fake(path: Path, repo: str, predicate_type: str | None):
            calls.append((Path(path).name, predicate_type))
            return True, "ok"

        report = _verify(directory, attestations=True, gh_verify=fake)
        assert report.ok, report.render()
        declared = package_matrix.assets_for(package_matrix.load(MATRIX_PATH), VERSION, ["full"])
        assert len(calls) == len(declared) + sum(1 for asset in declared if asset["sbom"])
        assert ("sonoforge_0.3.3_amd64.deb", verify_release.SBOM_PREDICATE_TYPE) in calls
        # The sdist carries provenance but no SBOM: the workflow attests the
        # tarball, not an SBOM that does not exist for it.
        assert ("sonoforge-0.3.3.tar.gz", None) in calls
        assert all(not (name == "sonoforge-0.3.3.tar.gz" and predicate) for name, predicate in calls)

    def test_a_failed_attestation_fails_the_report(self, tmp_path: Path) -> None:
        directory = _build_release(tmp_path)

        def fake(path: Path, repo: str, predicate_type: str | None):
            if predicate_type is None:
                return True, "ok"
            return False, "no matching attestations"

        report = _verify(directory, attestations=True, gh_verify=fake)
        assert not report.ok
        assert "attestations" in _failed(report)

    def test_gh_verify_reports_missing_cli(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def boom(*args, **kwargs):
            raise FileNotFoundError

        monkeypatch.setattr(verify_release.subprocess, "run", boom)
        ok, detail = verify_release._gh_verify(tmp_path / "x", REPO, None)
        assert not ok and "gh is not installed" in detail


# ── helpers ───────────────────────────────────────────────────────────


class TestHelpers:
    def test_parse_sums_accepts_the_formats_sha256sum_writes(self) -> None:
        digest = "a" * 64
        text = f"{digest}  file-one.deb\n{digest} *file-two.exe\n# comment\n\n{'b' * 64} file-three.dmg\n"
        sums = verify_release.parse_sums(text)
        assert sums["file-one.deb"] == digest
        assert sums["file-two.exe"] == digest
        assert sums["file-three.dmg"] == "b" * 64

    def test_parse_sums_ignores_malformed_lines(self) -> None:
        assert verify_release.parse_sums("not-a-digest  file\n") == {}

    def test_sbom_serial_is_a_deterministic_version_binding(self) -> None:
        first = verify_release.expected_sbom_serial(REPO, VERSION)
        second = verify_release.expected_sbom_serial(REPO, VERSION)
        assert first == second
        assert first == "urn:uuid:" + str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/{REPO}/releases/tag/v{VERSION}")
        )
        assert first != verify_release.expected_sbom_serial(REPO, "0.3.4")

    def test_cli_writes_json_evidence_and_returns_zero(self, tmp_path: Path, capsys) -> None:
        directory = _build_release(tmp_path)
        evidence = tmp_path / "verification.json"
        code = verify_release.main(
            [
                "--dir",
                str(directory),
                "--tag",
                TAG,
                "--version",
                VERSION,
                "--profile",
                "full",
                "--latest-json",
                str(directory / "latest.json"),
                "--json-out",
                str(evidence),
            ]
        )
        assert code == 0
        assert "RESULT: PASS" in capsys.readouterr().out
        assert json.loads(evidence.read_text(encoding="utf-8"))["ok"] is True

    def test_cli_returns_one_for_a_broken_release(self, tmp_path: Path, capsys) -> None:
        directory = _build_release(tmp_path)
        (directory / "SonoForge-0.3.3-macos-arm64.dmg").unlink()
        code = verify_release.main(["--dir", str(directory), "--tag", TAG, "--version", VERSION, "--profile", "full"])
        assert code == 1
        assert "RESULT: FAIL" in capsys.readouterr().out


# ── build records ─────────────────────────────────────────────────────


class TestBuildRecord:
    def _collect(self, tmp_path: Path, **overrides):
        artifact = tmp_path / "artifact.bin"
        artifact.write_bytes(b"artifact")
        smoke = tmp_path / "smoke.json"
        smoke.write_text(json.dumps({"ok": True}), encoding="utf-8")
        kwargs = {
            "profile": "full",
            "platform": "linux-amd64",
            "artifacts": [artifact],
            "smoke_evidence": smoke,
            "tag": TAG,
            "version": VERSION,
            "root": ROOT,
            "lock_path": ROOT / "uv.lock",
            "environ": {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "42"},
            "created_at": "2026-10-21T00:00:00Z",
        }
        kwargs.update(overrides)
        return build_record.collect(**kwargs)

    def test_record_describes_the_artifacts_lock_and_run(self, tmp_path: Path) -> None:
        record = self._collect(tmp_path)
        assert record["schema"] == 1 and record["kind"] == build_record.KIND
        assert record["release"] == {"tag": TAG, "version": VERSION}
        assert record["source"]["commit"] == "a" * 40
        assert record["source"]["run_id"] == "42"
        assert len(record["lock"]["sha256"]) == 64
        assert record["lock"]["packages"] > 0
        assert record["smoke"]["status"] == build_record.SMOKE_PASS
        assert record["artifacts"][0]["name"] == "artifact.bin"
        # The checkout ships the model manifest, so the record binds to its hash.
        assert record["models"]["manifest"] == "model_manifest.json"
        assert len(record["models"]["manifest_sha256"]) == 64
        assert build_record.validate_record(record) == []

    def test_record_refuses_a_tag_that_does_not_match_the_version(self, tmp_path: Path) -> None:
        with pytest.raises(build_record.BuildRecordError, match="does not match package version"):
            self._collect(tmp_path, tag="v0.3.2")

    def test_record_refuses_a_non_version_tag(self, tmp_path: Path) -> None:
        with pytest.raises(build_record.BuildRecordError, match="must look like"):
            self._collect(tmp_path, tag="main")

    def test_record_refuses_no_artifacts(self, tmp_path: Path) -> None:
        with pytest.raises(build_record.BuildRecordError, match="at least one artifact"):
            self._collect(tmp_path, artifacts=[])

    def test_record_refuses_a_missing_artifact(self, tmp_path: Path) -> None:
        with pytest.raises(build_record.BuildRecordError, match="does not exist"):
            self._collect(tmp_path, artifacts=[tmp_path / "ghost.bin"])

    def test_record_refuses_a_missing_smoke_evidence(self, tmp_path: Path) -> None:
        with pytest.raises(build_record.BuildRecordError, match="smoke evidence does not exist"):
            self._collect(tmp_path, smoke_evidence=tmp_path / "ghost.json")

    def test_failed_smoke_evidence_is_recorded_as_failed(self, tmp_path: Path) -> None:
        smoke = tmp_path / "failed-smoke.json"
        smoke.write_text(json.dumps({"ok": False}), encoding="utf-8")
        record = self._collect(tmp_path, smoke_evidence=smoke)
        assert record["smoke"]["status"] == "failed"

    def test_missing_smoke_evidence_is_recorded_honestly(self, tmp_path: Path) -> None:
        record = self._collect(tmp_path, smoke_evidence=None)
        assert record["smoke"]["status"] == build_record.SMOKE_NOT_RECORDED
        assert record["smoke"]["sha256"] is None

    def test_validate_record_reports_broken_fields(self, tmp_path: Path) -> None:
        record = self._collect(tmp_path)
        record["artifacts"][0]["sha256"] = "nope"
        record["lock"]["sha256"] = ""
        problems = build_record.validate_record(record)
        assert any("sha256" in problem for problem in problems)

    def test_package_version_is_read_from_src(self) -> None:
        assert build_record.package_version(ROOT) == "0.3.3"

    def test_cli_writes_a_valid_record(self, tmp_path: Path) -> None:
        artifact = tmp_path / "artifact.bin"
        artifact.write_bytes(b"artifact")
        output = tmp_path / "record.json"
        code = build_record.main(
            [
                "--profile",
                "presenter",
                "--platform",
                "linux-x86_64",
                "--tag",
                TAG,
                "--artifact",
                str(artifact),
                "--output",
                str(output),
            ]
        )
        assert code == 0
        record = json.loads(output.read_text(encoding="utf-8"))
        assert record["profile"] == "presenter"
        assert build_record.validate_record(record) == []
