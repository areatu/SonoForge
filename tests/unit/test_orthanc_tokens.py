"""UI-0 PR-6 — Orthanc views and delegates use semantic theme tokens."""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def apply_theme(monkeypatch):
    from echo_personal_tool.presentation import dark_theme

    def _apply(theme: str) -> dict[str, str]:
        monkeypatch.setattr(dark_theme, "_current_theme_mode", theme)
        return dark_theme.get_theme_tokens()

    return _apply


def test_loader_stylesheet_uses_semantic_tokens(apply_theme) -> None:
    from echo_personal_tool.presentation.orthanc_study_dialog import build_loader_dialog_stylesheet

    tokens = apply_theme("graphite")
    stylesheet = build_loader_dialog_stylesheet()
    colours = set(re.findall(r"#[0-9a-fA-F]{3,8}\b", stylesheet))

    assert tokens["accent"] in stylesheet
    assert tokens["accent.action.text"] in stylesheet
    assert tokens["text.1"] in stylesheet
    assert colours <= set(tokens.values())


def test_loader_stylesheet_accepts_the_legacy_palette_contract(apply_theme) -> None:
    from echo_personal_tool.presentation.dark_theme import get_theme_palette
    from echo_personal_tool.presentation.orthanc_study_dialog import build_loader_dialog_stylesheet

    tokens = apply_theme("dark")
    stylesheet = build_loader_dialog_stylesheet(get_theme_palette())

    assert tokens["surface.0"] in stylesheet
    assert tokens["accent.action.text"] in stylesheet


def test_orthanc_fixed_tokens_retain_delegate_colours() -> None:
    from echo_personal_tool.presentation.theme.palettes import PALETTES, THEME_IDS

    expected = {
        "surface.thumbnail": "#05070a",
        "control.checkmark": "#08202c",
        "accent.action.text": "#062026",
        "badge.success.text": "#03261a",
        "badge.status.text": "#2a1602",
    }
    for theme_id in THEME_IDS:
        for token, value in expected.items():
            assert PALETTES[theme_id][token] == value


def test_server_settings_warning_styles_follow_active_tokens(qtbot, monkeypatch, apply_theme) -> None:
    from echo_personal_tool.infrastructure.server_settings import ServerSettings
    from echo_personal_tool.presentation import server_settings_dialog

    monkeypatch.setattr(server_settings_dialog, "load_server_settings", lambda: ServerSettings())
    tokens = apply_theme("graphite")
    form = server_settings_dialog.ServerSettingsForm()
    qtbot.addWidget(form)

    assert tokens["state.warn"] in form._tls_verify_warning.styleSheet()
    assert tokens["state.warn"] in form._dimse_tls_warning.styleSheet()
    assert tokens["text.2"] in form._tls_ca_hint.styleSheet()
