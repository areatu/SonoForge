"""The packaged-artifact smoke scenario: save -> restart -> export (QH-5a).

`QH-5a` slice 2 (spec §9.1, A-16) is the reason this file exists: a release is
confirmed by the packaged artifact doing the real work — first launch, a
synthetic cine, a measurement saved through the persistence layer, a **second
process** restoring it from disk, text and PDF export, and the storage
boundaries of the portable profile.

The scenario itself has to keep working, so it is tested here on the checkout
(cheap, deterministic) while the packaging workflows run the very same module
against the shipped executables. What is asserted below is that the scenario
fails when any of those promises is broken — a smoke that cannot fail is not
evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from echo_personal_tool.application import package_smoke

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "tools" / "release"
if str(RELEASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOLS))

import run_package_smoke  # noqa: E402,I001


@pytest.fixture()
def portable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Portable storage root — the smoke refuses to run outside it."""
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setenv("SONOFORGE_PORTABLE", "1")
    monkeypatch.setenv("SONOFORGE_PORTABLE_DIR", str(root / "portable"))
    monkeypatch.delenv("SONOFORGE_PROFILE", raising=False)
    return root


def _checks(manifest: dict) -> dict[str, bool]:
    return {check["name"]: check["ok"] for check in manifest["checks"]}


class TestSaveStage:
    def test_save_writes_the_record_cine_and_both_exports(self, portable: Path) -> None:
        manifest = package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="full")
        assert manifest["ok"], [check for check in manifest["checks"] if not check["ok"]]
        assert manifest["schema"] == package_smoke.SCHEMA
        assert manifest["kind"] == package_smoke.KIND
        assert manifest["stage"] == package_smoke.STAGE_SAVE
        assert manifest["expected_profile"] == "full"
        assert manifest["record"]["revision"] == 1
        assert [item["label"] for item in manifest["record"]["measurements"]] == ["LVEDD", "LVESD"]
        assert manifest["record"]["manual_bsa_m2"] == package_smoke.MANUAL_BSA_M2
        assert (portable / "input" / "synthetic-cine.dcm").is_file()
        assert (portable / "export" / "report.txt").is_file()
        pdf = (portable / "export" / "report.pdf").read_bytes()
        assert pdf.startswith(b"%PDF-") and len(pdf) > 1000
        assert (portable / "portable" / "measurements").is_dir()

    def test_every_promised_check_is_present_and_passes(self, portable: Path) -> None:
        checks = _checks(package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="full"))
        for name in (
            "profile",
            "capability:onnxruntime",
            "reference_ui",
            "synthetic_cine",
            "measurements_round_trip",
            "text_export",
            "pdf_export",
            "portable_storage",
            "no_temporary_leftovers",
            "storage_allowlist",
            "export_has_no_paths",
        ):
            assert checks.get(name) is True, name

    def test_manifest_carries_no_absolute_paths(self, portable: Path) -> None:
        manifest = package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="full")
        text = json.dumps(manifest)
        assert str(portable) not in text
        assert manifest["data_dir"] == "portable"
        assert manifest["executable_name"] == Path(sys.executable).name

    def test_a_wrong_expected_profile_fails_the_smoke(self, portable: Path) -> None:
        """`--expect-profile` is the A-11 claim: full and Presenter are not the same product."""
        manifest = package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="presenter")
        assert manifest["ok"] is False
        assert _checks(manifest)["profile"] is False
        assert _checks(manifest)["capability:onnxruntime"] is False

    def test_storage_outside_the_portable_root_fails(self, portable: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SONOFORGE_PORTABLE_DIR", str(portable / "elsewhere"))
        manifest = package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="full")
        assert _checks(manifest)["portable_storage"] is False

    def test_unknown_stage_is_rejected(self, portable: Path) -> None:
        with pytest.raises(package_smoke.SmokeFailure, match="unknown stage"):
            package_smoke.run("launch", portable, expect_profile="full")


class TestRestartStage:
    def test_restart_restores_the_saved_record_and_reexports(self, portable: Path) -> None:
        saved = package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="full")
        save_manifest = portable / "stage-save.json"
        save_manifest.write_text(json.dumps(saved), encoding="utf-8")

        restarted = package_smoke.run(
            package_smoke.STAGE_RESTART,
            portable,
            expect_profile="full",
            expect_manifest=save_manifest,
        )
        assert restarted["ok"], [check for check in restarted["checks"] if not check["ok"]]
        assert restarted["record"] == saved["record"]
        assert restarted["export"]["text"]["sha256"] == saved["export"]["text"]["sha256"]
        checks = _checks(restarted)
        assert checks["restart_kept_revision"] is True
        assert checks["restored_text_identical"] is True
        assert checks["restart_same_build"] is True

    def test_restart_without_a_saved_record_fails(self, portable: Path) -> None:
        package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="full")
        for record in (portable / "portable" / "measurements").glob("*.json"):
            record.unlink()
        with pytest.raises(package_smoke.SmokeFailure, match="did not find the saved record"):
            package_smoke.run(package_smoke.STAGE_RESTART, portable, expect_profile="full")

    def test_restart_without_the_cine_fails_clearly(self, portable: Path) -> None:
        with pytest.raises(package_smoke.SmokeFailure, match="synthetic cine"):
            package_smoke.run(package_smoke.STAGE_RESTART, portable, expect_profile="full")

    def test_restart_detects_a_different_export(self, portable: Path) -> None:
        saved = package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="full")
        saved["export"]["text"]["sha256"] = "0" * 64
        save_manifest = portable / "stage-save.json"
        save_manifest.write_text(json.dumps(saved), encoding="utf-8")
        restarted = package_smoke.run(
            package_smoke.STAGE_RESTART,
            portable,
            expect_profile="full",
            expect_manifest=save_manifest,
        )
        assert restarted["ok"] is False
        assert _checks(restarted)["restored_text_identical"] is False


