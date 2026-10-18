"""Canonical shortcut metadata, localization and generated Help section."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.i18n import tr_for_language
from echo_personal_tool.keyboard_shortcuts import (
    SHORTCUTS,
    event_matches_shortcut,
    get_shortcut,
    main_window_shortcuts,
    render_shortcut_help_markdown,
    replace_shortcut_help_section,
    shortcut_conflicts,
    shortcut_label,
    shortcuts_for_profile,
)

_LOCALES_DIR = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "infrastructure" / "locales"


def _locale(language: str) -> dict[str, str]:
    return json.loads((_LOCALES_DIR / f"{language}.json").read_text(encoding="utf-8"))


def test_registry_ids_are_unique_and_all_translations_exist() -> None:
    assert len({shortcut.id for shortcut in SHORTCUTS}) == len(SHORTCUTS)
    assert not shortcut_conflicts()
    assert not shortcut_conflicts("full")
    assert not shortcut_conflicts("presenter")
    for language in ("en", "ru"):
        translations = _locale(language)
        for shortcut in SHORTCUTS:
            assert shortcut.description_key in translations
            assert shortcut.group_key in translations
            assert f"{shortcut.group_key}.intro" in translations
        assert "shortcuts.help.heading" in translations
        assert "shortcuts.help.no_inference" in translations


def test_profile_filters_bindings_without_losing_common_actions() -> None:
    full = {shortcut.id for shortcut in shortcuts_for_profile("full")}
    presenter = {shortcut.id for shortcut in shortcuts_for_profile("presenter")}
    assert "auto_segment" in full and "auto_segment" not in presenter
    assert "presenter_toggle" in presenter and "presenter_toggle" not in full
    assert "reference_reload_web" in full and "reference_reload_web" not in presenter
    assert "new_tab" in full & presenter
    assert {shortcut.id for shortcut in main_window_shortcuts("presenter")} >= {
        "open_folder",
        "load_server",
        "new_tab",
        "presenter_toggle",
    }
    assert "presenter_toggle" not in {shortcut.id for shortcut in main_window_shortcuts("full")}


def test_inline_and_gesture_labels_use_locale_metadata() -> None:
    assert shortcut_label("caliper", language="en") == "L"
    assert shortcut_label("finish_tool", language="en") == "Enter / Return"
    assert shortcut_label("multiview_ctrl_click", language="en") == "Ctrl+click"
    assert shortcut_label("multiview_ctrl_click", language="ru") == "Ctrl+клик"
    assert get_shortcut("multiview_ctrl_click").kind == "gesture"
    assert shortcut_label("play_pause", language="ru") == "Пробел"
    assert shortcut_label("reference_next_page", language="ru") == "→ / ↓ / Пробел"


def test_dynamic_hint_templates_use_registered_key_labels() -> None:
    for language in ("en", "ru"):
        finish_key = shortcut_label("finish_tool", language=language)
        cancel_key = shortcut_label("cancel_tool", language=language)
        values = (
            ("status.calibration_click", {"cancel_key": cancel_key}),
            ("status.calibration_bmode_click", {"cancel_key": cancel_key}),
            (
                "viewer.vessel_cycle_candidate",
                {
                    "index": 2,
                    "count": 5,
                    "value": 73.2,
                    "left_key": shortcut_label("vessel_previous_cycle", language=language),
                    "right_key": shortcut_label("vessel_next_cycle", language=language),
                    "accept_key": finish_key,
                    "cancel_key": cancel_key,
                },
            ),
            ("viewer.lv_trace_prompt", {"finish_key": finish_key}),
            ("viewer.atrial_trace_prompt", {"finish_key": finish_key}),
            ("doppler.trace_click_end", {"finish_key": finish_key}),
        )
        for key, kwargs in values:
            assert "{" not in tr_for_language(key, language, **kwargs)


def test_help_is_rendered_from_registry_and_respects_profile() -> None:
    full = render_shortcut_help_markdown("en", profile="full")
    presenter = render_shortcut_help_markdown("ru", profile="presenter")
    command_tab = "⌘T" if sys.platform == "darwin" else "Ctrl+T"
    assert f"| `{command_tab}` |" in full
    assert "| `Ctrl+клик` |" in presenter
    assert "| `` ` `` |" in full
    assert "Presenter view" not in full
    assert "Request AI segmentation" in full
    assert "Request AI segmentation" not in presenter
    assert "режим докладчика" in presenter
    assert "`I`" not in presenter


def test_help_section_replacement_preserves_content_outside_section() -> None:
    source = "# Guide\n\nBefore.\n\n## 18. Old shortcuts\n\nOld list.\n\n## 19. Next\n\nAfter.\n"
    result = replace_shortcut_help_section(source, "en", profile="full", add_markers=True)
    assert result.startswith("# Guide\n\nBefore.")
    assert "<!-- SHORTCUT_REGISTRY:START -->" in result
    assert "Old list." not in result
    assert "## 19. Next\n\nAfter." in result
    assert replace_shortcut_help_section(result, "en", profile="full", add_markers=True) == result


def test_event_matching_uses_registered_sequences() -> None:
    qt_core = pytest.importorskip("PySide6.QtCore")
    qt_gui = pytest.importorskip("PySide6.QtGui")
    primary_o = qt_gui.QKeyEvent(
        qt_core.QEvent.Type.KeyPress,
        qt_core.Qt.Key.Key_O,
        qt_core.Qt.KeyboardModifier.MetaModifier
        if sys.platform == "darwin"
        else qt_core.Qt.KeyboardModifier.ControlModifier,
    )
    enter = qt_gui.QKeyEvent(
        qt_core.QEvent.Type.KeyPress,
        qt_core.Qt.Key.Key_Enter,
        qt_core.Qt.KeyboardModifier.NoModifier,
    )
    assert event_matches_shortcut(primary_o, "open_folder")
    assert not event_matches_shortcut(primary_o, "load_server")
    assert event_matches_shortcut(enter, "finish_tool")


def test_mac_shortcut_labels_use_command_and_option_symbols(monkeypatch) -> None:
    import echo_personal_tool.keyboard_shortcuts as shortcuts

    monkeypatch.setattr(shortcuts.sys, "platform", "darwin")
    assert shortcut_label("command_field") == "⌘K"
    assert shortcut_label("open_folder") == "⌘O"


def test_macos_command_shortcut_matches_meta_modifier(monkeypatch) -> None:
    qt_core = pytest.importorskip("PySide6.QtCore")
    qt_gui = pytest.importorskip("PySide6.QtGui")
    import echo_personal_tool.keyboard_shortcuts as shortcuts

    monkeypatch.setattr(shortcuts.sys, "platform", "darwin")
    event = qt_gui.QKeyEvent(
        qt_core.QEvent.Type.KeyPress,
        qt_core.Qt.Key.Key_K,
        qt_core.Qt.KeyboardModifier.MetaModifier,
    )
    assert event_matches_shortcut(event, "command_field")


def test_unknown_shortcut_id_is_explicit() -> None:
    with pytest.raises(KeyError, match="Unknown SonoForge shortcut"):
        get_shortcut("not-a-shortcut")
