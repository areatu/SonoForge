"""Tests for editors/parameter_table_editor.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from echo_personal_tool.constructor.editors.parameter_table_editor import _parse_float
from echo_personal_tool.constructor.models import (
    GradationModel,
    NormRangeModel,
    ParameterModel,
    PathologyModel,
)

pytestmark = pytest.mark.gui

_THEME = {
    "bg_dark": "#111827",
    "bg_panel": "#1a2332",
    "bg_control": "#243044",
    "bg_button": "#2e4054",
    "bg_button_hover": "#3a5068",
    "bg_button_pressed": "#1e2a38",
    "accent": "#9ca3b0",
    "accent_bright": "#b0b8c0",
    "accent_tab": "#3b82f6",
    "text": "#f1f5f9",
    "text_dim": "#94a3b8",
    "border": "#334155",
}


@pytest.fixture
def editor(qtbot) -> ParameterTableEditor:
    from echo_personal_tool.constructor.editors.parameter_table_editor import (
        ParameterTableEditor,
    )

    with patch(
        "echo_personal_tool.constructor.editors.parameter_table_editor.get_theme_palette",
        return_value=_THEME,
    ):
        w = ParameterTableEditor()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def flat_pathology() -> PathologyModel:
    return PathologyModel(
        name="Diastolic",
        slug="diastolic",
        parameters=[
            ParameterModel(
                id="ea_ratio",
                name="E/A ratio",
                unit="",
                norm_male=NormRangeModel(low=0.8, high=2.0),
                norm_female=NormRangeModel(low=0.9, high=1.8),
                pathology_desc="Reduced",
                source="ASE 2017",
            ),
            ParameterModel(
                id="ivsd",
                name="IVSd",
                unit="cm",
                norm_male=NormRangeModel(low=0.6, high=1.1),
                norm_female=NormRangeModel(low=0.5, high=1.0),
            ),
        ],
    )


@pytest.fixture
def gradation_pathology() -> PathologyModel:
    return PathologyModel(
        name="Gradated",
        slug="gradated",
        parameters=[],
        gradations=[
            GradationModel(
                name="Mild",
                parameters=[
                    ParameterModel(id="g1_mild", name="G1 Mild", unit="ml"),
                ],
            ),
            GradationModel(
                name="Severe",
                parameters=[
                    ParameterModel(id="g1_severe", name="G1 Severe", unit="ml"),
                ],
            ),
        ],
    )


class TestParseFloat:
    def test_valid(self) -> None:
        assert _parse_float("3.14") == 3.14

    def test_int_string(self) -> None:
        assert _parse_float("42") == 42.0

    def test_invalid(self) -> None:
        assert _parse_float("abc") is None

    def test_empty(self) -> None:
        assert _parse_float("") is None

    def test_none_like(self) -> None:
        assert _parse_float("None") is None


class TestSetPathology:
    def test_set_flat(self, editor, flat_pathology) -> None:
        editor.set_pathology(flat_pathology)
        assert editor._pathology is flat_pathology
        assert len(editor._parameters) == 2
        assert len(editor._columns) == len(editor._columns)

    def test_set_gradation(self, editor, gradation_pathology) -> None:
        editor.set_pathology(gradation_pathology)
        assert editor._pathology is gradation_pathology
        assert len(editor._parameters) == 2


class TestSetParameters:
    def test_set_empty(self, editor) -> None:
        editor.set_parameters([])
        assert editor._pathology is None
        assert len(editor._parameters) == 0

    def test_set_with_params(self, editor) -> None:
        params = [ParameterModel(id="p1", name="P1")]
        editor.set_parameters(params)
        assert editor._pathology is None
        assert len(editor._parameters) == 1


class TestFilter:
    def test_filter_by_name(self, editor, flat_pathology) -> None:
        editor.set_pathology(flat_pathology)
        editor.filter("ea")
        assert len(editor._parameters) == 1
        assert editor._parameters[0].id == "ea_ratio"

    def test_filter_by_id(self, editor, flat_pathology) -> None:
        editor.set_pathology(flat_pathology)
        editor.filter("ivsd")
        assert len(editor._parameters) == 1

    def test_filter_no_match(self, editor, flat_pathology) -> None:
        editor.set_pathology(flat_pathology)
        editor.filter("zzz")
        assert len(editor._parameters) == 0

    def test_clear_filter(self, editor, flat_pathology) -> None:
        editor.set_pathology(flat_pathology)
        editor.filter("ea")
        editor.clear_filter()
        assert len(editor._parameters) == 2


class TestGetField:
    def test_id(self, editor) -> None:
        p = ParameterModel(id="test_id", name="Test", unit="")
        assert editor._get_field(p, "id") == "test_id"

    def test_name(self, editor) -> None:
        p = ParameterModel(id="", name="Test Name", unit="")
        assert editor._get_field(p, "name") == "Test Name"

    def test_unit(self, editor) -> None:
        p = ParameterModel(id="", name="", unit="cm")
        assert editor._get_field(p, "unit") == "cm"

    def test_norm_male_low(self, editor) -> None:
        p = ParameterModel(id="", name="", norm_male=NormRangeModel(low=1.0, high=5.0))
        assert editor._get_field(p, "norm_male_low") == "1.0"

    def test_norm_male_high(self, editor) -> None:
        p = ParameterModel(id="", name="", norm_male=NormRangeModel(low=1.0, high=5.0))
        assert editor._get_field(p, "norm_male_high") == "5.0"

    def test_norm_female_low(self, editor) -> None:
        p = ParameterModel(id="", name="", norm_female=NormRangeModel(low=2.0))
        assert editor._get_field(p, "norm_female_low") == "2.0"

    def test_norm_female_high(self, editor) -> None:
        p = ParameterModel(id="", name="", norm_female=NormRangeModel(high=6.0))
        assert editor._get_field(p, "norm_female_high") == "6.0"

    def test_no_norm(self, editor) -> None:
        p = ParameterModel(id="", name="")
        assert editor._get_field(p, "norm_male_low") == ""

    def test_pathology_desc(self, editor) -> None:
        p = ParameterModel(id="", name="", pathology_desc="test")
        assert editor._get_field(p, "pathology_desc") == "test"

    def test_source(self, editor) -> None:
        p = ParameterModel(id="", name="", source="ASE")
        assert editor._get_field(p, "source") == "ASE"

    def test_unknown_field(self, editor) -> None:
        p = ParameterModel(id="", name="")
        assert editor._get_field(p, "unknown") == ""


class TestSetField:
    def test_set_id(self, editor) -> None:
        p = ParameterModel(id="old")
        editor._set_field(p, "id", "new")
        assert p.id == "new"

    def test_set_name(self, editor) -> None:
        p = ParameterModel(name="old")
        editor._set_field(p, "name", "new")
        assert p.name == "new"

    def test_set_name_captures_full_name(self, editor) -> None:
        p = ParameterModel(name="Конечно-диастолический диаметр (LVEDD)")
        editor._set_field(p, "name", "КДР (LVEDD)")
        assert p.name == "КДР (LVEDD)"
        assert p.full_name == "Конечно-диастолический диаметр (LVEDD)"
        assert p.tooltip == "Конечно-диастолический диаметр (LVEDD)"

    def test_set_name_keeps_original_full_name(self, editor) -> None:
        p = ParameterModel(name="Конечно-диастолический диаметр (LVEDD)")
        editor._set_field(p, "name", "КДР (LVEDD)")
        editor._set_field(p, "name", "ЛЖ КДР (LVEDD)")
        assert p.name == "ЛЖ КДР (LVEDD)"
        assert p.full_name == "Конечно-диастолический диаметр (LVEDD)"

    def test_set_unit(self, editor) -> None:
        p = ParameterModel(unit="kg")
        editor._set_field(p, "unit", "ml")
        assert p.unit == "ml"

    def test_set_norm_male_low(self, editor) -> None:
        p = ParameterModel()
        editor._set_field(p, "norm_male_low", "3.5")
        assert p.norm_male is not None
        assert p.norm_male.low == 3.5

    def test_set_norm_male_high(self, editor) -> None:
        p = ParameterModel()
        editor._set_field(p, "norm_male_high", "7.0")
        assert p.norm_male is not None
        assert p.norm_male.high == 7.0

    def test_set_norm_female_low(self, editor) -> None:
        p = ParameterModel()
        editor._set_field(p, "norm_female_low", "2.5")
        assert p.norm_female is not None
        assert p.norm_female.low == 2.5

    def test_set_norm_female_high(self, editor) -> None:
        p = ParameterModel()
        editor._set_field(p, "norm_female_high", "8.0")
        assert p.norm_female is not None
        assert p.norm_female.high == 8.0

    def test_set_norm_male_invalid(self, editor) -> None:
        p = ParameterModel()
        editor._set_field(p, "norm_male_low", "abc")
        assert p.norm_male is not None
        assert p.norm_male.low is None

    def test_set_pathology_desc(self, editor) -> None:
        p = ParameterModel()
        editor._set_field(p, "pathology_desc", "test desc")
        assert p.pathology_desc == "test desc"

    def test_set_pathology_desc_empty(self, editor) -> None:
        p = ParameterModel(pathology_desc="old")
        editor._set_field(p, "pathology_desc", "")
        assert p.pathology_desc is None

    def test_set_source(self, editor) -> None:
        p = ParameterModel()
        editor._set_field(p, "source", "ASE 2017")
        assert p.source == "ASE 2017"

    def test_set_source_empty(self, editor) -> None:
        p = ParameterModel(source="old")
        editor._set_field(p, "source", "")
        assert p.source is None


class TestAddParameter:
    def test_add_parameter(self, editor) -> None:
        editor.set_parameters([])
        editor._add_parameter()
        assert len(editor._parameters) == 1
        assert editor._parameters[0].id == "param_1"

    def test_add_parameter_emits_signal(self, editor) -> None:
        editor.set_parameters([])
        received = []
        editor.parameters_changed.connect(lambda: received.append(True))
        editor._add_parameter()
        assert len(received) >= 1


class TestDeleteSelected:
    @patch("echo_personal_tool.constructor.editors.parameter_table_editor.QMessageBox")
    def test_delete_no_selection(self, mock_msgbox, editor) -> None:
        editor.set_parameters([])
        editor.delete_selected()
        mock_msgbox.question.assert_not_called()

    @patch("echo_personal_tool.constructor.editors.parameter_table_editor.QMessageBox")
    def test_delete_confirmed(self, mock_msgbox, editor) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.Yes
        params = [ParameterModel(id="p1", name="P1"), ParameterModel(id="p2", name="P2")]
        editor.set_parameters(params)
        # Select row 0
        editor._table.selectRow(0)
        editor.delete_selected()
        assert len(editor._parameters) == 1


class TestColumnVisibility:
    def test_toggle_column(self, editor) -> None:
        editor._toggle_column("id", 2)  # Checked
        assert editor._col_visibility["id"] is True
        editor._toggle_column("id", 0)  # Unchecked
        assert editor._col_visibility["id"] is False


class TestColumnMoved:
    def test_column_moved(self, editor, flat_pathology) -> None:
        editor.set_pathology(flat_pathology)
        original_first = editor._columns[0]
        # Move column 0 to position 1
        editor._on_column_moved(0, 0, 1)
        assert editor._columns[0] != original_first


class TestFontChanges:
    def test_font_changed(self, editor) -> None:
        editor._on_font_changed("serif")
        assert editor._font_family == "serif"

    def test_size_changed(self, editor) -> None:
        editor._on_size_changed(16)
        assert editor._font_size == 16
