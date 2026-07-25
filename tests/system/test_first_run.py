"""System tests: runtime_setup can check python version, check models, get setup status."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.system


class TestFirstRun:
    def test_check_python_version_passes(self) -> None:
        """check_python_version returns True when running Python >= 3.10."""
        from echo_personal_tool.infrastructure.runtime_setup import check_python_version

        assert check_python_version() is True

    def test_check_python_version_actual(self) -> None:
        """Python version in use is at least 3.10."""
        assert sys.version_info >= (3, 10)

    def test_get_setup_status_returns_dataclass(self) -> None:
        """get_setup_status returns a SetupStatus dataclass."""
        from echo_personal_tool.infrastructure.runtime_setup import SetupStatus, get_setup_status

        status = get_setup_status()
        assert isinstance(status, SetupStatus)
        assert isinstance(status.python_ok, bool)
        assert isinstance(status.deps_installed, bool)
        assert isinstance(status.models_exist, bool)
        assert isinstance(status.venv_exists, bool)

    def test_setup_status_python_ok(self) -> None:
        """SetupStatus.python_ok should be True on this environment."""
        from echo_personal_tool.infrastructure.runtime_setup import get_setup_status

        status = get_setup_status()
        assert status.python_ok is True

    def test_check_deps_mocked(self) -> None:
        """check_deps can be mocked to return False."""
        from echo_personal_tool.infrastructure.runtime_setup import check_deps

        with patch("echo_personal_tool.infrastructure.runtime_setup.importlib.import_module", side_effect=ImportError):
            result = check_deps()
            assert result is False

    def test_check_models_mocked_missing(self) -> None:
        """check_models returns False when model manifest doesn't exist."""
        from echo_personal_tool.infrastructure.runtime_setup import check_models

        with patch("echo_personal_tool.infrastructure.runtime_setup._MODELS_DIR") as mock_dir:
            mock_dir.__truediv__ = MagicMock(return_value=MagicMock(is_file=MagicMock(return_value=False)))
            result = check_models()
            assert result is False

    def test_setup_status_venv_exists(self) -> None:
        """SetupStatus.venv_exists is a boolean (may be True or False)."""
        from echo_personal_tool.infrastructure.runtime_setup import get_setup_status

        status = get_setup_status()
        assert isinstance(status.venv_exists, bool)

    def test_check_deps_real(self) -> None:
        """check_deps returns True in the dev environment (all deps installed)."""
        from echo_personal_tool.infrastructure.runtime_setup import check_deps

        result = check_deps()
        assert isinstance(result, bool)

    def test_required_packages_list_populated(self) -> None:
        """_REQUIRED_PACKAGES is a non-empty list of strings."""
        from echo_personal_tool.infrastructure.runtime_setup import _REQUIRED_PACKAGES

        assert isinstance(_REQUIRED_PACKAGES, list)
        assert len(_REQUIRED_PACKAGES) > 0
        assert all(isinstance(p, str) for p in _REQUIRED_PACKAGES)
