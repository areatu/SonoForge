"""«Откуда значение»: the lineage a report value carries (UI-4 PR-4, §4.6).

The cases pin the honesty rule of the card: a caliper or a vessel measurement
shows its clip, frame and stable id; a calculator output lists the inputs it
really consumed; everything else has **no** origin — and therefore prints
«происхождение не записано» instead of a guess.

Also pinned here is the PR-5 half of the same contract: explicit «не
оценивалось» marks become printed rows, while the screen-only «измерить»
markers never do.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.calculator_inputs import resolve_standalone_inputs
from echo_personal_tool.domain.calculators import evaluate
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import DopplerFlowResult, DopplerResults, MeasurementSnapshot
from echo_personal_tool.domain.models.result_provenance import Freshness
from echo_personal_tool.domain.models.value_origin import (
    KIND_CALCULATOR,
    KIND_MEASUREMENT,
    METHOD_CALCULATOR,
    METHOD_DOPPLER_CALIPER,
    METHOD_LINEAR_CALIPER,
    METHOD_NOT_EVALUATED,
    METHOD_PLANIMETER,
    METHOD_VESSEL,
    ClipSource,
    ValueOrigin,
    calculator_origin,
    unrecorded_origin,
)
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.services.report_builder import (
    GROUP_LEFT_VENTRICLE,
    GROUP_ORDER,
    ReportGroup,
    ReportValue,
    build_report_document,
    build_report_groups,
    with_extra_values,
)
from echo_personal_tool.domain.services.report_sections import build_report_sections, not_evaluated_values
from echo_personal_tool.infrastructure.i18n import set_language, tr

UID = "1.2.840.113619.2.55.3.1234567890.77"


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def _caliper(**kwargs) -> LinearMeasurement:
    defaults = dict(
        label="LVEDD",
        pixel_length=120.0,
        millimeter_length=48.0,
        frame_index=7,
        sop_instance_uid=UID,
        measurement_id="m-0001",
        revision=3,
    )
    defaults.update(kwargs)
    return LinearMeasurement(**defaults)


def _rows(snapshot: MeasurementSnapshot) -> list[ReportValue]:
    return [value for group in build_report_groups(snapshot) for value in group.values]


# ── direct measurements ────────────────────────────────────────────────


def test_a_linear_caliper_keeps_its_clip_frame_and_measurement_id() -> None:
    row = next(value for value in _rows(MeasurementSnapshot(linear_measurements=(_caliper(),))))
    origin = row.origin
    assert origin is not None
    assert origin.kind == KIND_MEASUREMENT
    assert origin.method_id == METHOD_LINEAR_CALIPER
    assert origin.measurement_id == "m-0001"
    assert origin.revision == 3
    assert origin.freshness == Freshness.FRESH.value
    assert origin.clips == (ClipSource(UID, 7),)
    assert origin.clips[0].frame_index == 7


def test_a_caliper_without_a_stored_clip_does_not_invent_one() -> None:
    """Older documents have an empty SOP UID: the card must stay honest."""
    measurement = _caliper(sop_instance_uid="", measurement_id="", frame_index=None)
    row = next(value for value in _rows(MeasurementSnapshot(linear_measurements=(measurement,))))
    origin = row.origin
    assert origin is not None
    assert origin.method_id == METHOD_LINEAR_CALIPER
    assert origin.clips == ()
    assert origin.sources == ()


def test_a_doppler_zone_caliper_is_labelled_by_its_method() -> None:
    measurement = _caliper(label="VTI", doppler=True, time_ms=120.0, velocity_cm_s=250.0)
    rows = [value for value in _rows(MeasurementSnapshot(linear_measurements=(measurement,))) if value.origin]
    assert rows, "the Δt/ΔV rows must carry the caliper origin"
    for row in rows:
        assert row.origin is not None
        assert row.origin.method_id == METHOD_DOPPLER_CALIPER
        assert row.origin.clips == (ClipSource(UID, 7),)


def test_a_vessel_measurement_carries_its_own_identity() -> None:
    vessel = VesselMeasurement(
        psv_cm_s=120.0,
        edv_cm_s=30.0,
        ri=0.75,
        sd=4.0,
        mv_approx=90.0,
        sop_instance_uid=UID,
        frame_index=2,
        measurement_id="v-9",
        revision=1,
    )
    rows = [
        value
        for value in _rows(MeasurementSnapshot(vessel_measurements=(vessel,)))
        if value.origin is not None
    ]
    assert rows
    for row in rows:
        assert row.origin is not None
        assert row.origin.method_id == METHOD_VESSEL
        assert row.origin.measurement_id == "v-9"
        assert row.origin.clips == (ClipSource(UID, 2),)


def test_a_planimeter_value_records_the_method_but_no_clip() -> None:
    from echo_personal_tool.domain.models.measurements import PlanimeterResult

    snapshot = MeasurementSnapshot(planimeter=(PlanimeterResult("LA area", "area", 24.0, "cm²"),))
    row = next(value for value in _rows(snapshot) if value.label == "LA area")
    assert row.origin is not None
    assert row.origin.method_id == METHOD_PLANIMETER
    assert row.origin.sources == ()
    assert row.origin.recorded is False


def test_a_derived_doppler_value_has_no_origin_rather_than_a_guess() -> None:
    """A computed Vmax aggregate records no input lineage in this release."""
    doppler = DopplerResults(flow_results=(DopplerFlowResult(site="TR", vmax_cm_s=280.0),))
    rows = _rows(MeasurementSnapshot(doppler=doppler))
    derived = next(value for value in rows if "TR" in value.label)
    assert derived.origin is None


# ── calculator outputs ─────────────────────────────────────────────────


def test_a_calculator_output_lists_the_inputs_it_consumed() -> None:
    values = {"lvot_d": 2.0, "lvot_vti": 20.0, "av_vti": 100.0, "hr": 70.0, "bsa": 1.9}
    snapshot = evaluate(resolve_standalone_inputs(values))
    rows = _rows(MeasurementSnapshot(calculations=snapshot))
    output = next(value for value in rows if value.label == "SV")
    origin = output.origin
    assert origin is not None
    assert origin.kind == KIND_CALCULATOR
    assert origin.method_id == METHOD_CALCULATOR
    identifiers = {item.id for item in origin.inputs}
    assert "LVOTd" in identifiers and "LVOT VTI" in identifiers
    assert all(item.source for item in origin.inputs)
    assert origin.freshness == Freshness.FRESH.value


def test_calculator_origin_without_inputs_is_unverified() -> None:
    origin = calculator_origin("cardiac_output", inputs=())
    assert origin.freshness == Freshness.UNVERIFIED.value
    assert origin.recorded is False


def test_unrecorded_origin_states_that_nothing_was_recorded() -> None:
    origin = unrecorded_origin("simpson")
    assert origin.freshness == Freshness.UNVERIFIED.value
    assert origin.recorded is False


# ── «не оценивалось» marks print (PR-5) ───────────────────────────────


def _sections():
    return build_report_sections(None, "en")


def test_only_marked_and_unfilled_items_become_rows() -> None:
    sections = _sections()
    item = next(item for section in sections for item in section.items if not item.filled)
    rows = not_evaluated_values(sections, frozenset({item.key}), value_text=tr("report.not_evaluated"))
    assert len(rows) == 1
    assert rows[0].label == item.label
    assert rows[0].value == tr("report.not_evaluated")
    assert rows[0].origin is not None
    assert rows[0].origin.method_id == METHOD_NOT_EVALUATED


def test_a_filled_item_is_not_printed_as_not_evaluated() -> None:
    """A measured value is never replaced by the mark, whatever was clicked."""
    from echo_personal_tool.domain.services.report_sections import (
        ReportSection,
        ReportSectionItem,
        SectionStatus,
    )

    item = ReportSectionItem(key="lv.lvedd", label="LVIDd", protocol_id="p", step_index=0, filled=True)
    section = ReportSection(id="lv", title="LV", status=SectionStatus.DONE, filled=1, total=1, items=(item,))
    assert not_evaluated_values((section,), frozenset({item.key}), value_text=tr("report.not_evaluated")) == ()


def test_marks_keep_the_anatomical_group_of_their_section() -> None:
    sections = _sections()
    lv_section = next(section for section in sections if section.id == "lv")
    item = lv_section.items[0]
    row = not_evaluated_values(sections, frozenset({item.key}), value_text=tr("report.not_evaluated"))[0]
    assert row.group == GROUP_LEFT_VENTRICLE


def test_marks_are_appended_to_the_document_after_its_own_values() -> None:
    base = build_report_document(MeasurementSnapshot(linear_measurements=(_caliper(),)), None)
    sections = _sections()
    item = next(item for section in sections for item in section.items)
    rows = not_evaluated_values(sections, frozenset({item.key}), value_text=tr("report.not_evaluated"))
    merged = with_extra_values(base, rows)
    merged_labels = [value.label for group in merged.groups for value in group.values]
    assert rows[0].label in merged_labels
    assert merged.patient == base.patient
    assert len(merged_labels) == sum(len(group.values) for group in base.groups) + len(rows)


def test_appending_keeps_group_order_and_creates_missing_groups() -> None:
    base = build_report_document(MeasurementSnapshot(), None)
    assert base.groups == ()
    rows = (
        ReportValue(label="Marked", value=tr("report.not_evaluated"), group="other"),
        ReportValue(label="Marked LV", value=tr("report.not_evaluated"), group=GROUP_LEFT_VENTRICLE),
    )
    merged = with_extra_values(base, rows)
    keys = [group.key for group in merged.groups]
    assert keys == sorted(keys, key=lambda key: GROUP_ORDER.index(key))


def test_appending_does_not_touch_notes_of_existing_groups() -> None:
    group = ReportGroup(title="Other", key="other", values=(ReportValue(label="A", value="1"),), notes=("note",))
    base = build_report_document(MeasurementSnapshot(), None)
    base = base.__class__(patient=base.patient, groups=(group,))
    row = ReportValue(label="Marked", value=tr("report.not_evaluated"), group="other")
    merged = with_extra_values(base, (row,))
    assert merged.groups[0].notes == ("note",)
    assert [value.label for value in merged.groups[0].values] == ["A", "Marked"]


def test_a_value_without_an_origin_is_not_pretended_to_have_one() -> None:
    plain = ReportValue(label="X", value="1")
    assert plain.origin is None
    explicit = ReportValue(label="Y", value="2", origin=ValueOrigin(kind=KIND_MEASUREMENT, method_id="m"))
    assert explicit.origin is not None
