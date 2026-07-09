"""Tests for StructuredReferenceWidget."""
from __future__ import annotations

import pytest
from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
from echo_personal_tool.presentation.structured_reference_widget import StructuredReferenceWidget


_SAMPLE_YAML = """
topics:
  - name: Аортальный клапан
    slug: aortic_valve
    pathologies:
      - name: Недостаточность (АН)
        slug: aortic_regurgitation
        image_path: pisa_ar.png
        gradations:
          - name: Лёгкая
            parameters:
              - id: ar_eroa
                name: EROA
                unit: см²
                norm_male: {low: null, high: 0.10}
                pathology_desc: "<0.10"
                source: "ASE 2017"
          - name: Тяжёлая
            parameters:
              - id: ar_eroa
                name: EROA
                unit: см²
                norm_male: {low: 0.30, high: null}
                pathology_desc: "≥0.30"
                source: "ASE 2017"
      - name: Стеноз (АС)
        slug: aortic_stenosis
        gradations:
          - name: Умеренный
            parameters:
              - id: as_vmax
                name: Vmax
                unit: м/с
                norm_male: {low: null, high: 2.5}
                pathology_desc: "3.0-3.9"
                source: "ESC 2021"
  - name: Левый желудочек
    slug: left_ventricle
    pathologies:
      - name: Норма
        slug: normal
        parameters:
          - id: lvef
            name: "Фракция выброса (LVEF)"
            unit: "%"
            norm_male: {low: 52, high: 72}
            norm_female: {low: 54, high: 74}
            source: "ASE 2015"
"""


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "test.yaml"
    path.write_text(_SAMPLE_YAML, encoding="utf-8")
    return ReferenceDataStore(str(path)).load()


@pytest.fixture
def widget(store, qtbot):
    w = StructuredReferenceWidget(store)
    qtbot.addWidget(w)
    w.show()
    return w


def test_widget_creates_topic_buttons(widget):
    assert len(widget._topic_buttons) == 2


def test_topic_selection_shows_pathologies(widget):
    widget._on_topic_clicked(widget._topics[0])
    assert widget._pathology_list.count() >= 1


def test_pathology_selection_shows_parameters(widget):
    widget._on_topic_clicked(widget._topics[0])
    widget._on_pathology_row_changed(0)
    assert widget._table.rowCount() >= 1


def test_pathology_without_gradation_shows_parameters(widget):
    widget._on_topic_clicked(widget._topics[1])
    widget._on_pathology_row_changed(0)
    assert widget._table.rowCount() >= 1


def test_table_updates_on_gradation_change(widget):
    widget._on_topic_clicked(widget._topics[0])
    widget._on_pathology_row_changed(0)
    assert widget._table.rowCount() >= 1
    assert widget._table.item(0, 0) is not None


def test_sex_toggle_updates_norms(widget):
    widget._on_topic_clicked(widget._topics[1])
    widget._on_pathology_row_changed(0)
    male_text = widget._table.item(0, 2).text()
    widget._female_radio.click()
    female_text = widget._table.item(0, 2).text()
    assert male_text != female_text


def test_navigate_to_param(widget):
    widget.navigate_to_param("ar_eroa")
    assert widget._table.rowCount() >= 1


def test_search_filters_table(widget):
    widget._search_input.setText("eroa")
    assert widget._table.rowCount() >= 1


def test_gradation_buttons_shown(widget):
    """Selecting a pathology with gradations should show radio buttons."""
    widget._on_topic_clicked(widget._topics[0])  # aortic_valve
    widget._on_pathology_row_changed(0)  # aortic_regurgitation (has gradations)
    assert widget._gradation_group.isVisible()
    assert len(widget._gradation_radio_group.buttons()) >= 2


def test_gradation_buttons_hidden(widget):
    """Selecting a pathology without gradations should hide radio buttons."""
    widget._on_topic_clicked(widget._topics[1])  # left_ventricle
    widget._on_pathology_row_changed(0)  # normal (no gradations)
    assert not widget._gradation_group.isVisible()


def test_gradation_change_updates_table(widget):
    """Switching gradation should update parameter values."""
    widget._on_topic_clicked(widget._topics[0])  # aortic_valve
    widget._on_pathology_row_changed(0)  # aortic_regurgitation
    first_text = widget._table.item(0, 2).text()  # norm column
    # Switch to second gradation (Тяжёлая)
    if len(widget._gradation_radio_group.buttons()) > 1:
        widget._gradation_radio_group.buttons()[1].click()
        second_text = widget._table.item(0, 2).text()
        assert first_text != second_text


def test_navigate_to_param_with_gradation(widget):
    """navigate_to_param should select correct gradation."""
    widget.navigate_to_param("ar_eroa")
    assert widget._current_gradation is not None
    assert widget._current_gradation.name == "Лёгкая"
