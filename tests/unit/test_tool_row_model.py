"""Logic of the image tool row (UI-2 PR-3): the button list, its catalog link and keys."""

from __future__ import annotations

import json
from pathlib import Path

from echo_personal_tool.domain.measurement_catalog import CATALOG
from echo_personal_tool.keyboard_shortcuts import SHORTCUTS
from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.tool_buttons.model import (
    ROW_TOOLS,
    RowTool,
    row_tool,
    validate_row,
)

_LOCALES = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "infrastructure" / "locales"


def _keys(lang: str) -> frozenset[str]:
    return frozenset(json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8")))


_SHORTCUT_IDS = frozenset(spec.id for spec in SHORTCUTS)
_BOTH_LOCALES = _keys("ru") & _keys("en")


def test_row_order_matches_the_spec_groups() -> None:
    # Spec §4.2: linear L, area A, contour C, Doppler V, calibration K, auto-contour I.
    assert [tool.id for tool in ROW_TOOLS] == [
        "caliper",
        "area",
        "contour",
        "doppler",
        "calibration",
        "auto_contour",
    ]


def test_ids_are_unique() -> None:
    ids = [tool.id for tool in ROW_TOOLS]
    assert len(ids) == len(set(ids))


def test_row_is_consistent_with_catalog_shortcuts_and_locales() -> None:
    assert validate_row(catalog=dict(CATALOG), shortcut_ids=_SHORTCUT_IDS, locale_keys=_BOTH_LOCALES) == []


def test_catalog_backed_buttons_point_at_their_catalog_tool() -> None:
    backed = [tool for tool in ROW_TOOLS if tool.catalog_id]
    assert {tool.id for tool in backed} == {"caliper", "area"}
    for tool in backed:
        assert str(CATALOG[tool.catalog_id].payload.action) == str(tool.action)


def test_payload_is_the_action_requested_contract() -> None:
    caliper = row_tool("caliper")
    assert caliper is not None
    assert caliper.payload() == (MeasurementAction.CALIPER, "A4C", "ED", "")


def test_unknown_tool_id_gives_none() -> None:
    assert row_tool("missing") is None


def test_validate_row_reports_each_kind_of_problem() -> None:
    broken = (
        RowTool("x", MeasurementAction.CALIPER, "no.such.label", "no_such_shortcut", "tool.missing"),
        RowTool("x", MeasurementAction.CALIPER, "tool_row.caliper"),
        RowTool("y", MeasurementAction.AREA_COMPARE, "tool_row.area", "", "tool.caliper"),
    )
    problems = validate_row(broken, catalog=dict(CATALOG), shortcut_ids=_SHORTCUT_IDS, locale_keys=_BOTH_LOCALES)
    text = "\n".join(problems)
    assert "duplicate id: x" in text
    assert "no label no.such.label" in text
    assert "unknown shortcut no_such_shortcut" in text
    assert "unknown catalog tool tool.missing" in text
    assert "catalog action differs" in text


def test_manual_contour_is_a_measurement_action() -> None:
    assert str(MeasurementAction.MANUAL_CONTOUR) == "manual_contour"
