"""UI-5 PR-1 — the S2 card itself (spec UI §4.7, UD-06, UD-14).

The gate of the package says it plainly: **the card holds no image**. The
schemes of the handbook stay in the reference window (S1) because their text is
too small for a popup, so the test walks the widget tree of a filled card and
fails on anything that carries a pixmap or an icon.

The rest of the file is the acceptance scenario UA-13 (LVEDD 48 mm in a
woman): the grade, the norm for the sex, the scale, the source and
«Открыть в справочнике», which hands the parameter id to the host.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QLabel, QWidget

pytestmark = pytest.mark.gui

_COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@pytest.fixture()
def apply_theme(monkeypatch):
    """Switch the theme of the facade; returns its tokens."""
    from echo_personal_tool.presentation import dark_theme

    def _apply(theme: str) -> dict[str, str]:
        monkeypatch.setattr(dark_theme, "_current_theme_mode", theme)
        return dark_theme.get_theme_tokens()

    return _apply


@pytest.fixture()
def card_factory(qtbot, apply_theme):
    """A card of one parameter, built by the domain and shown offscreen."""
    from echo_personal_tool.domain.services import reference_card as domain
    from echo_personal_tool.presentation.reference_card import ReferenceCard

    apply_theme("graphite")

    def _make(**kwargs):
        domain.clear_cache()
        model = domain.build_reference_card(**kwargs)
        card = ReferenceCard()
        qtbot.addWidget(card)
        card.set_model(model)
        return card, model

    yield _make
    domain.clear_cache()


def _image_widgets(root):
    """Widgets of the tree that carry a raster image (UD-06 forbids them)."""
    offenders: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        pixmap = getattr(widget, "pixmap", None)
        if callable(pixmap):
            found = pixmap()
            if found is not None and not found.isNull():
                offenders.append(f"{type(widget).__name__}.pixmap")
        icon = getattr(widget, "icon", None)
        if callable(icon):
            found = icon()
            if found is not None and not found.isNull():
                offenders.append(f"{type(widget).__name__}.icon")
        document = getattr(widget, "document", None)
        if callable(document):
            found = document()
            if found is not None and "<img" in found.toHtml().lower():
                offenders.append(f"{type(widget).__name__}.document")
    return offenders


def _tree_stylesheets(root):
    """Stylesheets of the whole widget tree."""
    return [sheet for widget in [root, *root.findChildren(QWidget)] if (sheet := widget.styleSheet())]


# ── the gate: no image in the card ─────────────────────────────────


def test_no_image_in_the_widget_tree(card_factory) -> None:
    card, _model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    assert _image_widgets(card) == []


def test_no_image_with_a_grade_a_scale_and_a_source(card_factory) -> None:
    """The fullest card: a chip, four segments and the source line."""
    card, model = card_factory(param_id="lvm", value=162.0, unit="г", sex="F", language="ru")
    assert model.grade is not None
    assert len(model.cuts) == 4
    assert _image_widgets(card) == []
    for sheet in _tree_stylesheets(card):
        assert "url(" not in sheet
        assert ".png" not in sheet and ".svg" not in sheet


def test_the_module_loads_no_image_asset() -> None:
    """Not only the tree: the module itself never reaches for a picture."""
    source = (
        Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "presentation" / "reference_card.py"
    ).read_text(encoding="utf-8")
    for needle in ("QPixmap", "QImage", "QSvgRenderer", "image_path", ".svg", ".png", "QMovie"):
        assert needle not in source, f"the card must not load images: {needle}"


# ── UA-13: LVEDD 48 mm in a woman ──────────────────────────────────


def test_ua13_card_of_lvedd_48_female(card_factory) -> None:
    card, model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    assert card._title.text() == model.label
    assert card._value.text() == "48 мм"
    assert card._chip.text() == "Норма"
    assert card._chip.isVisibleTo(card)
    assert card._norm.text() == "женщины · 36–51 мм"
    assert card._source.isVisibleTo(card)
    assert "ASE/EACVI" in card._source.text()
    # The scale and its legend: one segment per gradation, with the thresholds.
    assert card._scale.isVisibleTo(card)
    legend = [label.text() for label in card._legend.findChildren(QLabel)]
    assert "Норма 36–51" in legend
    assert "Тяжёлое ≥62" in legend


def test_the_scale_marks_the_value(card_factory) -> None:
    """The marker is placed inside the segment the value falls into."""
    card, _model = card_factory(param_id="lvedd", value=54.0, unit="мм", sex="F", language="ru")
    segments = card._scale._segments()
    assert len(segments) == 4
    marker = card._scale._marker_x(segments)
    second_x, second_width, _colour, active = segments[1]
    assert second_x <= marker <= second_x + second_width
    assert active  # «Лёгкое» is the grade of 54 mm


def test_a_value_off_the_scale_puts_the_marker_on_the_edge(card_factory) -> None:
    card, model = card_factory(param_id="lvedd", value=30.0, unit="мм", sex="F", language="ru")
    assert model.grade is None
    assert card._scale._marker_x(card._scale._segments()) == 0.0
    assert not card._chip.isVisibleTo(card)


def test_the_card_renders(card_factory) -> None:
    """Painting the scale must not crash (the marker and the bar are drawn)."""
    card, _model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    card.adjustSize()
    pixmap = card.grab()
    assert pixmap.width() > 0 and pixmap.height() > 0


# ── «Открыть в справочнике» ────────────────────────────────────────


def test_open_in_reference_emits_the_parameter_id(card_factory, qtbot) -> None:
    card, _model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    with qtbot.waitSignal(card.reference_requested, timeout=1000) as blocker:
        card._open.click()
    assert blocker.args == ["lvedd"]


def test_open_is_hidden_for_an_unknown_parameter(card_factory) -> None:
    card, _model = card_factory(param_id="no_such_parameter", value=3.0, unit="мм", language="ru")
    assert not card._open.isVisibleTo(card)


# ── when the handbook has nothing ──────────────────────────────────


def test_without_a_norm_the_card_says_so(card_factory) -> None:
    from echo_personal_tool.infrastructure.i18n import tr

    card, _model = card_factory(param_id="no_such_parameter", value=3.0, unit="мм", language="ru")
    assert card._norm.text() == tr("ref_card.no_norm")
    assert not card._chip.isVisibleTo(card)
    assert not card._source.isVisibleTo(card)


def test_without_a_value_the_value_says_so(card_factory) -> None:
    from echo_personal_tool.infrastructure.i18n import tr

    card, _model = card_factory(param_id="lvedd", value=None, unit="мм", sex="F", language="ru")
    assert card._value.text() == tr("ref_card.not_measured")
    assert card._norm.text() == "женщины · 36–51 мм"


def test_how_to_is_hidden_until_the_handbook_has_the_text(card_factory, monkeypatch) -> None:
    """UQ-12: the block appears with the field (UI-5 PR-3), not before."""
    from echo_personal_tool.domain.services import reference_card as domain
    from echo_personal_tool.domain.services.reference_card import ReferenceCardModel

    card, model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    assert not card._how_to.isVisibleTo(card)

    with_text = ReferenceCardModel(
        **{**model.__dict__, "how_to": ("В М-режиме, перпендикулярно длинной оси", "Конец диастолы")}
    )
    card.set_model(with_text)
    assert card._how_to.isVisibleTo(card)
    assert "перпендикулярно" in card._how_to.text()
    domain.clear_cache()


def test_an_unknown_grade_name_paints_the_neutral_segment(qtbot, apply_theme) -> None:
    """A gradation the palette does not know keeps the card readable."""
    from echo_personal_tool.domain.services.reference_card import GradeCut
    from echo_personal_tool.presentation.dark_theme import get_theme_tokens
    from echo_personal_tool.presentation.reference_card import _GradeScale

    apply_theme("graphite")
    scale = _GradeScale()
    qtbot.addWidget(scale)
    scale.set_model((GradeCut(name="Что-то ещё", low=1.0, high=2.0),), None, None)
    segments = scale._segments()
    assert len(segments) == 1
    assert segments[0][2].name() == get_theme_tokens()["line.2"]  # neutral, not a grade


# ── tokens, themes, placement ──────────────────────────────────────


def test_stylesheets_paint_only_tokens(card_factory, apply_theme) -> None:
    """UD-09: the card takes every colour from the active theme."""
    from echo_personal_tool.presentation.reference_grades import GRADE_COLORS, GRADE_COLORS_LIGHT

    theme = apply_theme("graphite")
    card, _model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    allowed = set(theme.values())
    # The gradations are data of the handbook, not roles of the theme (UI-5).
    for palette in (GRADE_COLORS, GRADE_COLORS_LIGHT):
        for fill, text in palette.values():
            allowed.update({fill.lower(), text.lower()})
    for sheet in _tree_stylesheets(card):
        for literal in _COLOUR_LITERAL.findall(sheet):
            assert literal.lower() in allowed, f"a colour outside the theme and the palette: {literal}"


def test_a_theme_switch_repaints_the_card(card_factory, apply_theme) -> None:
    """Both halves of the look follow the theme: labels *and* the painted body."""
    card, _model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    navy = apply_theme("navy")
    card.apply_theme()
    sheets = " ".join(_tree_stylesheets(card))
    assert navy["text.1"] in sheets
    # The body is drawn by paintEvent (no QSS background: a styled top-level
    # window gets a second, differently coloured frame from the platform), so
    # the check is the rendered pixel inside the left margin.
    card.adjustSize()
    image = card.grab().toImage()
    pixel = image.pixelColor(6, image.height() // 2).name().lower()
    assert pixel == navy["surface.2"].lower()


def test_a_repaint_leaves_one_legend_row_per_grade(card_factory, apply_theme) -> None:
    """The legend is rebuilt on every theme switch — the old rows must go.

    A row that is only ``deleteLater``-ed stays a child of the card until the
    event loop runs, and a child is painted: the ghost legend used to sit on
    top of the card at (0, 0).
    """
    card, model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    apply_theme("navy")
    card.apply_theme()
    rows = [label for label in card.findChildren(QLabel) if label.objectName() == "gradeLegendText"]
    assert len(rows) == len(model.cuts)
    assert [row.text() for row in rows] == [f"{cut.name} {cut.range_text()}".strip() for cut in model.cuts]


def test_escape_closes_the_card(card_factory, qtbot) -> None:
    card, _model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    card.show()
    assert card.isVisible()
    qtbot.keyClick(card, Qt.Key_Escape)
    assert not card.isVisible()


def test_popup_keeps_the_card_inside_the_screen(card_factory) -> None:
    card, _model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    card.adjustSize()
    screen = card.screen().availableGeometry()
    # Far outside on the right and at the bottom: the card must stay visible.
    card.popup_at(QPoint(screen.right() + 500, screen.bottom() + 500))
    assert card.x() + card.width() <= screen.right()
    assert card.y() + card.height() <= screen.bottom()


def test_popup_does_not_cover_the_row_it_belongs_to(card_factory) -> None:
    """The card goes beside the row, never on top of the tool it explains."""
    card, _model = card_factory(param_id="lvedd", value=48.0, unit="мм", sex="F", language="ru")
    card.adjustSize()
    row = QRect(100, 300, 200, 24)
    card.popup_at(QPoint(100, 290), anchor=row)  # the pointer sits on the row
    rect = QRect(card.x(), card.y(), card.width(), card.height())
    assert not rect.intersects(row)

    # The tool panel lives at the right edge of the window: there the card must
    # open to the left of the row, over the image area, not off the panel.
    screen = card.screen().availableGeometry() if card.screen() is not None else QRect(0, 0, 1280, 800)
    edge_row = QRect(screen.right() - 280, screen.top() + 100, 260, 24)
    card.popup_at(edge_row.topLeft(), anchor=edge_row)
    edge_rect = QRect(card.x(), card.y(), card.width(), card.height())
    assert not edge_rect.intersects(edge_row)
    assert edge_rect.right() < edge_row.left()


def test_show_reference_card_reuses_one_card_per_host(qtbot, apply_theme) -> None:
    from echo_personal_tool.domain.services import reference_card as domain
    from echo_personal_tool.presentation.reference_card import show_reference_card

    apply_theme("graphite")
    host = QWidget()
    qtbot.addWidget(host)
    first = show_reference_card(
        domain.build_reference_card("lvedd", value=48.0, unit="мм", sex="F", language="ru"),
        QPoint(10, 10),
        parent=host,
    )
    second = show_reference_card(
        domain.build_reference_card("lvm", value=162.0, unit="г", sex="F", language="ru"),
        QPoint(10, 10),
        parent=host,
    )
    assert first is second
    assert second.model.param_id == "lvm"
    domain.clear_cache()
