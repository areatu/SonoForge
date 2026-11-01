"""Unit tests for infrastructure/runtime_setup.py."""

from __future__ import annotations

import subprocess
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
        for module in ("cv2", "yaml"):
            assert module in rs_mod._REQUIRED_MODULES
            assert module in rs_mod._MODULE_DISTRIBUTIONS

    def test_pymupdf_needs_no_distribution_alias(self):
        # PyMuPDF 2.0 deprecated the `fitz` shim (FutureWarning on every
        # startup), so the required module is `pymupdf` — the import name
        # equals the distribution name and no mapping may reappear.
        assert "pymupdf" in rs_mod._REQUIRED_MODULES
        assert "fitz" not in rs_mod._REQUIRED_MODULES
        assert "fitz" not in rs_mod._MODULE_DISTRIBUTIONS


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


class TestInstallIdempotency:
    """#326: a second run on a ready environment must be a no-op, not a redo."""

    def _prepared_venv(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_path = _venv_pip_path(venv_dir)
        pip_path.parent.mkdir(parents=True)
        pip_path.touch()
        _venv_python_path(venv_dir).touch()
        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        return venv_dir, pip_path, pins

    def test_second_run_reuses_the_venv_and_succeeds(self, tmp_path):
        venv_dir, pip_path, pins = self._prepared_venv(tmp_path)
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as run,
        ):
            assert rs_mod.install_deps() is True
            assert rs_mod.install_deps() is True

        # The verification probe spawns the venv interpreter too; the pip calls
        # are the ones that start from the venv's pip executable.
        pip_calls = [call.args[0] for call in run.call_args_list if call.args[0][0] == str(pip_path)]
        assert len(pip_calls) == 2, "two installs, no venv recreation"
        assert all(call[-2] == "-r" and call[-1] == str(pins) for call in pip_calls)
        assert not any("-m" in call for call in pip_calls), "an existing venv must not be recreated"

    def test_pip_never_receives_a_bare_module_name(self, tmp_path):
        """The #326 regression guard: install arguments are a pins file, never names."""
        venv_dir, pip_path, pins = self._prepared_venv(tmp_path)
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as run,
        ):
            assert rs_mod.install_deps() is True

        argv = next(call.args[0] for call in run.call_args_list if call.args[0][0] == str(pip_path))
        for module in rs_mod._REQUIRED_MODULES:
            assert module not in argv, f"{module} is an import name, not a distribution"
        for module_only in ("cv2", "yaml", "PIL", "fitz"):
            assert module_only not in argv


