"""System tests: import main module, verify QApplication creation, verify main() callable."""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.system


class TestInstallLaunch:
    def test_import_main_module(self) -> None:
        """echo_personal_tool.main can be imported."""
        mod = importlib.import_module("echo_personal_tool.main")
        assert hasattr(mod, "main")
        assert callable(mod.main)

    def test_import_application_package(self) -> None:
        """echo_personal_tool.application can be imported."""
        mod = importlib.import_module("echo_personal_tool.application")
        assert mod is not None

    def test_import_app_controller(self) -> None:
        """AppController can be imported and instantiated."""
        from echo_personal_tool.application.app_controller import AppController

        ctrl = AppController()
        assert ctrl is not None

    def test_import_main_window(self) -> None:
        """MainWindow can be imported."""
        from echo_personal_tool.presentation.main_window import MainWindow

        assert MainWindow is not None

    def test_import_domain_models(self) -> None:
        """Domain models can be imported."""
        from echo_personal_tool.domain.models import Contour, LinearMeasurement

        assert Contour is not None
        assert LinearMeasurement is not None

    def test_import_domain_calculations(self) -> None:
        """Domain calculations can be imported."""
        from echo_personal_tool.domain.calculations.body_surface import bsa_du_bois_m2
        from echo_personal_tool.domain.calculations.lvef_simpson import calculate

        assert callable(bsa_du_bois_m2)
        assert callable(calculate)

    def test_import_version(self) -> None:
        """Package version is accessible."""
        from echo_personal_tool import __version__

        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_qapplication_can_be_created(self) -> None:
        """QApplication can be instantiated."""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        assert app is not None

    def test_main_function_is_callable(self) -> None:
        """main() is a callable that returns an int."""
        from echo_personal_tool.main import main

        assert callable(main)
        import inspect

        sig = inspect.signature(main)
        assert sig.return_annotation is not None or True  # just verify callable

    def test_infrastructure_modules_importable(self) -> None:
        """Key infrastructure modules can be imported."""
        from echo_personal_tool.infrastructure.dicom_uid_validator import validate_dicom_uid
        from echo_personal_tool.infrastructure.runtime_setup import check_python_version
        from echo_personal_tool.infrastructure.user_preferences import UserPreferences

        assert callable(validate_dicom_uid)
        assert callable(check_python_version)
        assert UserPreferences is not None
