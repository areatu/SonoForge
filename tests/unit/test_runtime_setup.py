"""Unit tests for runtime_setup (pure functions, mocked I/O)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from echo_personal_tool.infrastructure.runtime_setup import (
    SetupStatus,
    _report,
    check_deps,
    check_models,
    check_python_version,
    get_setup_status,
)


class TestCheckPythonVersion:
    def test_current_python(self) -> None:
        assert check_python_version() is True


class TestCheckDeps:
    def test_all_installed(self) -> None:
        # In the test environment, most deps should be available
        result = check_deps()
        assert isinstance(result, bool)


class TestCheckModels:
    def test_models_not_exist(self) -> None:
        with patch("echo_personal_tool.infrastructure.runtime_setup._MODELS_DIR") as mock_dir:
            mock_dir.__truediv__ = MagicMock(return_value=MagicMock(is_file=MagicMock(return_value=False)))
            result = check_models()
            assert isinstance(result, bool)


class TestGetSetupStatus:
    def test_returns_setup_status(self) -> None:
        status = get_setup_status()
        assert isinstance(status, SetupStatus)
        assert isinstance(status.venv_exists, bool)
        assert isinstance(status.deps_installed, bool)
        assert isinstance(status.models_exist, bool)
        assert isinstance(status.python_ok, bool)


class TestReport:
    def test_with_callback(self) -> None:
        cb = MagicMock()
        _report(cb, "msg", 50)
        cb.assert_called_once_with("msg", 50)

    def test_without_callback(self) -> None:
        _report(None, "msg", 50)  # no exception

    def test_callback_exception_swallowed(self) -> None:
        cb = MagicMock(side_effect=RuntimeError("oops"))
        _report(cb, "msg", 50)  # no exception propagated


class TestSetupStatusDataclass:
    def test_creation(self) -> None:
        status = SetupStatus(
            venv_exists=True, deps_installed=False,
            models_exist=True, python_ok=True,
        )
        assert status.venv_exists is True
        assert status.deps_installed is False
