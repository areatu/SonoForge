"""Smoke tests — quick sanity checks that the package boots and core modules import."""

from __future__ import annotations

import importlib
import pkgutil

import pytest

from echo_personal_tool import __version__


# ── Version ──────────────────────────────────────────────────────


def test_version_is_set() -> None:
    assert __version__ == "0.2.2"


# ── Core imports ─────────────────────────────────────────────────


def test_onnx_engine_imports() -> None:
    pytest.importorskip("onnxruntime")
    from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

    assert OnnxInferenceEngine is not None


def test_main_package_importable() -> None:
    import echo_personal_tool

    assert hasattr(echo_personal_tool, "__version__")


def test_main_entry_point_importable() -> None:
    from echo_personal_tool import __main__

    assert hasattr(__main__, "main")


# ── Domain layer ────────────────────────────────────────────────


def test_domain_models_importable() -> None:
    from echo_personal_tool.domain import models

    assert models is not None


def test_domain_calculations_importable() -> None:
    from echo_personal_tool.domain import calculations

    assert calculations is not None


def test_domain_services_importable() -> None:
    from echo_personal_tool.domain import services

    assert services is not None


# ── Infrastructure layer ────────────────────────────────────────


def test_infrastructure_i18n_importable() -> None:
    from echo_personal_tool.infrastructure.i18n import set_language, tr

    assert callable(set_language)
    assert callable(tr)


def test_infrastructure_server_settings_importable() -> None:
    from echo_personal_tool.infrastructure.server_settings import ServerSettings

    assert ServerSettings is not None


def test_infrastructure_user_preferences_importable() -> None:
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences

    assert UserPreferences is not None


def test_infrastructure_dicom_importable() -> None:
    from echo_personal_tool.infrastructure import orthanc_client

    assert orthanc_client is not None


# ── i18n locales ────────────────────────────────────────────────


def test_i18n_loads_both_locales() -> None:
    from echo_personal_tool.infrastructure.i18n import set_language, tr

    set_language("ru")
    ru_text = tr("status.loading", name="test")
    set_language("en")
    en_text = tr("status.loading", name="test")
    assert isinstance(ru_text, str) and len(ru_text) > 0
    assert isinstance(en_text, str) and len(en_text) > 0


# ── Bundled resources ───────────────────────────────────────────


def test_bundled_fonts_accessible() -> None:
    from echo_personal_tool.resources.bundled_fonts import report_cyrillic_font_path

    path = report_cyrillic_font_path()
    assert path.exists(), f"Font not found: {path}"


# ── All subpackages importable ──────────────────────────────────


_SUBPACKAGES = [
    "echo_personal_tool.application",
    "echo_personal_tool.domain",
    "echo_personal_tool.domain.models",
    "echo_personal_tool.domain.calculations",
    "echo_personal_tool.domain.services",
    "echo_personal_tool.infrastructure",
    "echo_personal_tool.presentation",
    "echo_personal_tool.constructor",
    "echo_personal_tool.resources",
    "echo_personal_tool.ui",
]


@pytest.mark.parametrize("pkg_name", _SUBPACKAGES)
def test_subpackage_importable(pkg_name: str) -> None:
    mod = importlib.import_module(pkg_name)
    assert mod is not None
