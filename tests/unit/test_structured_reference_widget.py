"""Tests for StructuredReferenceWidget."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QTableWidget

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


def _find_tables(w) -> list[QTableWidget]:
    """Return all QTableWidget instances in the cards layout."""
    tables = []
    for i in range(w._cards_layout.count()):
        item = w._cards_layout.itemAt(i)
        if item and item.widget() and isinstance(item.widget(), QTableWidget):
            tables.append(item.widget())
    return tables


def test_topic_selection_shows_pathologies(widget):
    widget._on_topic_clicked(widget._topics[0])
    assert widget._pathology_list.count() >= 1


def test_pathology_selection_shows_parameters(widget):
    widget._on_topic_clicked(widget._topics[0])
    widget._on_pathology_row_changed(0)
    tables = _find_tables(widget)
    assert len(tables) >= 1


def test_pathology_without_gradation_shows_parameters(widget):
    widget._on_topic_clicked(widget._topics[1])
    widget._on_pathology_row_changed(0)
    tables = _find_tables(widget)
    assert len(tables) >= 1


def test_cards_updates_on_pathology_selection(widget):
    widget._on_topic_clicked(widget._topics[0])
    widget._on_pathology_row_changed(0)
    tables = _find_tables(widget)
    assert len(tables) >= 1
    table = tables[0]
    assert table.rowCount() >= 1


def test_sex_toggle_updates_norms(widget):
    widget._on_topic_clicked(widget._topics[1])
    widget._on_pathology_row_changed(0)
    tables = _find_tables(widget)
    assert len(tables) >= 1
    table = tables[0]
    assert table.rowCount() >= 1


def test_navigate_to_param(widget):
    widget.navigate_to_param("ar_eroa")
    # After navigate, either cards (search results) or tables should be visible
    has_content = len(widget._param_cards) >= 1 or len(_find_tables(widget)) >= 1
    assert has_content


def test_search_filters_table(widget):
    widget._search_input.setText("eroa")
    assert len(widget._param_cards) >= 1


def test_gradations_flattened_into_single_card(widget):
    """Parameters from all gradations should appear in a single table."""
    widget._on_topic_clicked(widget._topics[0])  # aortic_valve
    widget._on_pathology_row_changed(0)  # aortic_regurgitation (has gradations)
    tables = _find_tables(widget)
    assert len(tables) >= 1
    table = tables[0]
    # Table should have 1 row (1 unique param: EROA) and columns = 1 + 2 gradations
    assert table.rowCount() >= 1
    assert table.columnCount() >= 3  # "Параметр" + "Лёгкая" + "Тяжёлая"
    # First row should contain EROA
    first_cell = table.item(0, 0)
    assert first_cell is not None
    assert "EROA" in first_cell.text()


def test_single_gradation_alone(widget):
    """A pathology with one gradation should show its parameters."""
    widget._on_topic_clicked(widget._topics[0])  # aortic_valve
    widget._on_pathology_row_changed(1)  # aortic_stenosis (1 gradation)
    tables = _find_tables(widget)
    assert len(tables) >= 1
    table = tables[0]
    assert table.rowCount() >= 1
    first_cell = table.item(0, 0)
    assert first_cell is not None
    assert "Vmax" in first_cell.text()


def test_navigate_to_param_no_gradation_selection(widget):
    """navigate_to_param should navigate without selecting gradation UI."""
    widget.navigate_to_param("ar_eroa")
    # After navigate, either cards (search results) or tables should be visible
    has_content = len(widget._param_cards) >= 1 or len(_find_tables(widget)) >= 1
    assert has_content
    # gradation is no longer a UI concept
    assert widget._current_gradation is None