class TestInstallFailureMessages:
    """#326: the user gets one sentence, pip's output stays in the log."""

    def _failing_install(self, tmp_path, exc):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_path = _venv_pip_path(venv_dir)
        pip_path.parent.mkdir(parents=True)
        pip_path.touch()
        _venv_python_path(venv_dir).touch()
        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        callback = MagicMock()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", side_effect=exc),
        ):
            result = rs_mod.install_deps(progress_callback=callback)
        messages = [call.args[0] for call in callback.call_args_list]
        return result, messages

    @pytest.mark.parametrize(
        ("stderr", "reason"),
        [
            (b"ERROR: Could not find a version that satisfies the requirement cv2", "pip_failed_unavailable"),
            (b"WARNING: Retrying\nConnectionError: HTTPSConnectionPool(host='pypi.org')", "pip_failed_network"),
            (b"ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.", "pip_failed_hash"),
            (b"ERROR: something entirely unexpected", "pip_failed"),
            (None, "pip_failed"),
        ],
    )
    def test_pip_failures_are_classified(self, stderr, reason):
        assert rs_mod._pip_failure_reason(stderr) == reason

    def test_network_failure_tells_the_user_what_to_do(self, tmp_path):
        exc = subprocess.CalledProcessError(
            1,
            "pip",
            output=b"",
            stderr=b"ERROR: Could not install packages due to an OSError: ConnectionError: timed out",
        )
        result, messages = self._failing_install(tmp_path, exc)

        assert result is False
        assert messages[-1] == rs_mod._INSTALL_FAILURE_MESSAGES["pip_failed_network"]
        joined = "\n".join(messages)
        assert "Traceback" not in joined
        assert "ERROR:" not in joined
        assert "pypi" not in joined.lower()

    def test_hash_failure_is_named_as_an_integrity_problem(self, tmp_path):
        exc = subprocess.CalledProcessError(
            1,
            "pip",
            output=b"",
            stderr=b"ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.",
        )
        result, messages = self._failing_install(tmp_path, exc)

        assert result is False
        assert messages[-1] == rs_mod._INSTALL_FAILURE_MESSAGES["pip_failed_hash"]

    def test_every_failure_message_is_a_single_sentence(self):
        for reason, message in rs_mod._INSTALL_FAILURE_MESSAGES.items():
            assert message.endswith("."), f"{reason}: {message}"
            assert "\n" not in message, f"{reason} must stay one line"
            assert "Traceback" not in message
            assert "{" not in message and "}" not in message

    def test_missing_pin_file_is_reported_before_any_install(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_path = _venv_pip_path(venv_dir)
        pip_path.parent.mkdir(parents=True)
        pip_path.touch()
        callback = MagicMock()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=None),
            patch("subprocess.run") as run,
        ):
            assert rs_mod.install_deps(progress_callback=callback) is False

        run.assert_not_called()
        assert callback.call_args_list[-1].args[0] == rs_mod._INSTALL_FAILURE_MESSAGES["pins_missing"]

    def test_venv_creation_failure_is_reported(self, tmp_path):
        venv_dir = tmp_path / "venv"
        callback = MagicMock()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "venv")),
        ):
            assert rs_mod.install_deps(progress_callback=callback) is False

        assert callback.call_args_list[-1].args[0] == rs_mod._INSTALL_FAILURE_MESSAGES["venv_failed"]

    def test_unlaunchable_pip_is_reported_as_a_broken_environment(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_path = _venv_pip_path(venv_dir)
        pip_path.parent.mkdir(parents=True)
        pip_path.touch()
        _venv_python_path(venv_dir).touch()
        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        callback = MagicMock()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", side_effect=OSError("cannot execute")),
        ):
            assert rs_mod.install_deps(progress_callback=callback) is False

        assert callback.call_args_list[-1].args[0] == rs_mod._INSTALL_FAILURE_MESSAGES["pip_missing"]

    def test_verification_failure_is_not_reported_as_success(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        pip_path = _venv_pip_path(venv_dir)
        pip_path.parent.mkdir(parents=True)
        pip_path.touch()
        _venv_python_path(venv_dir).touch()
        pins = tmp_path / "pinned-packages.txt"
        pins.write_text("numpy==1.26.4 --hash=sha256:" + "a" * 64 + "\n")
        callback = MagicMock()
        with (
            patch.object(rs_mod, "_VENV_DIR", venv_dir),
            patch.object(rs_mod, "_pinned_requirements_file", return_value=pins),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch.object(rs_mod, "_verify_installed_deps", return_value=False),
        ):
            assert rs_mod.install_deps(progress_callback=callback) is False

        assert callback.call_args_list[-1].args[0] == rs_mod._INSTALL_FAILURE_MESSAGES["verify_failed"]
        assert all(call.args[0] != "Dependencies installed." for call in callback.call_args_list)


class TestRunSetupTasks:
    """#326: the first-run sequence itself — order, short-circuit, frozen builds."""

    def _status(self, *, deps: bool, models: bool) -> rs_mod.SetupStatus:
        return rs_mod.SetupStatus(venv_exists=True, deps_installed=deps, models_exist=models, python_ok=True)

    def test_dependencies_run_before_models(self):
        calls: list[str] = []
        with (
            patch.object(rs_mod, "install_deps", side_effect=lambda cb=None: calls.append("deps") or True),
            patch.object(rs_mod, "download_models", side_effect=lambda cb=None: calls.append("models") or True),
        ):
            assert rs_mod.run_setup_tasks(self._status(deps=False, models=False), frozen=False) is True

        assert calls == ["deps", "models"]

    def test_a_present_environment_does_nothing(self):
        with (
            patch.object(rs_mod, "install_deps") as deps,
            patch.object(rs_mod, "download_models") as models,
        ):
            assert rs_mod.run_setup_tasks(self._status(deps=True, models=True), frozen=False) is True

        deps.assert_not_called()
        models.assert_not_called()

    def test_frozen_build_skips_the_dependency_install(self):
        with (
            patch.object(rs_mod, "install_deps") as deps,
            patch.object(rs_mod, "download_models", return_value=True) as models,
        ):
            assert rs_mod.run_setup_tasks(self._status(deps=False, models=False), frozen=True) is True

        deps.assert_not_called()
        models.assert_called_once()

    def test_download_is_skipped_when_the_install_failed(self):
        with (
            patch.object(rs_mod, "install_deps", return_value=False),
            patch.object(rs_mod, "download_models") as models,
        ):
            assert rs_mod.run_setup_tasks(self._status(deps=False, models=False), frozen=False) is False

        models.assert_not_called()

    def test_a_failed_download_fails_the_whole_setup(self):
        with (
            patch.object(rs_mod, "install_deps", return_value=True),
            patch.object(rs_mod, "download_models", return_value=False),
        ):
            assert rs_mod.run_setup_tasks(self._status(deps=False, models=False), frozen=False) is False

    def test_progress_callback_reaches_both_tasks(self):
        callback = MagicMock()
        with (
            patch.object(rs_mod, "install_deps") as deps,
            patch.object(rs_mod, "download_models") as models,
        ):
            deps.return_value = True
            models.return_value = True
            rs_mod.run_setup_tasks(self._status(deps=False, models=False), callback, frozen=False)

        assert deps.call_args.args[0] is callback
        assert models.call_args.args[0] is callback

    def test_frozen_defaults_to_the_interpreter_attribute(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(rs_mod, "install_deps") as deps,
            patch.object(rs_mod, "download_models", return_value=True),
        ):
            rs_mod.run_setup_tasks(self._status(deps=False, models=False))

        deps.assert_not_called()


class TestCheckDeps:
    """#326: a module that cannot load its native library is missing too."""

    def test_unloadable_module_counts_as_missing(self):
        real_import = rs_mod.importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "cv2":
                raise OSError("libGL.so.1: cannot open shared object file")
            return real_import(name, *args, **kwargs)

        with patch.object(rs_mod.importlib, "import_module", side_effect=fake_import):
            assert rs_mod.check_deps() is False

    def test_missing_module_counts_as_missing(self):
        real_import = rs_mod.importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("no module named yaml")
            return real_import(name, *args, **kwargs)

        with patch.object(rs_mod.importlib, "import_module", side_effect=fake_import):
            assert rs_mod.check_deps() is False


class TestShowSetupDialogOutcome:
    """#326: the dialog answers honestly, and a ready environment is not asked.

    The dialog's own Qt loop is covered by the GUI suite; what is checked here
    is the decision the caller sees — the old implementation returned
    ``worker.isRunning() or not worker.isRunning()``, i.e. always True.
    """

    def test_ready_environment_returns_true_without_building_a_dialog(self):
        status = rs_mod.SetupStatus(venv_exists=True, deps_installed=True, models_exist=True, python_ok=True)
        with (
            patch.object(rs_mod, "get_setup_status", return_value=status),
            patch.object(rs_mod, "install_deps") as deps,
            patch.object(rs_mod, "download_models") as models,
        ):
            assert rs_mod.show_setup_dialog() is True

        deps.assert_not_called()
        models.assert_not_called()
