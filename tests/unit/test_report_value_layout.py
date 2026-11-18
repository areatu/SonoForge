"""A saved layout addresses parameters, not captions, methods or row positions."""

from dataclasses import replace

import pytest

from echo_personal_tool.domain.models.measurements import (
    DopplerFlowResult,
    DopplerResults,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
    TeichholzResult,
)
from echo_personal_tool.domain.services.report_builder import build_report_document
from echo_personal_tool.domain.services.report_value_layout import DEFAULT_REPORT_VALUE_EXCLUDED, merge_report_order
from echo_personal_tool.infrastructure.i18n import set_language


@pytest.mark.parametrize("language", ["ru", "en"])
def test_default_exclusions_do_not_depend_on_language_or_the_other_stroke_volume(language):
    set_language(language)
    snapshot = MeasurementSnapshot(
        lvef=LvefResult(a4c=LvViewMetrics(length_ed_mm=87, edv_ml=120), sv_ml=70),
        teichholz=TeichholzResult(135, 60, 55.5, 75),
        doppler=DopplerResults(flow_results=(DopplerFlowResult("LVOT", 90, vti_cm=18),)),
        spacing_calibrated=True,
    )

    def keys(source, **kwargs):
        return [v.key for g in build_report_document(source, **kwargs).groups for v in g.values]

    full = keys(snapshot)
    hidden = keys(snapshot, hidden_keys=DEFAULT_REPORT_VALUE_EXCLUDED)
    assert set(full) - set(hidden) == {"lv:lv.length_a4c:0", "lv:lv.sv_teich:0", "av:lvot.vmax:0"}
    assert "lv:lv.sv:0" in hidden and "av:lvot.vti:0" in hidden
    only_teich = replace(snapshot, lvef=None)
    assert "lv:lv.sv_teich:0" not in keys(only_teich, hidden_keys=DEFAULT_REPORT_VALUE_EXCLUDED)
    assert "lv:lv.sv_teich:0" in keys(only_teich, hidden_keys=())


def test_order_is_local_to_each_group_and_ignores_absent_keys():
    snapshot = MeasurementSnapshot(
        lvef=LvefResult(a4c=LvViewMetrics(edv_ml=120, esv_ml=60), lvef_percent=50),
        doppler=DopplerResults(e_cm_s=80, a_cm_s=55),
    )
    before = build_report_document(snapshot)
    lv, mv = before.groups
    rank = [mv.values[-1].key, lv.values[1].key, "absent", lv.values[0].key]
    after = build_report_document(snapshot, value_order=rank)
    assert [g.key for g in after.groups] == [lv.key, mv.key]
    assert after.groups[0].values == (lv.values[1], lv.values[0], *lv.values[2:])
    assert after.groups[1].values == (mv.values[-1], *mv.values[:-1])
    # Editing only a subset in another study retains an absent parameter's slot.
    assert merge_report_order(["a", "absent", "b"], ("b", "a", "new")) == ("b", "absent", "a", "new")
