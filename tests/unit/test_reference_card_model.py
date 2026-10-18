"""UI-5 PR-1 — the domain behind the S2 card (spec UI §4.7, §8.5).

The card is only a view: the norm for the sex of the patient, the gradation of
the value and the segments of the scale are decided here, where no widget is
involved. The cases below are the acceptance scenarios UA-13 (LVEDD 48 mm in a
woman) and UA-14 (LVM 162 g by the linear method) and the gate of the package
— «gradations by sex», plus the honest answers when the handbook has nothing.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services import reference_card
from echo_personal_tool.domain.services.reference_card import (
    GradeCut,
    build_reference_card,
    clear_cache,
)


@pytest.fixture(autouse=True)
def _fresh_store():
    clear_cache()
    yield
    clear_cache()


def _grades(model) -> tuple[str, ...]:
    return tuple(cut.name for cut in model.cuts)


# ── UA-13: LVEDD 48 mm in a woman ──────────────────────────────────


def test_lvedd_48_female_is_normal() -> None:
    model = build_reference_card("lvedd", value=48.0, unit="мм", sex="F", language="ru")
    assert model.known
    assert model.grade is not None and model.grade.name == "Норма"
    assert (model.norm.low, model.norm.high) == (36.0, 51.0)
    assert model.norm_text == "36–51"
    assert model.sex_label == "женщины"
    assert model.unit == "мм"
    assert model.value_text == "48 мм"
    assert model.label == "КДР ЛЖ (LVEDD)"
    assert model.full_name
    assert model.source
    # The scale is the gradations of the handbook for the same sex.
    assert _grades(model) == ("Норма", "Лёгкое", "Умеренное", "Тяжёлое")
    assert [(cut.low, cut.high) for cut in model.cuts] == [
        (36.0, 51.0),
        (52.0, 56.0),
        (57.0, 61.0),
        (62.0, None),
    ]


@pytest.mark.parametrize(
    "value,expected",
    [
        (51.0, "Норма"),
        (52.0, "Лёгкое"),
        (57.0, "Умеренное"),
        (62.0, "Тяжёлое"),
        (400.0, "Тяжёлое"),
    ],
)
def test_gradations_follow_the_half_open_handbook_ranges(value, expected) -> None:
    model = build_reference_card("lvedd", value=value, unit="мм", sex="F", language="ru")
    assert model.grade is not None and model.grade.name == expected


def test_value_below_the_scale_has_no_grade() -> None:
    """«на границе нормы» is not a grade (UD-14): below the norm there is none."""
    model = build_reference_card("lvedd", value=30.0, unit="мм", sex="F", language="ru")
    assert model.grade is None
    assert model.has_norm  # the norm itself is still shown
    assert model.norm_text == "36–51"


# ── градации по полу (gate UI-5) ───────────────────────────────────


def test_the_same_number_is_a_different_grade_for_the_other_sex() -> None:
    female = build_reference_card("lvedd", value=57.0, unit="мм", sex="F", language="ru")
    male = build_reference_card("lvedd", value=57.0, unit="мм", sex="M", language="ru")
    assert female.grade.name == "Умеренное"
    assert male.grade.name == "Норма"
    assert (female.norm.low, female.norm.high) == (36.0, 51.0)
    assert (male.norm.low, male.norm.high) == (42.0, 59.0)
    assert male.sex_label == "мужчины"
    assert [(cut.low, cut.high) for cut in male.cuts] == [
        (42.0, 59.0),
        (60.0, 63.0),
        (64.0, 68.0),
        (69.0, None),
    ]


def test_unknown_sex_falls_back_to_the_male_ranges_without_a_sex_label() -> None:
    """DICOM allows an empty sex; the card must not invent a female range."""
    model = build_reference_card("lvedd", value=57.0, unit="мм", sex="", language="ru")
    assert (model.norm.low, model.norm.high) == (42.0, 59.0)
    assert model.sex_label == ""
    assert model.grade.name == "Норма"


# ── UA-14: the linear-method LVM of UI-5 PR-0 ──────────────────────


@pytest.mark.parametrize(
    "sex,value,expected",
    [
        ("F", 66.0, None),
        ("F", 67.0, "Норма"),
        ("F", 162.0, "Норма"),
        ("F", 163.0, "Лёгкое"),
        ("F", 211.0, "Тяжёлое"),
        ("M", 88.0, "Норма"),
        ("M", 224.0, "Норма"),
        ("M", 225.0, "Лёгкое"),
    ],
)
def test_lvm_uses_the_linear_method_ranges(sex, value, expected) -> None:
    model = build_reference_card("lvm", value=value, unit="г", sex=sex, language="ru")
    if expected is None:
        assert model.grade is None
    else:
        assert model.grade is not None and model.grade.name == expected
    # The method belongs to the norm: the card shows it, it is not a footnote.
    assert "М-режим" in model.method


def test_lvm_norm_text_is_the_linear_range() -> None:
    model = build_reference_card("lvm", value=162.0, unit="г", sex="F", language="ru")
    assert model.norm_text == "67–162"
    assert [(cut.low, cut.high) for cut in model.cuts] == [
        (67.0, 162.0),
        (163.0, 186.0),
        (187.0, 210.0),
        (211.0, None),
    ]


# ── units ──────────────────────────────────────────────────────────


def test_a_value_in_app_units_meets_the_range_of_the_handbook() -> None:
    """TR Vmax reads in cm/s, the handbook stores m/s (the report's table)."""
    model = build_reference_card("tr_vmax", value=280.0, unit="см/с", sex="F", language="ru")
    assert model.grade is not None and model.grade.name == "Норма"
    assert model.norm_text == "≤280"
    assert model.cuts[0].high == 280.0
    loud = build_reference_card("tr_vmax", value=310.0, unit="см/с", sex="F", language="ru")
    assert loud.grade is None  # the handbook has no gradation above the norm


def test_scale_override_when_the_value_already_reads_reference_units() -> None:
    """The norm text is the report's own formatting (same rounding everywhere)."""
    model = build_reference_card("tr_vmax", value=2.8, unit="м/с", sex="F", language="ru", scale=1.0)
    assert model.norm_text == "≤2.80"
    assert model.grade is not None and model.grade.name == "Норма"


# ── when the handbook has nothing ──────────────────────────────────


def test_unknown_parameter_says_so_instead_of_guessing() -> None:
    model = build_reference_card("no_such_parameter", value=3.0, unit="мм", sex="F", language="ru")
    assert not model.known
    assert not model.has_norm
    assert model.cuts == ()
    assert model.norm_text == ""
    assert model.grade is None
    # The row still knows the value it measured.
    assert model.value == 3.0
    assert model.value_text == "3 мм"


def test_empty_param_id_is_not_a_parameter() -> None:
    model = build_reference_card("", value=1.0, unit="мм", language="ru")
    assert not model.known
    assert model.label == ""


# ── value presentation ─────────────────────────────────────────────


def test_without_a_value_the_card_keeps_the_norm() -> None:
    model = build_reference_card("lvedd", value=None, unit="мм", sex="F", language="ru")
    assert model.grade is None
    assert model.value_text == ""
    assert model.has_norm
    assert model.norm_text == "36–51"


@pytest.mark.parametrize(
    "value,decimals,text",
    [
        (48.0, None, "48 мм"),
        (0.42, None, "0.42 мм"),
        (12.5, None, "12.5 мм"),
        (1234.0, None, "1234 мм"),
        (48.0, 1, "48.0 мм"),
    ],
)
def test_value_text_keeps_the_reading_short(value, decimals, text) -> None:
    model = build_reference_card("lvedd", value=value, unit="мм", sex="F", language="ru", decimals=decimals)
    assert model.value_text == text


def test_caller_labels_win_over_the_handbook() -> None:
    """UD-15: the row label comes from the catalog, not from the YAML."""
    model = build_reference_card(
        "lvedd",
        value=48.0,
        unit="мм",
        sex="F",
        language="ru",
        label="КДР ЛЖ",
        full_name="Конечно-диастолический размер",
    )
    assert model.label == "КДР ЛЖ"
    assert model.full_name == "Конечно-диастолический размер"


def test_caller_value_text_is_kept_verbatim() -> None:
    model = build_reference_card("lvedd", value=48.0, unit="мм", sex="F", value_text="48,0 мм")
    assert model.value_text == "48,0 мм"


# ── language ───────────────────────────────────────────────────────


def test_english_reads_the_english_handbook() -> None:
    model = build_reference_card("lvedd", value=65.0, unit="mm", sex="M", language="en")
    assert model.grade is not None and model.grade.name == "Moderate"
    assert model.sex_label == "men"
    assert model.norm_text == "42–59"
    assert _grades(model) == ("Normal", "Mild", "Moderate", "Severe")


def test_russian_is_the_fallback_language_of_the_module() -> None:
    """The tests run under the RU locale; the card follows the interface."""
    model = build_reference_card("lvedd", value=48.0, unit="мм", sex="F")
    assert model.language == "ru"
    assert model.grade.name == "Норма"


# ── how_to (UQ-12, filled in by UI-5 PR-3) ────────────────────────


def test_how_to_is_empty_until_the_schema_carries_the_field() -> None:
    model = build_reference_card("lvedd", value=48.0, unit="мм", sex="F", language="ru")
    assert model.how_to == ()


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ()),
        ("", ()),
        ("one step", ("one step",)),
        (["a", "b"], ("a", "b")),
        ({"ru": ["шаг"], "en": ["step"]}, ("шаг",)),
        ({"en": ["step"]}, ("step",)),
    ],
)
def test_how_to_reads_the_shapes_the_constructor_will_write(raw, expected) -> None:
    class _Param:
        how_to = raw

    assert reference_card._how_to(_Param(), "ru") == expected


# ── GradeCut ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "low,high,text",
    [
        (36.0, 51.0, "36–51"),
        (None, 2.8, "≤2.8"),
        (211.0, None, "≥211"),
        (None, None, ""),
    ],
)
def test_grade_cut_range_text(low, high, text) -> None:
    assert GradeCut(name="Норма", low=low, high=high).range_text() == text


@pytest.mark.parametrize(
    "low,high,value,inside",
    [
        (36.0, 51.0, 36.0, True),
        (36.0, 51.0, 51.0, True),
        (36.0, 51.0, 35.9, False),
        (None, 2.8, 2.8, True),
        (None, 2.8, 2.9, False),
        (211.0, None, 1000.0, True),
        (211.0, None, 210.0, False),
    ],
)
def test_grade_cut_bounds_are_closed(low, high, value, inside) -> None:
    assert GradeCut(name="g", low=low, high=high).contains(value) is inside
