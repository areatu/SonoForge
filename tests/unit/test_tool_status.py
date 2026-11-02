"""Статусы строк панели из проекции (TP-3 PR-2, спека TP §8.5).

Без Qt: провайдер — чистая функция от проекции и каталога.
"""

from __future__ import annotations

from echo_personal_tool.application.tool_status import ToolState, ToolStatusProvider
from echo_personal_tool.domain.protocols import ProjectionValue, StudyProjection


def _provider() -> ToolStatusProvider:
    return ToolStatusProvider()


def test_present_value_is_done_and_formatted_from_catalog() -> None:
    projection = StudyProjection(values={"lv.lvesd": ProjectionValue(value=52.0, origin="lv_linear")})
    status = _provider().status("lv.lvesd", projection)
    assert status.state is ToolState.DONE
    assert status.value == 52.0
    assert status.unit == "mm"
    assert status.text == "52"
    assert status.origin == "lv_linear"
    assert status.count == 1


def test_stale_value_marks_stale_state() -> None:
    projection = StudyProjection(values={"lv.lvesd": ProjectionValue(value=52.0, stale=True)})
    status = _provider().status("lv.lvesd", projection)
    assert status.state is ToolState.STALE
    assert status.value == 52.0


def test_absent_value_is_none_not_locked_without_unmet() -> None:
    status = _provider().status("lv.lvesd", StudyProjection())
    assert status.state is ToolState.NONE
    assert status.text == ""
    assert status.count == 0


def test_unmet_requirement_locks_row_with_reason() -> None:
    projection = StudyProjection(unmet=frozenset({"spatial_calibration"}))
    status = _provider().status("lv.lvesd", projection)
    assert status.state is ToolState.LOCKED
    assert status.reason == "req:spatial_calibration"


def test_warning_overrides_done_with_qc_code() -> None:
    projection = StudyProjection(values={"lv.lvesd": ProjectionValue(value=52.0)})
    status = _provider().status("lv.lvesd", projection, warnings={"lv.lvesd": "out_of_range"})
    assert status.state is ToolState.QC
    assert status.reason == "out_of_range"


def test_result_key_falls_back_to_tool_id() -> None:
    provider = _provider()
    assert provider.result_key("lv.linear_ed") == "lv.ivsd"


def test_linear_unit_cm_switches_decimals() -> None:
    provider = ToolStatusProvider(linear_unit="cm")
    text, unit = provider.format_value("lv.lvesd", 5.2)
    assert unit == "cm"
    assert text == "5.2"
