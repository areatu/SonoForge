"""Unit tests for infrastructure/runtime_setup.py."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.infrastructure import runtime_setup as rs_mod


class TestCheckPythonVersion:
    def test_current_python_is_ok(self):
        assert rs_mod.check_python_version() is True

    def test_old_python_fails(self):
        # 3.10 is below the floor since 2026-10-22 (requires-python >=3.11,
        # raised for Pillow 13 — docs/reviews/2026-10-22-dependabot-alerts-ru.md),
        # so the boundary case is now the version that used to be supported.
        with patch.object(sys, "version_info", (3, 10, 0)):
            assert rs_mod.check_python_version() is False

    def test_python_3_11_exact(self):
        with patch.object(sys, "version_info", (3, 11, 0)):
            assert rs_mod.check_python_version() is True


class TestCheckModels:
    def test_models_exist(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "model_manifest.json").write_text("{}")
        with patch.object(rs_mod, "_MODELS_DIR", models_dir):
            assert rs_mod.check_models() is True

    def test_models_missing(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        with (
            patch.object(rs_mod, "_MODELS_DIR", models_dir),
            patch.object(rs_mod, "models_dirs_for_read", return_value=(models_dir,)),
        ):
            assert rs_mod.check_models() is False

    def test_models_found_in_legacy_read_fallback(self, tmp_path):
        models_dir = tmp_path / "new" / "models"
        legacy_dir = tmp_path / "old" / "models"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "model_manifest.json").write_text("{}")
        with (
            patch.object(rs_mod, "_MODELS_DIR", models_dir),
            patch.object(rs_mod, "models_dirs_for_read", return_value=(models_dir, legacy_dir)),
        ):
            assert rs_mod.check_models() is True


class TestGetSetupStatus:
    def test_all_ok(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "model_manifest.json").write_text("{}")
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_MODELS_DIR", models_dir),
            patch.object(rs_mod, "check_deps", return_value=True),
            patch.object(rs_mod, "check_python_version", return_value=True),
        ):
            status = rs_mod.get_setup_status()
            assert status.venv_exists is True
            assert status.deps_installed is True
            assert status.models_exist is True
            assert status.python_ok is True


def _venv_pip_path(venv_dir):
    return venv_dir / ("Scripts/pip.exe" if sys.platform == "win32" else "bin/pip")


def _venv_python_path(venv_dir):
    return venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


class TestInstallDeps:
    def test_install_creates_venv(self, tmp_path):
        venv_dir = tmp_path / "venv"

        def fake_create_venv(*args, **kwargs):
            # Simulate venv creation by creating the expected pip/python paths
            # (the post-install verification probes the venv interpreter).
            pip_path = _venv_pip_path(venv_dir)
            pip_path.parent.mkdir(parents=True, exist_ok=True)
            pip_path.touch()
            _venv_python_path(venv_dir).touch()
            return MagicMock(returncode=0)

        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", side_effect=fake_create_venv),
        ):
            result = rs_mod.install_deps()
            assert result is True

    def test_install_with_existing_venv(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_path = _venv_pip_path(venv_dir)
        pip_path.parent.mkdir(parents=True)
        pip_path.touch()
        _venv_python_path(venv_dir).touch()
        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result = rs_mod.install_deps()
            assert result is True

    def test_install_fails_no_pip(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch("subprocess.run"),
        ):
            result = rs_mod.install_deps()
            assert result is False

    def test_install_with_callback(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_path = _venv_pip_path(venv_dir)
        pip_path.parent.mkdir(parents=True)
        pip_path.touch()
        _venv_python_path(venv_dir).touch()
        callback = MagicMock()
        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            rs_mod.install_deps(progress_callback=callback)
            assert callback.called

    def test_install_failing_verification_is_not_reported_as_success(self, tmp_path):
        """#326: pip exit 0 is not enough — the venv must import the app deps."""
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_path = _venv_pip_path(venv_dir)
        pip_path.parent.mkdir(parents=True)
        pip_path.touch()
        _venv_python_path(venv_dir).touch()
        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch.object(rs_mod, "_verify_installed_deps", return_value=False),
        ):
            assert rs_mod.install_deps() is False


class TestVerifyInstalledDeps:
    def test_missing_venv_interpreter_fails(self, tmp_path):
        with patch.object(rs_mod, "_VENV_DIR", tmp_path):
            assert rs_mod._verify_installed_deps() is False

    def test_failed_probe_fails(self, tmp_path):
        _venv_python_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        _venv_python_path(tmp_path).touch()
        with (
            patch.object(rs_mod, "_VENV_DIR", tmp_path),
            patch("subprocess.run", return_value=MagicMock(returncode=1)),
        ):
            assert rs_mod._verify_installed_deps() is False

    def test_passing_probe_succeeds_and_checks_every_module(self, tmp_path):
        _venv_python_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        _venv_python_path(tmp_path).touch()
        with (
            patch.object(rs_mod, "_VENV_DIR", tmp_path),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as run,
        ):
            assert rs_mod._verify_installed_deps() is True
        argv = run.call_args.args[0]
        assert argv[0] == str(_venv_python_path(tmp_path))
        assert argv[1] == "-c"
        assert argv[3:] == rs_mod._REQUIRED_MODULES


