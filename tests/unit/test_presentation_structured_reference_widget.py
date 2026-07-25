"""Unit tests for presentation/structured_reference_widget.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestParsePathologyRows:
    def test_gradation_format(self):
        from echo_personal_tool.presentation.structured_reference_widget import _ParameterCard

        desc = "Лёгкая: <0.20 / Умеренная: 0.20-0.39 / Тяжёлая: ≥0.40"
        rows = _ParameterCard._parse_pathology_rows(desc, "мм")
        assert len(rows) == 3
        assert rows[0][0] == "Лёгкая"
        assert "<0.20" in rows[0][1]

    def test_simple_format(self):
        from echo_personal_tool.presentation.structured_reference_widget import _ParameterCard

        desc = ">115 (м) / >95 (ж) — гипертрофия"
        rows = _ParameterCard._parse_pathology_rows(desc, "г/м²")
        assert len(rows) == 1
        assert ">115" in rows[0][0]

    def test_no_unit(self):
        from echo_personal_tool.presentation.structured_reference_widget import _ParameterCard

        desc = "Лёгкая: 1 / Средняя: 2"
        rows = _ParameterCard._parse_pathology_rows(desc, "")
        assert len(rows) == 2

    def test_single_gradation_format(self):
        from echo_personal_tool.presentation.structured_reference_widget import _ParameterCard

        desc = "Тяжёлая: >40"
        rows = _ParameterCard._parse_pathology_rows(desc, "мм")
        # Only 1 gradation, falls back to simple format
        assert len(rows) == 1


class TestImageContainer:
    def test_size_hints(self):
        from echo_personal_tool.presentation.structured_reference_widget import _ImageContainer

        w = _ImageContainer()
        assert w.sizeHint().width() == 200
        assert w.sizeHint().height() == 200
        assert w.minimumSizeHint().width() == 100
        w.close()


class TestParameterCard:
    def test_init(self):
        from echo_personal_tool.domain.services.reference_data_store import ParameterRef
        from echo_personal_tool.presentation.structured_reference_widget import _ParameterCard

        param = MagicMock(spec=ParameterRef)
        param.name = "LVIDd"
        param.unit = "мм"
        param.pathology_desc = None
        card = _ParameterCard(param, "45-55")
        assert card is not None
        card.close()

    def test_selectable(self):
        from echo_personal_tool.domain.services.reference_data_store import ParameterRef
        from echo_personal_tool.presentation.structured_reference_widget import _ParameterCard

        param = MagicMock(spec=ParameterRef)
        param.name = "IVSd"
        param.unit = "мм"
        param.pathology_desc = None
        card = _ParameterCard(param, "")
        card.set_selected(True)
        assert card._selected is True
        card.set_selected(False)
        assert card._selected is False
        card.close()


class TestStructuredReferenceWidget:
    @pytest.fixture()
    def widget(self):
        from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
        from echo_personal_tool.presentation.structured_reference_widget import StructuredReferenceWidget

        store = ReferenceDataStore()
        store.load()
        w = StructuredReferenceWidget(store)
        yield w
        w.close()

    def test_creates(self, widget):
        assert widget is not None

    def test_topics_loaded(self, widget):
        assert len(widget._topics) > 0

    def test_initial_state(self, widget):
        assert isinstance(widget._topics, list)
        assert len(widget._topics) > 0
        # Default topic is auto-selected in _build_ui
        assert widget._current_topic is not None
        assert widget._sex_male is True

    def test_on_topic_clicked(self, widget):
        if widget._topics:
            widget._on_topic_clicked(widget._topics[0])
            assert widget._current_topic is not None

    def test_toggle_sex(self, widget):
        widget._sex_male = True
        widget._on_sex_changed(0)
        assert widget._sex_male is True
        widget._on_sex_changed(1)
        assert widget._sex_male is False

    def test_reload(self, widget):
        widget.reload()
        assert len(widget._topics) > 0

    def test_set_maximized_mode(self, widget):
        widget.set_maximized_mode(True)
        widget.set_maximized_mode(False)


class TestTopicLabels:
    def test_all_expected_topics_have_labels(self):
        from echo_personal_tool.presentation.structured_reference_widget import _TOPIC_LABELS

        expected = {
            "left_ventricle",
            "left_atrium",
            "right_ventricle",
            "right_atrium",
            "mitral_valve",
            "aortic_valve",
            "tricuspid_valve",
            "pulmonary_valve",
            "aorta",
            "prosthetic_valves",
            "other",
        }
        assert expected.issubset(set(_TOPIC_LABELS.keys()))

    def test_all_expected_topics_have_icons(self):
        from echo_personal_tool.presentation.structured_reference_widget import _TOPIC_ICONS

        expected = {
            "left_ventricle",
            "left_atrium",
            "right_ventricle",
            "right_atrium",
            "mitral_valve",
            "aortic_valve",
            "tricuspid_valve",
            "pulmonary_valve",
            "aorta",
            "prosthetic_valves",
            "other",
        }
        assert expected.issubset(set(_TOPIC_ICONS.keys()))

    def test_all_expected_topics_have_full_names(self):
        from echo_personal_tool.presentation.structured_reference_widget import _TOPIC_FULL_NAMES

        expected = {"left_ventricle", "left_atrium", "right_ventricle", "right_atrium"}
        assert expected.issubset(set(_TOPIC_FULL_NAMES.keys()))
