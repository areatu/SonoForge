"""Repeat selection is an input to report calculations, not a text substitution."""

from dataclasses import replace

import pytest

from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.calculations.lvm import lvm_grams
from echo_personal_tool.domain.calculations.teichholz import volume_ml
from echo_personal_tool.domain.models import Contour, InstanceMetadata, LinearMeasurement, VesselMeasurement
from echo_personal_tool.domain.models.report_repeat import ReportCandidate
from echo_personal_tool.domain.models.value_origin import ClipSource
from echo_personal_tool.domain.services.report_builder import build_report_document
from echo_personal_tool.domain.services.report_selection import select_report_sources


def _linear(label, mm, frame, clip="1.2.3"):
    return LinearMeasurement(label, mm * 2, mm, frame, sop_instance_uid=clip)


def _instance(uid):
    return InstanceMetadata(uid, "1.2", "US", 30, (1.0, 1.0), 33.0, "A4C")


def test_single_repeats_follow_acquisition_not_frame_or_numeric_order():
    first = _linear("Custom", 13, 9)
    second = _linear("Custom", 10, 2)
    third = _linear("Custom", 11, 0, "1.2.2")
    other = _linear("Independent", 12, 8)
    active, (repeat,) = select_report_sources((first, other, second), {})
    assert active == (other, second)
    assert repeat.override == ""
    assert repeat.candidates[-1] == ReportCandidate(
        repeat.default_id, ((second.display_text(), ClipSource("1.2.3", 2)),)
    )
    override = {repeat.key: repeat.candidates[0].id}
    changed = replace(first, millimeter_length=14, revision=2)
    assert select_report_sources((changed, other, second, third), override)[0] == (changed, other)
    # A vanished source must not turn its old ordinal into a different choice.
    active, (fallback,) = select_report_sources((second, third), override)
    assert active == (third,) and fallback.override == ""


def test_area_volume_and_named_vessel_sites_remain_distinct():
    a = Contour("GEN", chamber="AREA", measurement_label="X", sop_instance_uid="a")
    b, volume = replace(a, sop_instance_uid="b"), replace(a, chamber="VOL")
    assert select_report_sources((a, volume, b), {})[0] == (volume, b)
    r = VesselMeasurement(80, 20, 0.75, 4, None, "a", 8, label="CCA-R")
    l, new = replace(r, label="CCA-L"), replace(r, psv_cm_s=90, frame_index=2)
    selected, (repeat,) = select_report_sources((r, l, new), {})
    assert selected == (l, new)
    assert select_report_sources((r, l, new), {repeat.key: repeat.candidates[0].id})[0] == (r, l)


@pytest.mark.gui
def test_the_chosen_diastolic_sequence_drives_teichholz_mass_indexes_and_provenance(qapp):
    from echo_personal_tool.application.app_controller import AppController

    controller = AppController()
    controller.state_manager.set_instance(_instance("1.2.3"), 30, 33, emit=False)
    controller.set_calculator_input("bsa", 2.0)
    measurements = tuple(
        _linear(label, mm, frame)
        for ed_frame, es_frame, sizes in [(18, 23, (8, 48, 9, 30)), (2, 5, (10, 57, 11, 38))]
        for (label, frame), mm in zip(
            [("IVSd", ed_frame), ("LVEDD", ed_frame), ("LVPWd", ed_frame), ("LVESD", es_frame)], sizes
        )
    )
    controller.on_linear_measurements_changed(list(measurements))
    latest = controller.compute_study_snapshot(report_choices={})
    assert latest.linear_measurements == measurements[4:]
    assert latest.teichholz.esv_ml == pytest.approx(volume_ml(38))
    (repeat,) = latest.report_repeats
    chosen = controller.compute_study_snapshot(report_choices={repeat.key: repeat.candidates[0].id})
    assert chosen.linear_measurements == measurements[:4]
    assert chosen.teichholz.edv_ml == pytest.approx(volume_ml(48))
    assert chosen.teichholz.esv_ml == pytest.approx(volume_ml(30))
    assert chosen.lvm_g == pytest.approx(lvm_grams(8, 48, 9))
    assert chosen.indexed.teichholz_edvi_ml_m2 == pytest.approx(volume_ml(48) / 2)
    assert chosen.calculations.input("lvedd").value == pytest.approx(4.8)
    rows = {v.parameter_id: v for group in build_report_document(chosen).groups for v in group.values}
    assert rows["linear.lv.lvesd"].repeat == rows["linear.lv.ivsd"].repeat == chosen.report_repeats[0]
    assert [clip.frame_index for clip in rows["lv.ef_teich"].origin.clips] == [18, 23]
    assert controller.compute_study_snapshot().linear_measurements == measurements


def _contour(phase, frame, size, uid, view="A4C"):
    return Contour(
        phase,
        view=view,
        points=[(0, 0), (size / 2, -size), (size, 0)],
        mitral_annulus=((0, 0), (size, 0)),
        frame_index=frame,
        sop_instance_uid=uid,
        measurement_id=f"{uid}:{phase}:{view}",
    )


