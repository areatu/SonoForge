"""Unit tests for presentation/segment_quality_panel.py."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSegmentQualityPanelConstruction:
    def test_creates_table_with_correct_rows(self):
        from echo_personal_tool.domain.services.aha_segments import A4C_SEGMENT_NAMES
        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        assert panel._table.rowCount() == len(A4C_SEGMENT_NAMES)
        assert panel._table.columnCount() == 3

    def test_headers_are_set(self):
        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        headers = [panel._table.horizontalHeaderItem(i).text() for i in range(3)]
        assert headers == ["Segment", "Strain %", "Quality"]

    def test_initial_values_are_placeholder(self):
        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        for row in range(panel._table.rowCount()):
            strain = panel._table.item(row, 1)
            quality = panel._table.item(row, 2)
            assert strain is not None
            assert quality is not None
            assert strain.text() == "--"
            assert quality.text() == "--"


class TestUpdateResults:
    def test_update_sets_strain_and_quality(self):
        from echo_personal_tool.domain.services.aha_segments import A4C_SEGMENT_NAMES
        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        sorted_ids = sorted(A4C_SEGMENT_NAMES)
        strain_data = {sid: -15.0 + i for i, sid in enumerate(sorted_ids)}
        quality_data = {sid: 0.8 for sid in sorted_ids}

        panel.update_results(strain_data, quality_data)

        for row, sid in enumerate(sorted_ids):
            strain_item = panel._table.item(row, 1)
            quality_item = panel._table.item(row, 2)
            assert strain_item is not None
            assert quality_item is not None
            assert strain_item.text() != "--"
            assert quality_item.text() != "--"

    def test_missing_segments_show_placeholder(self):
        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        panel.update_results({}, {})
        for row in range(panel._table.rowCount()):
            assert panel._table.item(row, 1).text() == "--"
            assert panel._table.item(row, 2).text() == "--"

    def test_low_quality_highlights_row(self):
        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        # segment 1 = "Basal septal" is the first sorted entry
        panel.update_results({1: -20.0}, {1: 0.2})

        row = 0  # segment 1 is first sorted
        item = panel._table.item(row, 0)
        assert item is not None
        bg = item.background().color()
        fg = item.foreground().color()
        assert bg == panel._LOW_QUALITY_BG
        assert fg == panel._LOW_QUALITY_FG

    def test_good_quality_no_highlight(self):

        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        panel.update_results({1: -20.0}, {1: 0.8})

        row = 0
        item = panel._table.item(row, 0)
        assert item is not None
        # Should not be highlighted as low quality
        bg = item.background().color()
        assert bg != panel._LOW_QUALITY_BG

    def test_partial_data(self):
        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        # Only provide data for some segments
        panel.update_results({1: -15.0}, {1: 0.6})
        # Row 0 should have data, others should have placeholder
        assert panel._table.item(0, 1).text() != "--"
        # Check at least one other row still shows "--"
        other_rows = [r for r in range(panel._table.rowCount()) if r != 0]
        assert any(panel._table.item(r, 1).text() == "--" for r in other_rows)

    def test_strain_format(self):
        from echo_personal_tool.presentation.segment_quality_panel import SegmentQualityPanel

        panel = SegmentQualityPanel()
        panel.update_results({1: -12.345}, {1: 0.876})
        assert panel._table.item(0, 1).text() == "-12.3"
        assert panel._table.item(0, 2).text() == "0.88"
