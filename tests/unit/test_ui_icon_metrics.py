"""Icon and button metrics of the shell: one glyph source, explicit sizes.

Why this test exists (Win11/macOS/Linux comparison, 2026-10-23):

* every glyph of the shell was loaded with ``QPixmap.loadFromData(svg)``, which
  needs Qt's ``qsvg`` **image-format plugin**.  A frozen build without that
  plugin draws no glyph at all — the caption buttons and the system-bar actions
  came out empty on Windows while the same build looked correct on Linux.  The
  single loader :mod:`presentation.icon_loader` rasterises through
  ``QSvgRenderer`` (a Python module, no plugin file), and this test keeps the
  old raster path from coming back;
* the tool row is a strip of icons (§4.1), yet five of its buttons carried no
  glyph and, because the fixed 38 px cell elided their caption, showed «…» —
  four identical tiles in the row.  Every tool button must now name a glyph that
  exists in ``resources/icons``, and an icon-less one must fall back to a letter
  instead of an ellipsis;
* the glyph edge is explicit (:data:`ICON_EDGE_ROW` / :data:`ICON_EDGE_RAIL`)
  and the stylesheet no longer reserves 12 px of padding inside the fixed cell,
  otherwise the pictogram sits small and off-centre.

The module is Qt-free apart from the stylesheet builder, which is a pure string
function of the tokens.
"""

from __future__ import annotations

from pathlib import Path

import echo_personal_tool
from echo_personal_tool.presentation.tool_buttons import buttons as tool_buttons
from echo_personal_tool.presentation.tool_buttons.metrics import (
    BUTTON_EDGE_MIN,
    ICON_CELL_MARGIN,
    ICON_EDGE_RAIL,
    ICON_EDGE_ROW,
    initial_for_caption,
)

_PACKAGE = Path(echo_personal_tool.__file__).resolve().parent
_ICONS = _PACKAGE / "resources" / "icons"


def test_every_tool_button_names_an_existing_glyph():
    missing = [spec.id for spec in tool_buttons.TOOL_BUTTONS if not spec.icon]
    assert missing == [], f"tool buttons without a glyph fall back to «…» in the row: {missing}"

    absent = [spec.icon for spec in tool_buttons.TOOL_BUTTONS if not (_ICONS / f"{spec.icon}.svg").is_file()]
    assert absent == [], f"glyph files missing from resources/icons: {absent}"


def test_icon_edges_fit_the_fixed_cell():
    assert 0 < ICON_EDGE_ROW <= BUTTON_EDGE_MIN
    assert 0 < ICON_EDGE_RAIL <= BUTTON_EDGE_MIN
    # The glyph plus its margins has to stay inside the 38 px cell of the row.
    assert ICON_EDGE_ROW + 2 * ICON_CELL_MARGIN <= BUTTON_EDGE_MIN - 6


def test_stylesheet_keeps_the_tool_row_cell_padding_free():
    from echo_personal_tool.presentation.theme.qss import build_clinical_stylesheet

    sheet = build_clinical_stylesheet(13, theme="dark")
    assert 'QToolButton[view="row"], QToolButton[view="rail"] {' in sheet
    block = sheet.split('QToolButton[view="row"], QToolButton[view="rail"] {', 1)[1].split("}", 1)[0]
    assert "padding: 0;" in block
    assert "min-height: 0;" in block


def test_the_action_glyph_leaves_a_gap_before_its_caption():
    """Qt draws a button icon 4 px from the caption with no stylesheet knob.

    The row of shell actions is a pictogram with a word beside it (design A1);
    starting the word on top of the glyph is what read as «подпись сдвинута».
    The gap therefore lives in the icon box: the button asks for
    ``edge + gap`` and the loader paints the glyph into the left square.
    """
    source = (_PACKAGE / "presentation" / "system_bar.py").read_text(encoding="utf-8")
    assert "ACTION_ICON_GAP = " in source
    assert "gap_ratio=ACTION_ICON_GAP / ACTION_ICON_EDGE" in source
    assert "setIconSize(QSize(ACTION_ICON_EDGE + ACTION_ICON_GAP, ACTION_ICON_EDGE))" in source

    loader = (_PACKAGE / "presentation" / "icon_loader.py").read_text(encoding="utf-8")
    assert "gap_ratio: float = 0.0" in loader
    assert "QRectF(0, 0, ICON_RENDER_EDGE, ICON_RENDER_EDGE)" in loader


