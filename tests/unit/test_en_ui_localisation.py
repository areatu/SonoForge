"""The English interface must not show Russian captions (2026-10-30, item 4).

The report came with a screenshot of an English window whose protocol name
(«Симпсон Биплан»), step chips and a few overlay/status strings were still
Russian.  A locale-JSON audit alone cannot catch that: the wording is either
hard-coded in a widget or built from a template that keeps its own copy of the
language, so these tests read the **widget texts** of a real window instead.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.protocol_definitions import PROTOCOLS, SIMPSON_BIPLANE
from echo_personal_tool.domain.protocols import progress
from echo_personal_tool.domain.services.study_projection import build_study_projection
from echo_personal_tool.infrastructure.i18n import get_language, set_language, tr
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.ste_sensitivity_overlay import SteSensitivityOverlay
from echo_personal_tool.presentation.tool_panel_v2.protocol_card import ProtocolCard

pytestmark = pytest.mark.gui

_LOCALES = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "infrastructure" / "locales"
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")

#: The strings the card itself does not know how to look up (the panel pushes
#: them); the keys mirror ``ToolPanelV2._protocol_labels``.
_PROTOCOL_LABEL_KEYS = {
    "title": "panel.protocol_title",
    "none": "panel.protocol_none",
    "stop": "panel.protocol_stop",
    "derived": "panel.protocol_derived",
    "skipped": "panel.protocol_skipped",
    "stale": "panel.protocol_stale",
    "lock_mode": "panel.protocol_lock_mode",
    "lock_view": "panel.protocol_lock_view",
    "lock_req": "panel.protocol_lock_req",
    "auto_advance": "panel.auto_advance",
    "skip": "panel.protocol_skip",
}


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """A window persists its own preferences — keep them out of the real store."""
    return isolated_qsettings


@pytest.fixture(autouse=True)
def _restore_process_state():
    """The language and the application font are process-global: put them back.

    ``MainWindow`` applies the preferred UI font to ``QApplication``; a module
    that leaves it behind changes how every later test measures text (the
    panel's step tiles then fit two to a row where the suite expects one).  The
    stylesheet is left alone on purpose: clearing an app-wide sheet is a full
    repolish of every live widget, and other modules capture the previous sheet
    as their reference.
    """
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    font = QFont(app.font()) if app is not None else None
    yield
    if app is not None and font is not None:
        app.setFont(font)
    set_language("ru")


def _cyrillic_texts(root: QWidget) -> list[str]:
    """Visible widget texts of ``root`` that still carry Cyrillic."""
    offenders: list[str] = []
    for widget in root.findChildren(QWidget):
        if not widget.isVisibleTo(root):
            continue
        for attribute in ("text", "title", "placeholderText", "toolTip"):
            value = getattr(widget, attribute, None)
            value = value() if callable(value) else value
            if isinstance(value, str) and _CYRILLIC.search(value):
                offenders.append(f"{type(widget).__name__}.{widget.objectName()}.{attribute}={value}")
        for index in range(getattr(widget, "count", lambda: 0)()):
            item_text = getattr(widget, "itemText", lambda _i: None)(index)
            if isinstance(item_text, str) and _CYRILLIC.search(item_text):
                offenders.append(f"{type(widget).__name__}.{widget.objectName()}.item={item_text}")
    return offenders


def _protocol_progress():
    return progress(SIMPSON_BIPLANE, build_study_projection(MeasurementSnapshot()))


def _make_window(qtbot, language: str) -> MainWindow:
    preferences = UserPreferences(tool_panel_v2=True, language=language)
    window = MainWindow(controller=AppController(), user_preferences=preferences)
    qtbot.addWidget(window)
    window.resize(1366, 768)
    window.show()
    QTest.qWait(30)
    window._tool_panel.set_protocols(PROTOCOLS)
    window._tool_panel.set_protocol_progress(_protocol_progress())
    window._viewer._ste_sensitivity.show()
    QTest.qWait(30)
    return window


def test_english_locale_has_no_russian_values() -> None:
    """Examples inside the English catalog must be English too («кдр» was not)."""
    data = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))
    offenders = {key: value for key, value in data.items() if isinstance(value, str) and _CYRILLIC.search(value)}
    assert offenders == {}


def test_ste_overlay_reloads_its_captions(qapp) -> None:
    set_language("ru")
    overlay = SteSensitivityOverlay()
    assert _CYRILLIC.search(overlay._header.text())

    set_language("en")
    overlay.reload_text()

    assert overlay._header.text() == "Curve smoothing"
    texts = [
        overlay._header.text(),
        overlay._header.toolTip(),
        overlay._slider.toolTip(),
        overlay._reset_btn.toolTip(),
    ]
    assert [text for text in texts if _CYRILLIC.search(text)] == []
    overlay.deleteLater()


def test_protocol_card_repaints_after_language_switch(qtbot) -> None:
    set_language("ru")
    card = ProtocolCard("ru")
    qtbot.addWidget(card)
    card.set_protocols(PROTOCOLS)
    card.set_labels({name: tr(key) for name, key in _PROTOCOL_LABEL_KEYS.items()})
    card.set_progress(_protocol_progress())
    assert _CYRILLIC.search(card._derived.text())

    set_language("en")
    card.set_labels({name: tr(key) for name, key in _PROTOCOL_LABEL_KEYS.items()})
    card.set_language("en")

    assert card._derived.text().startswith("Derived")
    assert [tile.text() for tile in card._tile_buttons if _CYRILLIC.search(tile.text())] == []
    assert [
        card._combo.itemText(i) for i in range(card._combo.count()) if _CYRILLIC.search(card._combo.itemText(i))
    ] == []


def test_english_window_has_no_russian_captions(qtbot) -> None:
    """Nothing on screen of a window opened in English may be Russian."""
    window = _make_window(qtbot, "en")
    assert _cyrillic_texts(window) == []


def test_live_language_switch_repaints_every_caption(qtbot) -> None:
    """Switching RU → EN in the running window leaves no Russian caption."""
    window = _make_window(qtbot, "ru")
    assert _cyrillic_texts(window) != []  # the Russian chrome is on screen

    window._apply_user_preferences(replace(window._user_preferences, language="en"))
    QTest.qWait(50)

    assert get_language() == "en"
    assert _cyrillic_texts(window) == []


def test_language_switch_drops_the_window_built_in_the_old_language(qtbot) -> None:
    """The strain window names every panel at build time — like the handbook."""
    window = _make_window(qtbot, "ru")
    strain = window._ensure_strain_window()
    strain.show()
    QTest.qWait(30)

    window._apply_user_preferences(replace(window._user_preferences, language="en"))
    QTest.qWait(50)

    assert window._strain_window is None
    assert not strain.isVisible()