class TestComparison:
    def _manifests(self, portable: Path) -> tuple[dict, dict]:
        saved = package_smoke.run(package_smoke.STAGE_SAVE, portable, expect_profile="full")
        save_manifest = portable / "stage-save.json"
        save_manifest.write_text(json.dumps(saved), encoding="utf-8")
        restarted = package_smoke.run(
            package_smoke.STAGE_RESTART,
            portable,
            expect_profile="full",
            expect_manifest=save_manifest,
        )
        return saved, restarted

    def test_matching_stages_pass(self, portable: Path) -> None:
        saved, restarted = self._manifests(portable)
        checks = {check["name"]: check["ok"] for check in package_smoke.compare(saved, restarted)}
        assert all(checks.values()), checks

    def test_a_failed_stage_fails_the_comparison(self, portable: Path) -> None:
        saved, restarted = self._manifests(portable)
        restarted["ok"] = False
        checks = {check["name"]: check["ok"] for check in package_smoke.compare(saved, restarted)}
        assert checks["restart_ok"] is False

    def test_a_relabelled_manifest_fails(self, portable: Path) -> None:
        saved, restarted = self._manifests(portable)
        saved["stage"] = "restart"
        checks = {check["name"]: check["ok"] for check in package_smoke.compare(saved, restarted)}
        assert checks["save_stage"] is False

    def test_a_different_build_fails(self, portable: Path) -> None:
        saved, restarted = self._manifests(portable)
        restarted["version"] = "0.0.0"
        checks = {check["name"]: check["ok"] for check in package_smoke.compare(saved, restarted)}
        assert checks["same_build"] is False

    def test_a_different_record_fails(self, portable: Path) -> None:
        saved, restarted = self._manifests(portable)
        restarted["record"]["revision"] = 2
        checks = {check["name"]: check["ok"] for check in package_smoke.compare(saved, restarted)}
        assert checks["record_identity"] is False

    def test_the_comparison_does_not_claim_a_restart_by_itself(self, portable: Path) -> None:
        """Only the runner knows the two stages were two processes — it checks the pids."""
        saved, restarted = self._manifests(portable)
        assert "different_process" not in {check["name"] for check in package_smoke.compare(saved, restarted)}
        assert saved["process"]["pid"] == restarted["process"]["pid"]  # same pytest process


class TestCli:
    def test_save_and_compare_through_the_cli(self, portable: Path, capsys) -> None:
        save_json = portable / "save.json"
        restart_json = portable / "restart.json"
        comparison = portable / "comparison.json"
        assert package_smoke.main(["save", "--workdir", str(portable), "--json", str(save_json)]) == 0
        assert (
            package_smoke.main(
                [
                    "restart",
                    "--workdir",
                    str(portable),
                    "--expect",
                    str(save_json),
                    "--json",
                    str(restart_json),
                ]
            )
            == 0
        )
        assert package_smoke.main(["compare", str(save_json), str(restart_json), "--json", str(comparison)]) == 0
        payload = json.loads(comparison.read_text(encoding="utf-8"))
        assert payload["ok"] is True
        assert "RESULT: PASS" in capsys.readouterr().out

    def test_compare_of_broken_manifests_returns_one(self, portable: Path, capsys) -> None:
        broken = portable / "broken.json"
        broken.write_text(json.dumps({"stage": "save", "ok": False}), encoding="utf-8")
        assert package_smoke.main(["compare", str(broken), str(broken)]) == 1
        assert "RESULT: FAIL" in capsys.readouterr().out


class TestRunner:
    """The workflows call this runner; it must fail closed and keep the evidence."""

    def test_module_runner_produces_passing_evidence(self, portable: Path, tmp_path: Path) -> None:
        evidence = tmp_path / "evidence.json"
        payload = run_package_smoke.run(
            runner="module",
            profile="full",
            workdir=portable,
            interpreter=sys.executable,
            timeout=180,
            evidence=evidence,
        )
        assert payload["ok"] is True
        assert payload["runner"] == "module"
        assert payload["artifact"] is None
        assert payload["comparison"]["ok"] is True
        assert payload["stages"]["save"]["stage"] == "save"
        assert payload["stages"]["restart"]["stage"] == "restart"
        assert payload["runner_checks"][0]["name"] == "different_process"
        assert payload["runner_checks"][0]["ok"] is True
        written = json.loads(evidence.read_text(encoding="utf-8"))
        assert written["kind"] == run_package_smoke.KIND
        assert written["ok"] is True

    def test_artifact_runner_requires_an_existing_artifact(self, portable: Path) -> None:
        with pytest.raises(SystemExit, match="--artifact is required"):
            run_package_smoke.run(
                runner="artifact",
                profile="full",
                workdir=portable,
                artifact=portable / "ghost.exe",
            )

    def test_payload_runner_requires_a_payload_root(self, portable: Path) -> None:
        with pytest.raises(SystemExit, match="--payload-root is required"):
            run_package_smoke.run(
                runner="payload",
                profile="full",
                workdir=portable,
                payload_root=portable / "ghost-payload",
            )

    def test_a_failing_artifact_fails_the_runner(self, portable: Path, tmp_path: Path) -> None:
        fake = tmp_path / "fake-artifact"
        fake.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        fake.chmod(0o755)
        with pytest.raises(SystemExit, match="package smoke save failed"):
            run_package_smoke.run(
                runner="artifact",
                profile="full",
                workdir=portable,
                artifact=fake,
                timeout=60,
            )