def test_stylesheet_aligns_the_pacs_toolbutton_with_its_neighbours():
    from echo_personal_tool.presentation.theme.qss import build_clinical_stylesheet

    sheet = build_clinical_stylesheet(13, theme="dark")
    # QToolButton must share the metrics of the QPushButtons of the system bar…
    assert "#systemBar QPushButton, #systemBar QToolButton {" in sheet
    # …and the InstantPopup menu must not draw the stray style indicator.
    assert "#systemBar QToolButton::menu-indicator {" in sheet
    indicator = sheet.split("#systemBar QToolButton::menu-indicator {", 1)[1].split("}", 1)[0]
    assert "image: none;" in indicator
    assert "width: 0;" in indicator


def test_the_action_row_is_flat_with_group_separators():
    """Actions read as text + glyph on the bar, not as a line of boxed chips.

    The design (A1) shows «PACS | Сравнить | Презентация» as flat items with
    hairlines between the groups and exactly one accented control at the end.
    The build painted every action as a filled, bordered rectangle, which made
    the row loud and hid the active work mode.
    """
    from echo_personal_tool.presentation.theme.qss import build_clinical_stylesheet

    sheet = build_clinical_stylesheet(13, theme="dark")
    bar = sheet.split("#systemBar QPushButton, #systemBar QToolButton {", 1)[1].split("}", 1)[0]
    assert "background: transparent;" in bar
    assert "border: 1px solid transparent;" in bar
    assert "#systemBarSeparator {" in sheet


def test_shell_modules_do_not_rasterise_svg_through_the_image_plugin():
    """``QPixmap.loadFromData(svg)`` is the platform-dependent path this change removed.

    Only the modules that own a glyph loader are listed: a deliberate runtime
    fallback (the structured reference widget keeps one) is not a shell loader.
    """
    modules = [
        _PACKAGE / "presentation" / "system_bar.py",
        _PACKAGE / "presentation" / "tab_bar.py",
        _PACKAGE / "presentation" / "window_chrome" / "title_bar.py",
        _PACKAGE / "presentation" / "tool_buttons" / "base.py",
        _PACKAGE / "presentation" / "ase_reference_dialog.py",
        _PACKAGE / "constructor" / "constructor_dialog.py",
    ]
    offenders = [path.name for path in modules if "loadFromData(" in _code_only(path.read_text(encoding="utf-8"))]
    assert offenders == [], f"still loading SVG through the image-format plugin: {offenders}"


def _code_only(source: str) -> str:
    """Drop docstrings and comments so prose about the old loader is not a match."""
    import io
    import tokenize

    pieces = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.STRING, tokenize.COMMENT):
                continue
            pieces.append(token.string)
    except (tokenize.TokenError, IndentationError):  # pragma: no cover - defensive
        return source
    return " ".join(pieces)


def test_iconless_button_falls_back_to_a_letter_not_an_ellipsis():
    assert initial_for_caption("Площадь") == "П"
    assert initial_for_caption("  manual contour") == "M"
    assert initial_for_caption("—") == "?"


def test_the_widget_style_is_pinned_to_fusion():
    """The stylesheet is written for Fusion; the platform style must not decide metrics.

    Without this, the same QSS produced visibly different buttons, paddings and
    glyph alignment on Windows (Windows style) than on Linux (Fusion) — the
    «визуал кнопок и выравнивания отличаются» of the platform comparison.
    """
    from echo_personal_tool.presentation.theme import widget_style

    assert widget_style.WIDGET_STYLE == "Fusion"

    calls = []

    class _App:
        def setStyle(self, style):  # noqa: N802 - Qt API name
            calls.append(style)

    created = []

    def _create(name):
        created.append(name)
        return object()

    widget_style.apply_widget_style(_App(), create=_create)
    assert created == ["Fusion"]
    assert len(calls) == 1

    class _MissingApp(_App):
        pass

    assert widget_style.apply_widget_style(_MissingApp(), create=lambda _name: None) is None
