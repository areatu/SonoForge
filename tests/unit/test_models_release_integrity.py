"""Integrity of the published model release (audit P1-5, §12).

Two holes were open: the downloaded ``models-v1.tar.gz`` went straight into
``tarfile.open`` with no digest check (only tar-slip was guarded), and manifest
entries carrying ``"sha256": null`` silently disabled the per-model check in
``onnx_engine._verify_model_integrity`` because it returns early on a missing
value.

The archive digest is pinned once in ``runtime_setup``; both launchers read it
from there instead of repeating the literal.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure import runtime_setup as rs_mod

ROOT = Path(__file__).resolve().parents[2]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class TestPinnedDigest:
    def test_is_full_sha256(self) -> None:
        assert HEX64.match(rs_mod.MODELS_RELEASE_SHA256), "pinned digest is not 64 lowercase hex chars"

    def test_matches_pinned_value(self) -> None:
        # The literal lives in the module; if the release asset is re-uploaded,
        # this constant must be updated deliberately.
        assert rs_mod.MODELS_RELEASE_SHA256 == "cebaf1f2c80a1853a5e355246eefa50ffbb0b6bd1ff35b2964533703ed50825d"

    def test_launcher_cli_prints_the_pinned_value(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "echo_personal_tool.infrastructure.runtime_setup", "--print-models-sha256"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == rs_mod.MODELS_RELEASE_SHA256

    def test_launchers_do_not_repeat_the_literal(self) -> None:
        """Both launchers must ask the package for the digest, not restate it."""
        for relative in ("build/linux/sonoforge-launcher", "launcher.py"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            assert not HEX64.search(text), f"{relative} hardcodes a release digest"
        bash_launcher = (ROOT / "build" / "linux" / "sonoforge-launcher").read_text(encoding="utf-8")
        assert "--print-models-sha256" in bash_launcher
        assert "sha256sum" in bash_launcher
        root_launcher = (ROOT / "launcher.py").read_text(encoding="utf-8")
        assert "verify_models_archive" in root_launcher


class TestVerifyModelsArchive:
    def test_accepts_matching_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import hashlib

        archive = tmp_path / "models.tar.gz"
        payload = b"release asset bytes"
        archive.write_bytes(payload)
        monkeypatch.setattr(rs_mod, "MODELS_RELEASE_SHA256", hashlib.sha256(payload).hexdigest())
        assert rs_mod.verify_models_archive(archive) is True

    def test_rejects_substituted_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import hashlib

        archive = tmp_path / "models.tar.gz"
        archive.write_bytes(b"tampered payload")
        monkeypatch.setattr(rs_mod, "MODELS_RELEASE_SHA256", hashlib.sha256(b"release asset bytes").hexdigest())
        assert rs_mod.verify_models_archive(archive) is False

    def test_rejects_truncated_download(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import hashlib

        whole = b"z" * (3 * 1024 * 1024 + 17)  # > one read chunk, so chunking is exercised
        archive = tmp_path / "models.tar.gz"
        archive.write_bytes(whole)
        monkeypatch.setattr(rs_mod, "MODELS_RELEASE_SHA256", hashlib.sha256(whole).hexdigest())
        assert rs_mod.verify_models_archive(archive) is True

        archive.write_bytes(whole[:-1])
        assert rs_mod.verify_models_archive(archive) is False


def _make_release_tarball(dest: Path, data_dir_name: str = "models") -> bytes:
    """Build a small archive whose layout matches the real release."""
    inner = b'{"schema_version": "1.0"}'
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=f"{data_dir_name}/model_manifest.json")
        info.size = len(inner)
        tar.addfile(info, io.BytesIO(inner))
    payload = buffer.getvalue()
    dest.write_bytes(payload)
    return payload


class TestDownloadModelsChecksBeforeExtract:
    def test_bad_digest_never_reaches_extraction(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import hashlib

        models_dir = tmp_path / "models"
        monkeypatch.setattr(rs_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(rs_mod, "_MODELS_DIR", models_dir)
        monkeypatch.setattr(
            rs_mod,
            "MODELS_RELEASE_SHA256",
            hashlib.sha256(b"the real release asset").hexdigest(),
        )

        def fake_download(url: str, dest: Path, progress_callback=None) -> None:
            Path(dest).write_bytes(b"a different archive entirely")

        extracted = {"called": False}

        def fake_tar_open(*args, **kwargs):  # noqa: ANN002, ANN003
            extracted["called"] = True
            raise AssertionError("extraction must not start before the digest matches")

        monkeypatch.setattr(rs_mod, "_download_file", fake_download)
        monkeypatch.setattr(rs_mod.tarfile, "open", fake_tar_open)

        with caplog.at_level("ERROR", logger=rs_mod.logger.name):
            assert rs_mod.download_models() is False

        assert extracted["called"] is False, "archive was opened despite a digest mismatch"
        assert "SHA256 check" in caplog.text
        assert not (models_dir / "model_manifest.json").exists()

    def test_matching_digest_is_extracted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import hashlib

        models_dir = tmp_path / "models"
        monkeypatch.setattr(rs_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(rs_mod, "_MODELS_DIR", models_dir)

        def fake_download(url: str, dest: Path, progress_callback=None) -> None:
            payload = _make_release_tarball(Path(dest))
            monkeypatch.setattr(rs_mod, "MODELS_RELEASE_SHA256", hashlib.sha256(payload).hexdigest())

        monkeypatch.setattr(rs_mod, "_download_file", fake_download)

        assert rs_mod.download_models() is True
        assert (models_dir / "model_manifest.json").is_file()


class TestManifestNeverShipsUncheckedModels:
    """`sha256: null` must not reach a model that is actually loaded.

    ``onnx_engine._verify_model_integrity`` returns early when the manifest has
    no digest, so a shipped model without one would never be checked.
    """

    @pytest.fixture(scope="class")
    def manifest(self) -> dict:
        return json.loads((ROOT / "models" / "model_manifest.json").read_text(encoding="utf-8"))

    def test_manifest_is_valid_json(self, manifest: dict) -> None:
        assert manifest.get("schema_version")
        assert manifest.get("models")

    def test_exported_models_have_a_digest(self, manifest: dict) -> None:
        for model_id, entry in manifest["models"].items():
            if entry.get("status") != "exported":
                continue
            digest = entry.get("sha256")
            assert digest, f"exported model {model_id} ships without sha256"
            assert HEX64.match(digest), f"exported model {model_id} has a malformed sha256"

    def test_int8_variant_has_a_digest(self, manifest: dict) -> None:
        for model_id, entry in manifest["models"].items():
            if not entry.get("filename_int8"):
                continue
            digest = entry.get("sha256_int8")
            assert digest, f"{model_id} ships filename_int8 without sha256_int8"
            assert HEX64.match(digest)

    def test_not_exported_models_are_the_only_null_digests(self, manifest: dict) -> None:
        nulls = [model_id for model_id, entry in manifest["models"].items() if not entry.get("sha256")]
        unexported = [model_id for model_id, entry in manifest["models"].items() if entry.get("status") != "exported"]
        assert sorted(nulls) == sorted(unexported), (
            f"models with sha256={nulls} are not exactly the unexported ones {unexported}; "
            "a shipped model would load without any integrity check"
        )

    def test_every_exported_file_exists_on_disk(self, manifest: dict) -> None:
        """Catch manifest/model drift on a checkout that actually has models.

        ``*.onnx`` is gitignored (models/.gitignore), so a plain checkout — and
        therefore CI — has no binaries. The check still runs locally after a
        download, where a stale manifest entry is a real failure.
        """
        models_dir = ROOT / "models"
        exported = {
            model_id: entry
            for model_id, entry in manifest["models"].items()
            if entry.get("status") == "exported"
        }
        if not any((models_dir / entry["filename"]).exists() for entry in exported.values()):
            pytest.skip("model binaries are gitignored (*.onnx); download the release to run this check")
        for model_id, entry in exported.items():
            assert (models_dir / entry["filename"]).is_file(), f"{model_id}: {entry['filename']} missing"
            if entry.get("filename_int8"):
                assert (models_dir / entry["filename_int8"]).is_file(), f"{model_id}: int8 file missing"
