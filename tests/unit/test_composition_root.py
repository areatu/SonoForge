"""Unit tests for the #480 application composition root (``application.composition``)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.composition import (
    DEFAULT_HERMETIC_PLAYBACK_CONFIG,
    FALLBACK_RAM_CAP_BYTES,
    AppPaths,
    DisabledOnnxSegmenter,
    build_app_services,
    compute_frame_cache_budget,
    services_of,
)
from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine
from echo_personal_tool.infrastructure.user_preferences import UserPreferences

pytestmark = pytest.mark.gui


def test_app_controller_instantiates_without_preferences_psutil_or_home(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    """Default ``AppController()`` touches neither user settings, psutil, nor ``$HOME``."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("AppController() must not probe host preferences, RAM, or paths")

    monkeypatch.setenv("HOME", "/nonexistent-sonoforge-home-480")
    monkeypatch.setattr("echo_personal_tool.infrastructure.user_preferences.load_user_preferences", _forbidden)
    monkeypatch.setattr("echo_personal_tool.application.user_preferences.load_user_preferences", _forbidden)
    monkeypatch.setattr("echo_personal_tool.infrastructure.paths.measurements_dir", _forbidden)
    monkeypatch.setattr("psutil.virtual_memory", _forbidden)

    controller = AppController()
    try:
        bound = services_of(controller)
        assert bound is not None
        assert not controller.measurement_persistence.enabled
        assert isinstance(bound.segmenter, DisabledOnnxSegmenter)
        assert not bound.segmenter.is_available()
        assert controller.playback_config == DEFAULT_HERMETIC_PLAYBACK_CONFIG
    finally:
        controller.measurement_persistence.close()


def test_app_services_fixture_wires_hermetic_controller(
    app_services,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    """The ``app_services`` fixture builds a working controller without touching QSettings."""
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.user_preferences.load_user_preferences",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected load_user_preferences call")),
    )
    controller = AppController(app_services)
    try:
        bound = services_of(controller)
        assert bound is app_services
        assert controller.state_manager is app_services.state_manager
        assert controller.measurement_persistence is app_services.persistence
        assert bound.frame_cache is app_services.frame_cache
    finally:
        controller.measurement_persistence.close()


def test_build_app_services_distinguishes_full_and_presenter_profiles(tmp_path: Path, qapp) -> None:
    """Full vs Presenter capabilities and adapters are expressed via ``AppServices``."""
    full_services = build_app_services(
        "full",
        paths=AppPaths.under(tmp_path / "full"),
        available_ram_bytes=8 * 1024 * 1024 * 1024,
    )
    presenter_services = build_app_services(
        "presenter",
        paths=AppPaths.under(tmp_path / "presenter"),
        available_ram_bytes=8 * 1024 * 1024 * 1024,
    )
    try:
        assert full_services.profile == "full"
        assert full_services.display_name == "SonoForge"
        assert full_services.capabilities.ai_segmentation is True
        assert full_services.capabilities.reference_ui is True
        assert full_services.capabilities.presenter_view is False
        assert isinstance(full_services.segmenter, OnnxInferenceEngine)
        assert full_services.persistence.enabled is True
        full_services.io.recent_folders.record(tmp_path)
        assert len(full_services.io.recent_folders.entries()) == 1

        assert presenter_services.profile == "presenter"
        assert presenter_services.display_name == "SonoForge Presenter"
        assert presenter_services.capabilities.ai_segmentation is False
        assert presenter_services.capabilities.reference_ui is False
        assert presenter_services.capabilities.presenter_view is True
        assert isinstance(presenter_services.segmenter, DisabledOnnxSegmenter)
        assert presenter_services.segmenter.is_available() is False
        with pytest.raises(RuntimeError, match="disabled"):
            presenter_services.segmenter.segment(np.zeros((8, 8), dtype=np.uint8))
        # Presenter defaults measurement storage off and keeps recent folders inert.
        assert presenter_services.persistence.enabled is False
        presenter_services.io.recent_folders.record(tmp_path)
        assert presenter_services.io.recent_folders.entries() == ()
    finally:
        full_services.persistence.close()
        presenter_services.persistence.close()


def test_compute_frame_cache_budget_caps_at_eight_percent_ram_and_handles_psutil_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Frame-cache budget obeys both the preference floor and the 8% physical RAM cap."""
    prefs = UserPreferences(playback_max_cache_mb=256)
    constrained = compute_frame_cache_budget(
        prefs,
        available_ram_bytes=1024 * 1024 * 1024,
        playback_config=DEFAULT_HERMETIC_PLAYBACK_CONFIG,
    )
    expected_cap = int(1024 * 1024 * 1024 * 0.08)
    assert constrained.ram_cap_bytes == expected_cap
    assert constrained.max_cache_bytes == expected_cap

    roomy = compute_frame_cache_budget(
        prefs,
        available_ram_bytes=16 * 1024 * 1024 * 1024,
        playback_config=DEFAULT_HERMETIC_PLAYBACK_CONFIG,
    )
    assert roomy.max_cache_bytes == 256 * 1024 * 1024

    monkeypatch.setattr(
        "psutil.virtual_memory",
        lambda: (_ for _ in ()).throw(OSError("proc unavailable")),
    )
    fallback = compute_frame_cache_budget(
        prefs,
        playback_config=DEFAULT_HERMETIC_PLAYBACK_CONFIG,
    )
    assert fallback.ram_cap_bytes == FALLBACK_RAM_CAP_BYTES
    assert fallback.max_cache_bytes == 256 * 1024 * 1024


def test_main_window_requires_explicit_controller_and_honours_injected_presenter_services(
    qtbot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MainWindow`` rejects implicit graph assembly and follows ``AppServices`` over env vars."""
    from echo_personal_tool.presentation.main_window import MainWindow

    with pytest.raises(TypeError, match="explicit controller"):
        MainWindow()

    monkeypatch.setenv("SONOFORGE_PROFILE", "full")
    presenter_services = build_app_services(
        "presenter",
        preferences=UserPreferences(layout_state_json="", measurement_persistence_enabled=False),
        paths=AppPaths.under(tmp_path / "presenter-ui"),
    )
    controller = AppController(presenter_services)
    window = MainWindow(
        controller=controller,
        user_preferences=presenter_services.preferences,
        services=presenter_services,
    )
    qtbot.addWidget(window)
    try:
        assert window.windowTitle() == "SonoForge Presenter"
        bound = services_of(controller)
        assert bound is presenter_services
        assert bound.capabilities.presenter_view is True
        assert bound.capabilities.ai_segmentation is False
        assert bound.capabilities.reference_ui is False
    finally:
        presenter_services.persistence.close()
