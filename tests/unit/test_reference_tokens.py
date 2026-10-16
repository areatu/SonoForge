"""UI-0 PR-5 — the reference area on design tokens.

The reference widgets (``StructuredReferenceWidget``, the ASE dialog chrome and
the web reference) read the *roles* of the active theme through
``dark_theme.get_theme_tokens()`` instead of the former 28-key palette: every
``#hex`` left in a stylesheet below is a substituted token value, never a
hardcoded colour. Clinical gradation colours (``_GRADATION_COLORS*``) are data,
not theme — they stay pinned until the UI-5 card redesign.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gui

#: A colour literal inside a stylesheet.
_COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")

_SAMPLE_YAML = """
topics:
  - name: Aortic valve
    slug: aortic_valve
    pathologies:
      - name: Regurgitation (AR)
        slug: aortic_regurgitation
        gradations:
          - name: Mild
            parameters:
              - id: ar_eroa
                name: EROA
                unit: cm2
                norm_male: {low: null, high: 0.10}
                pathology_desc: "<0.10"
                source: "ASE 2017"
"""


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def apply_theme(monkeypatch):
    """Switch the theme mode of the facade; returns its tokens."""
    from echo_personal_tool.presentation import dark_theme

    def _apply(theme: str) -> dict[str, str]:
        monkeypatch.setattr(dark_theme, "_current_theme_mode", theme)
        return dark_theme.get_theme_tokens()

    return _apply


def _make_widget(qtbot, tmp_path):
    from echo_personal_tool.domain.services.reference_data_store import (
        ReferenceDataStore,
    )
    from echo_personal_tool.presentation.structured_reference_widget import (
        StructuredReferenceWidget,
    )

    path = tmp_path / "reference.yaml"
    path.write_text(_SAMPLE_YAML, encoding="utf-8")
    store = ReferenceDataStore(str(path)).load()
    widget = StructuredReferenceWidget(store)
    qtbot.addWidget(widget)
    card = _make_card(qtbot)
    return widget, card


def _make_card(qtbot):
    from echo_personal_tool.presentation.structured_reference_widget import (
        _ParameterCard,
    )

    card = _ParameterCard(SimpleNamespace(unit="mm", name="IVS", full_name="Septum", pathology_desc=""), "")
    qtbot.addWidget(card)
    return card


def _tree_stylesheets(widget) -> list[str]:
    from PySide6.QtWidgets import QWidget

    sheets = [widget.styleSheet()]
    sheets.extend(child.styleSheet() for child in widget.findChildren(QWidget))
    return [sheet for sheet in sheets if sheet]


def test_reference_stylesheets_paint_only_tokens(qtbot, tmp_path, apply_theme) -> None:
    """Every #hex in the reference stylesheets is a token of the active theme."""
    theme = apply_theme("graphite")
    widget, card = _make_widget(qtbot, tmp_path)

    allowed = set(theme.values())
    found: set[str] = set()
    for sheet in (*_tree_stylesheets(widget), *_tree_stylesheets(card)):
        for literal in _COLOUR_LITERAL.findall(sheet):
            assert literal in allowed, f"hardcoded colour in reference UI: {sheet!r}"
            found.add(literal)
    assert found, "expected the reference stylesheets to carry theme colours"


def test_reference_stylesheets_follow_a_theme_switch(qtbot, tmp_path, apply_theme) -> None:
    """The same widget paints the roles of each theme — no per-theme branch."""
    graphite = apply_theme("graphite")
    widget, _card = _make_widget(qtbot, tmp_path)
    graphite_sheets = " ".join(_tree_stylesheets(widget))

    dark = apply_theme("dark")
    widget2, _card2 = _make_widget(qtbot, tmp_path)
    dark_sheets = " ".join(_tree_stylesheets(widget2))

    assert graphite["surface.1"] in graphite_sheets
    assert dark["surface.1"] in dark_sheets
    assert graphite["surface.1"] != dark["surface.1"]
    assert graphite_sheets != dark_sheets


def test_parameter_card_selection_follows_accent_tab(qtbot, tmp_path, apply_theme) -> None:
    """The selected card border is the accent.tab role of the active theme."""
    from echo_personal_tool.presentation.structured_reference_widget import (
        _ParameterCard,
    )

    theme = apply_theme("graphite")
    _make_widget(qtbot, tmp_path)
    assert theme["accent.tab"] in _ParameterCard._STYLE_SELECTED
    assert not _COLOUR_LITERAL.search(
        _ParameterCard._STYLE_SELECTED.replace(theme["accent.tab"], "").replace(theme["surface.2"], "")
    )


def test_reference_glyph_takes_the_text_token(qtbot, apply_theme) -> None:
    """The ASE dialog repaints its close glyph with text.1 (mirrors the shell)."""
    from PySide6.QtGui import QColor

    from echo_personal_tool.presentation.ase_reference_dialog import _load_icon

    theme = apply_theme("graphite")
    pixmap = _load_icon("close")
    assert not pixmap.isNull()
    image = pixmap.toImage()
    colours = {
        (image.pixelColor(x, y).red(), image.pixelColor(x, y).green(), image.pixelColor(x, y).blue())
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() >= 200
    }
    expected = QColor(theme["text.1"])
    assert (expected.red(), expected.green(), expected.blue()) in colours


def test_ase_dialog_stylesheets_paint_only_tokens(qtbot, apply_theme) -> None:
    """The ASE dialog chrome paints token roles; close hover is danger.solid."""
    from echo_personal_tool.presentation.ase_reference_dialog import (
        AseReferenceDialog,
    )

    theme = apply_theme("graphite")
    dialog = AseReferenceDialog()
    qtbot.addWidget(dialog)

    allowed = set(theme.values())
    found: set[str] = set()
    for sheet in _tree_stylesheets(dialog):
        for literal in _COLOUR_LITERAL.findall(sheet):
            assert literal in allowed, f"hardcoded colour in ASE dialog: {sheet!r}"
            found.add(literal)
    assert theme["state.danger.solid"] in found


def test_gradation_clinical_colours_stay_pinned() -> None:
    """UI-0 PR-5 moves the chrome, not the clinical grades (UI-5 owns those)."""
    from echo_personal_tool.presentation.structured_reference_widget import (
        _GRADATION_COLORS,
        _GRADATION_COLORS_LIGHT,
    )

    assert _GRADATION_COLORS["норм"] == ("#1E22C55E", "#22c55e")
    assert _GRADATION_COLORS["severe"] == ("#1EEF4444", "#ef4444")
    assert _GRADATION_COLORS_LIGHT["норм"] == ("#2D22C55E", "#16a34a")
    assert _GRADATION_COLORS_LIGHT["severe"] == ("#2DEF4444", "#dc2626")
