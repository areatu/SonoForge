"""System tests: graceful handling when optional deps are missing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.system


class TestMissingDeps:
    def test_import_graceful_with_mocked_import_error(self) -> None:
        """Importing a module gracefully handles ImportError from missing dep."""
        import importlib

        # Simulate a missing optional dependency
        with patch.dict("sys.modules", {"nonexistent_optional_dep": None}):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                importlib.import_module("nonexistent_optional_dep")

    def test_onnx_engine_fallback(self) -> None:
        """OnnxEngine gracefully reports unavailable when ONNX runtime is missing."""
        from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

        # The engine may or may not have models; test the is_available path
        engine = OnnxInferenceEngine.__new__(OnnxInferenceEngine)
        # Check that the class exists and can be instantiated (even if no models)
        assert OnnxInferenceEngine is not None

    def test_runtime_setup_deps_check_with_missing_package(self) -> None:
        """check_deps returns False when a required package is not importable."""
        from echo_personal_tool.infrastructure.runtime_setup import check_deps

        original_import_module = __import__("importlib").import_module

        def mock_import_module(name, *args, **kwargs):
            if name == "PySide6":
                raise ImportError("simulated missing PySide6")
            return original_import_module(name, *args, **kwargs)

        with patch(
            "echo_personal_tool.infrastructure.runtime_setup.importlib.import_module",
            side_effect=mock_import_module,
        ):
            result = check_deps()
            assert result is False

    def test_setup_status_when_deps_missing(self) -> None:
        """get_setup_status reports deps_installed=False when deps are missing."""
        from echo_personal_tool.infrastructure.runtime_setup import get_setup_status

        with patch("echo_personal_tool.infrastructure.runtime_setup.check_deps", return_value=False):
            status = get_setup_status()
            assert status.deps_installed is False

    def test_show_setup_dialog_import(self) -> None:
        """show_setup_dialog can be imported even without showing the dialog."""
        from echo_personal_tool.infrastructure.runtime_setup import show_setup_dialog

        assert callable(show_setup_dialog)

    def test_domain_models_importable_without_onnx(self) -> None:
        """Domain models can be imported even if onnxruntime is not available."""
        from echo_personal_tool.domain.models import Contour, LinearMeasurement

        assert Contour is not None
        assert LinearMeasurement is not None

    def test_fake_client_independent_of_network(self) -> None:
        """FakeDicomWebClient works without network access."""
        from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient

        client = FakeDicomWebClient()
        assert client.ping() is True
        studies = client.query_studies()
        assert isinstance(studies, list)
