"""Unit tests for infrastructure/runtime_setup.py."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from echo_personal_tool.infrastructure import runtime_setup as rs_mod


class TestCheckPythonVersion:
    def test_current_python_is_ok(self):
        assert rs_mod.check_python_version() is True

    def test_old_python_fails(self):
        with patch.object(sys, "version_info", (3, 9, 0)):
            assert rs_mod.check_python_version() is False

    def test_python_3_10_exact(self):
        with patch.object(sys, "version_info", (3, 10, 0)):
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
        with patch.object(rs_mod, "_MODELS_DIR", models_dir):
            assert rs_mod.check_models() is False


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


class TestInstallDeps:
    def test_install_creates_venv(self, tmp_path):
        venv_dir = tmp_path / "venv"

        def fake_create_venv(*args, **kwargs):
            # Simulate venv creation by creating the expected pip path
            pip_path = venv_dir / "bin" / "pip"
            pip_path.parent.mkdir(parents=True, exist_ok=True)
            pip_path.touch()
            return MagicMock(returncode=0)

        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch("subprocess.run", side_effect=fake_create_venv),
        ):
            result = rs_mod.install_deps()
            assert result is True

    def test_install_with_existing_venv(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_dir = venv_dir / "bin"
        pip_dir.mkdir()
        (pip_dir / "pip").touch()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch("subprocess.run"),
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
        pip_dir = venv_dir / "bin"
        pip_dir.mkdir()
        (pip_dir / "pip").touch()
        callback = MagicMock()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch("subprocess.run"),
        ):
            rs_mod.install_deps(progress_callback=callback)
            assert callback.called


class TestDownloadModels:
    def test_download_creates_dir(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        with (
            patch.object(rs_mod, "_MODELS_DIR", models_dir),
            patch.object(rs_mod, "_DATA_DIR", tmp_path),
            patch.object(rs_mod, "_download_file"),
            patch("tarfile.open") as mock_tar,
        ):
            mock_tar.return_value.__enter__ = MagicMock(return_value=MagicMock(getmembers=MagicMock(return_value=[])))
            mock_tar.return_value.__exit__ = MagicMock(return_value=False)
            (models_dir / "model_manifest.json").write_text("{}")
            result = rs_mod.download_models()
            assert result is True


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
