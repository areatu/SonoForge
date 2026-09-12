"""Unit tests for presentation/segment_quality_panel.py.

The panel lists the six segments of an apical four-chamber view. Those segments
carry real AHA ids (3/6/9/12/15/18), not the legacy 1..6 placeholders, so the
tests derive every id from ``A4C_SEGMENT_NAMES`` and never hardcode a row
number. One test pins that contract down explicitly: passing legacy ids must
leave the table empty rather than silently printing a value next to the wrong
segment name.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.aha_segments import A4C_SEGMENT_NAMES

pytestmark = pytest.mark.gui

# Rows follow the sorted AHA ids exactly as the panel builds them.
SEGMENT_IDS = sorted(A4C_SEGMENT_NAMES)
FIRST_ID = SEGMENT_IDS[0]
HEADERS = ["Segment", "Strain %", "Quality"]


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _panel():
    from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

    return SegmentQualityPanel()


class TestSegmentQualityPanelConstruction:
    def test_creates_table_with_correct_rows(self):
        panel = _panel()
        assert panel._table.rowCount() == len(A4C_SEGMENT_NAMES)
        assert panel._table.columnCount() == 3

    def test_headers_are_set(self):
        panel = _panel()
        headers = [panel._table.horizontalHeaderItem(i).text() for i in range(3)]
        assert headers == HEADERS

    def test_rows_follow_the_a4c_segment_ids(self):
        panel = _panel()
        labels = [panel._table.item(row, 0).text() for row in range(panel._table.rowCount())]
        assert labels == [A4C_SEGMENT_NAMES[segment_id] for segment_id in SEGMENT_IDS]

    def test_initial_values_are_placeholder(self):
        panel = _panel()
        for row in range(panel._table.rowCount()):
            strain = panel._table.item(row, 1)
            quality = panel._table.item(row, 2)
            assert strain is not None
            assert quality is not None
            assert strain.text() == "--"
            assert quality.text() == "--"


class TestUpdateResults:
    def test_update_sets_strain_and_quality(self):
        panel = _panel()
        strain_data = {sid: -15.0 + i for i, sid in enumerate(SEGMENT_IDS)}
        quality_data = {sid: 0.8 for sid in SEGMENT_IDS}

        panel.update_results(strain_data, quality_data)

        for row, sid in enumerate(SEGMENT_IDS):
            strain_item = panel._table.item(row, 1)
            quality_item = panel._table.item(row, 2)
            assert strain_item is not None
            assert quality_item is not None
            assert strain_item.text() == f"{strain_data[sid]:.1f}"
            assert quality_item.text() == "0.80"

    def test_missing_segments_show_placeholder(self):
        panel = _panel()
        panel.update_results({}, {})
        for row in range(panel._table.rowCount()):
            assert panel._table.item(row, 1).text() == "--"
            assert panel._table.item(row, 2).text() == "--"

    def test_legacy_segment_ids_are_ignored(self):
        """Ids 1..6 are the old placeholder scheme and must not hit any row."""
        panel = _panel()
        panel.update_results({1: -20.0, 2: -18.0}, {1: 0.9, 2: 0.3})
        for row in range(panel._table.rowCount()):
            assert panel._table.item(row, 1).text() == "--"
            assert panel._table.item(row, 2).text() == "--"

    def test_low_quality_highlights_row(self):
        panel = _panel()
        panel.update_results({FIRST_ID: -20.0}, {FIRST_ID: 0.2})

        row = SEGMENT_IDS.index(FIRST_ID)
        item = panel._table.item(row, 0)
        assert item is not None
        bg = item.background().color()
        fg = item.foreground().color()
        assert bg == panel._LOW_QUALITY_BG
        assert fg == panel._LOW_QUALITY_FG

    def test_good_quality_no_highlight(self):
        panel = _panel()
        panel.update_results({FIRST_ID: -20.0}, {FIRST_ID: 0.8})

        row = SEGMENT_IDS.index(FIRST_ID)
        item = panel._table.item(row, 0)
        assert item is not None
        # Should not be highlighted as low quality
        bg = item.background().color()
        assert bg != panel._LOW_QUALITY_BG

    def test_partial_data(self):
        panel = _panel()
        # Only provide data for the first segment
        panel.update_results({FIRST_ID: -15.0}, {FIRST_ID: 0.6})
        # Row 0 should have data, others should have placeholder
        assert panel._table.item(0, 1).text() != "--"
        # Check at least one other row still shows "--"
        other_rows = [r for r in range(panel._table.rowCount()) if r != 0]
        assert any(panel._table.item(r, 1).text() == "--" for r in other_rows)

    def test_strain_format(self):
        panel = _panel()
        panel.update_results({FIRST_ID: -12.345}, {FIRST_ID: 0.876})
        assert panel._table.item(0, 1).text() == "-12.3"
        assert panel._table.item(0, 2).text() == "0.88"