class TestPinnedDependencyInstall:
    def test_online_install_requires_hashes(self, tmp_path):
        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        with patch.dict("os.environ", {"SONOFORGE_INSTALL_MODE": "online"}):
            args = rs_mod._dependency_install_args(pins)
        assert args == ["install", "--quiet", "--require-hashes", "-r", str(pins)]

    def test_offline_install_disables_indexes(self, tmp_path):
        pins = tmp_path / "pinned-packages.txt"
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        with patch.dict(
            "os.environ",
            {"SONOFORGE_INSTALL_MODE": "offline", "SONOFORGE_WHEELHOUSE": str(wheelhouse)},
        ):
            args = rs_mod._dependency_install_args(pins)
        assert args is not None
        assert "--no-index" in args
        assert args[args.index("--find-links") + 1] == str(wheelhouse)
        assert "--require-hashes" in args

    def test_offline_install_without_wheelhouse_fails_closed(self, tmp_path):
        with patch.dict("os.environ", {"SONOFORGE_INSTALL_MODE": "offline"}, clear=True):
            assert rs_mod._dependency_install_args(tmp_path / "pins.txt") is None

    def test_unpinned_source_install_is_refused(self, tmp_path):
        venv = tmp_path / "venv"
        pip = _venv_pip_path(venv)
        pip.parent.mkdir(parents=True)
        pip.touch()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=None),
            patch("subprocess.run") as run,
        ):
            assert rs_mod.install_deps() is False
        run.assert_not_called()


class TestRequiredModules:
    """#326: the environment check requires import names, never distributions."""

    def test_every_required_module_is_importable_here(self):
        import importlib

        missing = []
        for name in rs_mod._REQUIRED_MODULES:
            try:
                importlib.import_module(name)
            except ImportError:
                missing.append(name)
        assert missing == []

    def test_every_required_module_maps_to_a_locked_distribution(self):
        from pathlib import Path

        import tomllib

        def norm(name: str) -> str:
            return name.lower().replace("_", "-")

        lock = tomllib.loads((Path(__file__).resolve().parents[2] / "uv.lock").read_text(encoding="utf-8"))
        locked = {norm(pkg["name"]) for pkg in lock["package"]}
        assert set(rs_mod._MODULE_DISTRIBUTIONS) <= set(rs_mod._REQUIRED_MODULES)
        for module in rs_mod._REQUIRED_MODULES:
            distribution = rs_mod._MODULE_DISTRIBUTIONS.get(module, module)
            assert norm(distribution) in locked, f"{module} -> {distribution} not in uv.lock"

    def test_module_distribution_names_are_not_confused(self):
        # The #326 bug class: `cv2`/`yaml` are import names; PyPI has no such
        # distributions, so they must only ever appear as modules with an
        # explicit distribution mapping.
        for module in ("cv2", "yaml", "fitz"):
            assert module in rs_mod._REQUIRED_MODULES
            assert module in rs_mod._MODULE_DISTRIBUTIONS


class TestDownloadModels:
    def test_download_creates_dir(self, tmp_path):
        import hashlib

        models_dir = tmp_path / "models"
        models_dir.mkdir()

        # Since P1-5 the archive is hashed before extraction, so the stubbed
        # download must actually write bytes and the pinned digest has to match
        # them — a bare MagicMock used to write nothing and passed unverified.
        payload = b"stub release payload"

        def fake_download(url, dest, progress_callback=None):
            dest.write_bytes(payload)

        download = MagicMock(side_effect=fake_download)
        with (
            patch.object(rs_mod, "_MODELS_DIR", models_dir),
            patch.object(rs_mod, "_DATA_DIR", tmp_path),
            patch.object(rs_mod, "MODELS_RELEASE_SHA256", hashlib.sha256(payload).hexdigest()),
            patch.object(rs_mod, "_download_file", download),
            patch("tarfile.open") as mock_tar,
        ):
            mock_tar.return_value.__enter__ = MagicMock(return_value=MagicMock(getmembers=MagicMock(return_value=[])))
            mock_tar.return_value.__exit__ = MagicMock(return_value=False)
            (models_dir / "model_manifest.json").write_text("{}")
            result = rs_mod.download_models()
            assert result is True
            download.assert_called_once()


class TestValidateDownloadUrl:
    """#324/B310: only the pinned https release endpoint may be opened."""

    def test_release_url_is_accepted(self):
        assert rs_mod._validate_download_url(rs_mod._MODELS_RELEASE_URL) == rs_mod._MODELS_RELEASE_URL

    def test_plain_http_is_rejected(self):
        with pytest.raises(ValueError):
            rs_mod._validate_download_url("http://github.com/areatu/sonoforge-models/releases/download/m/m.tar.gz")

    def test_file_scheme_is_rejected(self):
        with pytest.raises(ValueError):
            rs_mod._validate_download_url("file:///etc/passwd")

    def test_unexpected_host_is_rejected(self):
        with pytest.raises(ValueError):
            rs_mod._validate_download_url("https://example.com/models-v1.tar.gz")

    def test_download_file_rejects_before_any_socket(self, tmp_path):
        with patch("urllib.request.urlopen") as urlopen, pytest.raises(ValueError):
            rs_mod._download_file("https://example.com/x.tar.gz", tmp_path / "x.tar.gz")
        urlopen.assert_not_called()


class TestReport:
    def test_report_calls_callback(self):
        cb = MagicMock()
        rs_mod._report(cb, "msg", 50)
        cb.assert_called_once_with("msg", 50)

    def test_report_none_callback(self):
        rs_mod._report(None, "msg", 50)  # should not raise

    def test_report_callback_exception_swallowed(self):
        def bad_cb(msg, pct):
            raise RuntimeError("oops")

        rs_mod._report(bad_cb, "msg", 50)  # should not raise


class TestSetupStatusDataclass:
    def test_fields(self):
        status = rs_mod.SetupStatus(
            venv_exists=True,
            deps_installed=False,
            models_exist=True,
            python_ok=True,
        )
        assert status.venv_exists is True
        assert status.deps_installed is False
        assert status.models_exist is True
        assert status.python_ok is True
