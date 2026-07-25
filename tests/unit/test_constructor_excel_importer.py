"""Tests for importers/excel_importer.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.constructor.importers.excel_importer import (
    _parse_num,
    import_excel_file,
)


class TestParseNum:
    def test_none(self) -> None:
        assert _parse_num(None) is None

    def test_int(self) -> None:
        assert _parse_num(42) == 42.0

    def test_float(self) -> None:
        assert _parse_num(3.14) == 3.14

    def test_string_number(self) -> None:
        assert _parse_num("7.5") == 7.5

    def test_string_non_number(self) -> None:
        assert _parse_num("abc") is None

    def test_string_empty(self) -> None:
        assert _parse_num("") is None

    def test_bool(self) -> None:
        # bool is subclass of int
        assert _parse_num(True) == 1.0

    def test_list(self) -> None:
        assert _parse_num([1, 2]) is None


def _make_mock_sheet(rows: list[list], max_row: int) -> MagicMock:
    """Create a mock worksheet with given rows."""
    ws = MagicMock()
    ws.max_row = max_row
    # ws[1] returns header row as mock cells
    header_cells = []
    for val in rows[0]:
        cell = MagicMock()
        cell.value = val
        header_cells.append(cell)
    ws.__getitem__ = MagicMock(side_effect=lambda idx: header_cells if idx == 1 else [])
    # iter_rows returns data rows
    ws.iter_rows = MagicMock(return_value=rows[1:])
    return ws


def _make_mock_workbook(sheets: dict[str, list[list]]) -> MagicMock:
    """Create a mock workbook with named sheets."""
    wb = MagicMock()
    wb.sheetnames = list(sheets.keys())

    def getitem(name):
        rows = sheets[name]
        return _make_mock_sheet(rows, max_row=len(rows))

    wb.__getitem__ = MagicMock(side_effect=getitem)
    return wb


class TestImportExcelFile:
    @patch("echo_personal_tool.constructor.importers.excel_importer.openpyxl")
    def test_basic_import(self, mock_openpyxl: MagicMock) -> None:
        sheets = {
            "LV": [
                ["name", "unit", "id", "norm_male_low", "norm_male_high"],
                ["E/A ratio", "", "ea_ratio", 0.8, 2.0],
                ["IVSd", "cm", "ivsd", 0.6, 1.1],
            ]
        }
        mock_wb = _make_mock_workbook(sheets)
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = import_excel_file(Path("test.xlsx"))

        assert "topics" in result
        assert len(result["topics"]) == 1
        topic = result["topics"][0]
        assert topic["name"] == "LV"
        assert topic["slug"] == "lv"
        assert len(topic["pathologies"]) == 1
        patho = topic["pathologies"][0]
        assert patho["slug"] == "lv_all"
        assert len(patho["parameters"]) == 2

    @patch("echo_personal_tool.constructor.importers.excel_importer.openpyxl")
    def test_import_with_female_norms(self, mock_openpyxl: MagicMock) -> None:
        sheets = {
            "Heart": [
                ["id", "name", "unit", "norm_female_low", "norm_female_high"],
                ["ef", "EF", "%", 55, 70],
            ]
        }
        mock_wb = _make_mock_workbook(sheets)
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = import_excel_file(Path("test.xlsx"))
        param = result["topics"][0]["pathologies"][0]["parameters"][0]
        assert param["norm_female"]["low"] == 55.0
        assert param["norm_female"]["high"] == 70.0

    @patch("echo_personal_tool.constructor.importers.excel_importer.openpyxl")
    def test_skip_empty_sheets(self, mock_openpyxl: MagicMock) -> None:
        """Sheets with < 2 rows are skipped."""
        sheets = {
            "Empty": [["Header"]],  # only 1 row
        }
        mock_wb = _make_mock_workbook(sheets)
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = import_excel_file(Path("test.xlsx"))
        assert result["topics"] == []

    @patch("echo_personal_tool.constructor.importers.excel_importer.openpyxl")
    def test_skip_rows_without_id(self, mock_openpyxl: MagicMock) -> None:
        sheets = {
            "Data": [
                ["id", "name"],
                ["valid_id", "Valid"],
                ["", "No ID"],
            ]
        }
        mock_wb = _make_mock_workbook(sheets)
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = import_excel_file(Path("test.xlsx"))
        params = result["topics"][0]["pathologies"][0]["parameters"]
        assert len(params) == 1
        assert params[0]["id"] == "valid_id"

    @patch("echo_personal_tool.constructor.importers.excel_importer.openpyxl")
    def test_source_field_imported(self, mock_openpyxl: MagicMock) -> None:
        sheets = {
            "Data": [
                ["id", "name", "source"],
                ["p1", "Param1", "ASE 2017"],
            ]
        }
        mock_wb = _make_mock_workbook(sheets)
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = import_excel_file(Path("test.xlsx"))
        param = result["topics"][0]["pathologies"][0]["parameters"][0]
        assert param["source"] == "ASE 2017"

    @patch("echo_personal_tool.constructor.importers.excel_importer.openpyxl")
    def test_pathology_desc_imported(self, mock_openpyxl: MagicMock) -> None:
        sheets = {
            "Data": [
                ["id", "name", "pathology_desc"],
                ["p1", "Param1", "Description text"],
            ]
        }
        mock_wb = _make_mock_workbook(sheets)
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = import_excel_file(Path("test.xlsx"))
        param = result["topics"][0]["pathologies"][0]["parameters"][0]
        assert param["pathology_desc"] == "Description text"

    @patch("echo_personal_tool.constructor.importers.excel_importer.openpyxl")
    def test_multiple_sheets(self, mock_openpyxl: MagicMock) -> None:
        sheets = {
            "LV": [["id", "name"], ["p1", "P1"]],
            "RV": [["id", "name"], ["p2", "P2"]],
        }
        mock_wb = _make_mock_workbook(sheets)
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = import_excel_file(Path("test.xlsx"))
        assert len(result["topics"]) == 2
        slugs = {t["slug"] for t in result["topics"]}
        assert slugs == {"lv", "rv"}
