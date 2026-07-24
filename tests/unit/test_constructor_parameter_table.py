"""Unit tests for constructor/editors/parameter_table_editor pure functions."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


class TestParseFloat:
    def test_valid_number(self) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import _parse_float

        assert _parse_float("42.5") == 42.5

    def test_integer_string(self) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import _parse_float

        assert _parse_float("100") == 100.0

    def test_invalid_string(self) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import _parse_float

        assert _parse_float("abc") is None

    def test_empty_string(self) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import _parse_float

        assert _parse_float("") is None

    def test_none_input(self) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import _parse_float

        assert _parse_float(None) is None


class TestParameterTableEditor:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        assert editor is not None

    def test_set_parameters(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        params = [
            ParameterModel(id="IVSd", name="IVSd", unit="mm"),
            ParameterModel(id="LVIDd", name="LVIDd", unit="mm"),
        ]
        editor.set_parameters(params)
        assert len(editor._parameters) == 2

    def test_filter(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        params = [
            ParameterModel(id="IVSd", name="IVSd", unit="mm"),
            ParameterModel(id="LVIDd", name="LVIDd", unit="mm"),
        ]
        editor.set_parameters(params)
        editor.filter("IVS")
        # Should not crash

    def test_clear_filter(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        editor.clear_filter()
        # Should not crash

    def test_delete_selected(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        editor.delete_selected()
        # Should not crash

    def test_get_field(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import (
            NormRangeModel,
            ParameterModel,
        )

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        param = ParameterModel(
            id="IVSd",
            name="IVSd",
            unit="mm",
            norm_male=NormRangeModel(low=6.0, high=11.0),
            pathology_desc="Increased in HCM",
            source="ASE Guidelines",
        )
        assert editor._get_field(param, "id") == "IVSd"
        assert editor._get_field(param, "name") == "IVSd"
        assert editor._get_field(param, "unit") == "mm"
        assert editor._get_field(param, "norm_male_low") == "6.0"
        assert editor._get_field(param, "norm_male_high") == "11.0"
        assert editor._get_field(param, "pathology_desc") == "Increased in HCM"
        assert editor._get_field(param, "source") == "ASE Guidelines"

    def test_get_field_empty_norm(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        param = ParameterModel(id="IVSd")
        assert editor._get_field(param, "norm_male_low") == ""
        assert editor._get_field(param, "norm_female_high") == ""

    def test_get_field_unknown(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        param = ParameterModel(id="IVSd")
        assert editor._get_field(param, "unknown_field") == ""

    def test_set_field(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        param = ParameterModel(id="old_id")
        editor._set_field(param, "id", "new_id")
        assert param.id == "new_id"

    def test_set_field_norm_male(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        param = ParameterModel(id="IVSd")
        editor._set_field(param, "norm_male_low", "6.0")
        assert param.norm_male.low == 6.0

    def test_set_field_norm_female(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        param = ParameterModel(id="IVSd")
        editor._set_field(param, "norm_female_high", "12.0")
        assert param.norm_female.high == 12.0

    def test_set_field_pathology_desc(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        param = ParameterModel(id="IVSd")
        editor._set_field(param, "pathology_desc", "Test description")
        assert param.pathology_desc == "Test description"

    def test_set_field_empty_string(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import ParameterModel

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        param = ParameterModel(id="IVSd", pathology_desc="test")
        editor._set_field(param, "pathology_desc", "")
        assert param.pathology_desc is None

    def test_table_style(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        style = editor._table_style()
        assert "QTableWidget" in style

    def test_set_pathology(self, qtbot) -> None:
        from echo_personal_tool.constructor.editors.parameter_table_editor import (
            ParameterTableEditor,
        )
        from echo_personal_tool.constructor.models.reference_model import (
            PathologyModel,
            ParameterModel,
        )

        editor = ParameterTableEditor()
        qtbot.addWidget(editor)
        patho = PathologyModel(
            name="HCM",
            parameters=[ParameterModel(id="p1", name="P1")],
        )
        editor.set_pathology(patho)
        assert editor._pathology is patho
