"""Tests for editors/metadata_editor.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from echo_personal_tool.constructor.models import NormRangeModel, ParameterModel

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
def editor(qtbot) -> MetadataEditor:
    from echo_personal_tool.constructor.editors.metadata_editor import MetadataEditor

    with patch(
        "echo_personal_tool.constructor.editors.metadata_editor.get_theme_palette",
        return_value=_THEME,
    ):
        w = MetadataEditor()
    qtbot.addWidget(w)
    return w


class TestSetParameter:
    def test_set_parameter_both_sex(self, editor) -> None:
        param = ParameterModel(
            id="p1",
            name="P1",
            norm_male=NormRangeModel(low=0.8, high=2.0),
            norm_female=NormRangeModel(low=0.8, high=2.0),
        )
        editor.set_parameter(param)
        assert editor._parameter is param
        assert editor._sex_both.isChecked()

    def test_set_parameter_male_only(self, editor) -> None:
        param = ParameterModel(
            id="p1",
            name="P1",
            norm_male=NormRangeModel(low=1.0),
            norm_female=None,
        )
        editor.set_parameter(param)
        assert editor._sex_male.isChecked()

    def test_set_parameter_female_only(self, editor) -> None:
        param = ParameterModel(
            id="p1",
            name="P1",
            norm_male=None,
            norm_female=NormRangeModel(low=1.0),
        )
        editor.set_parameter(param)
        assert editor._sex_female.isChecked()

    def test_set_parameter_no_norms(self, editor) -> None:
        param = ParameterModel(id="p1", name="P1")
        editor.set_parameter(param)
        assert editor._sex_both.isChecked()

    def test_set_parameter_source(self, editor) -> None:
        param = ParameterModel(id="p1", name="P1", source="ASE 2017")
        editor.set_parameter(param)
        assert editor._source_edit.text() == "ASE 2017"

    def test_set_parameter_description(self, editor) -> None:
        param = ParameterModel(id="p1", name="P1", pathology_desc="Desc text")
        editor.set_parameter(param)
        assert editor._desc_edit.text() == "Desc text"

    def test_set_parameter_none_source(self, editor) -> None:
        param = ParameterModel(id="p1", name="P1", source=None)
        editor.set_parameter(param)
        assert editor._source_edit.text() == ""


class TestOnChanged:
    def test_on_changed_no_parameter(self, editor) -> None:
        # Should not crash when no parameter is set
        editor._on_changed()

    def test_on_changed_updates_source(self, editor) -> None:
        param = ParameterModel(id="p1", name="P1")
        editor.set_parameter(param)
        # Unblock signals for test
        editor._block_signals(False)
        editor._source_edit.setText("New Source")
        assert param.source == "New Source"

    def test_on_changed_updates_description(self, editor) -> None:
        param = ParameterModel(id="p1", name="P1")
        editor.set_parameter(param)
        editor._block_signals(False)
        editor._desc_edit.setText("New Description")
        assert param.pathology_desc == "New Description"

    def test_on_changed_empty_source_sets_none(self, editor) -> None:
        param = ParameterModel(id="p1", name="P1", source="old")
        editor.set_parameter(param)
        editor._block_signals(False)
        editor._source_edit.setText("")
        assert param.source is None

    def test_on_changed_emits_signal(self, editor) -> None:
        param = ParameterModel(id="p1", name="P1")
        editor.set_parameter(param)
        editor._block_signals(False)
        received = []
        editor.metadata_changed.connect(lambda: received.append(True))
        editor._source_edit.setText("test")
        assert len(received) >= 1


class TestBlockSignals:
    def test_block_signals(self, editor) -> None:
        editor._block_signals(True)
        assert editor._sex_male.signalsBlocked()
        assert editor._source_edit.signalsBlocked()
        editor._block_signals(False)
        assert not editor._sex_male.signalsBlocked()
        assert not editor._source_edit.signalsBlocked()