@pytest.mark.gui
def test_simpson_selection_changes_both_phases_and_biplane_without_mixing_clips(qapp):
    from echo_personal_tool.application.app_controller import AppController

    controller = AppController()

    def add(uid, contours):
        controller.state_manager.set_instance(_instance(uid), 30, 33, emit=False)
        controller.on_contours_changed(list(contours))

    def pair(uid, size, view):
        return (_contour("ED", 2, size, uid, view), _contour("ES", 8, size * 0.65, uid, view))

    old = pair("1.2.9", 65, "A4C")
    new = pair("1.2.8", 50, "A4C")
    other_view = pair("1.2.7", 56, "A2C")
    for items in (old, new, other_view):
        add(items[0].sop_instance_uid, items)
    # An incomplete run is selectable but must not steal the ES of a complete pair.
    add("1.2.6", (_contour("ED", 1, 58, "1.2.6"),))
    latest = controller.compute_study_snapshot(report_choices={})
    assert latest.lvef == calculate(new + other_view, (1.0, 1.0))
    add("1.2.9", old)  # re-emission of an older clip is not a new pair
    assert controller.compute_study_snapshot(report_choices={}).lvef == latest.lvef
    rows = {v.parameter_id: v for g in build_report_document(latest).groups for v in g.values}
    repeat = rows["lv.edv_a4c"].repeat
    assert repeat == rows["lv.esv_a4c"].repeat and len(repeat.candidates) == 3
    assert repeat.default_id == repeat.candidates[1].id
    selected = controller.compute_study_snapshot(report_choices={repeat.key: repeat.candidates[0].id})
    assert selected.lvef == calculate(old + other_view, (1.0, 1.0))
    assert selected.lvef.edv_bi_ml != latest.lvef.edv_bi_ml
    assert selected.lvef.a4c.es_contour.measurement_id == old[1].measurement_id
    partial = controller.compute_study_snapshot(report_choices={repeat.key: repeat.candidates[-1].id})
    assert partial.lvef.a4c.esv_ml is None and partial.lvef.esv_bi_ml is None


def test_a_systolic_caliper_without_diastole_is_not_paired_with_the_next_cycle():
    es_only = _linear("LVESD", 18, 8)
    ed, es = _linear("LVIDd", 51, 1), _linear("LVESD", 33, 5)
    selected, (repeat,) = select_report_sources((es_only, ed, es), {})
    assert selected == (ed, es)
    assert select_report_sources((es_only, ed, es), {repeat.key: repeat.candidates[0].id})[0] == (es_only,)


@pytest.mark.parametrize(
    ("chamber", "view", "row_id"),
    [("LA", "A4C", "la.lav_a4c"), ("LA", "A2C", "la.area"), ("RA", "A4C", "ra.vol"), ("RV", "A4C", "rv.edv_a4c")],
)
@pytest.mark.gui
def test_other_chamber_contours_offer_the_accepted_acquisitions(chamber, view, row_id, qapp):
    from echo_personal_tool.application.app_controller import AppController

    controller = AppController()
    for uid, size, pending in [("1.2.1", 55, False), ("1.2.2", 40, False), ("1.2.3", 65, True)]:
        controller.state_manager.set_instance(_instance(uid), 30, 33, emit=False)
        contour = replace(_contour("ES", 3, size, uid, view), chamber=chamber, review_pending=pending)
        controller.on_contours_changed([contour])

    def row(choices):
        snapshot = controller.compute_study_snapshot(report_choices=choices)
        assert snapshot.unreviewed_contours == 1
        return next(v for g in build_report_document(snapshot).groups for v in g.values if v.parameter_id == row_id)

    latest = row({})
    options = latest.repeat
    assert len(options.candidates) == 2 and options.default_id == options.candidates[-1].id
    older = row({options.key: options.candidates[0].id})
    assert float(older.value) > float(latest.value)


def test_selected_contour_from_another_pixel_grid_keeps_its_physical_result():
    from echo_personal_tool.application.contour_calibration import express_contours_on_grid
    from echo_personal_tool.domain.services.report_selection import contour_candidate_text

    large = replace(_contour("ED", 1, 65, "a"), apex_landmark=(32.5, -65))
    small = _contour("ED", 0, 35, "b")
    source_grid, display_grid = (0.5, 0.8), (0.7, 0.6)
    common = express_contours_on_grid(
        (large, small), display_grid, lambda c: (source_grid if c is large else display_grid, True)
    )

    def describe(c):
        return contour_candidate_text(c, display_grid, True)

    _, (repeat,) = select_report_sources(common, {}, describe=describe)
    selected, _ = select_report_sources(common, {repeat.key: repeat.candidates[0].id}, describe=describe)
    assert repeat.candidates[0].parts[0][0] == contour_candidate_text(large, source_grid, True)
    expected = calculate((large,), source_grid).a4c
    actual = calculate(selected, display_grid).a4c
    assert actual.edv_ml == pytest.approx(expected.edv_ml)
    assert actual.length_ed_mm == pytest.approx(expected.length_ed_mm)
