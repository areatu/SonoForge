"""Task 4: derived values must cite the source they were computed from.

The report card said «происхождение не записано» about Simpson volumes,
Teichholz volumes, planimeter areas and LV mass even when the study held the
exact contours and calipers the values came from. The lineage was recorded all
along: the contour object carried its measurement id, its clip and its frame,
and the calculation threw it away at the boundary. These tests pin the rule
from both sides — recorded lineage must reach the report, and *absent*
lineage must still read as unrecorded (no guessing from the current state).
"""

from __future__ import annotations

import math


def _poly(cx: float, cy: float, rz: float, rx: float, n: int = 24) -> list[tuple[float, float]]:
    return [(cx + rx * math.cos(math.pi * i / (n - 1)), cy - rz * math.sin(math.pi * i / (n - 1))) for i in range(n)]


def _lv_contours(*, with_lineage: bool = True) -> tuple:
    from echo_personal_tool.domain.models.contour import Contour

    contours = []
    for view, rz, rx in (("A4C", 60.0, 26.0), ("A2C", 58.0, 25.0)):
        for phase, scale, frame in (("ed", 1.0, 12), ("es", 0.72, 22)):
            contours.append(
                Contour(
                    phase=phase,
                    view=view,
                    chamber="LV",
                    points=_poly(200, 260, rz * scale, rx * scale),
                    mitral_annulus=((150, 260), (250, 260)),
                    frame_index=frame if with_lineage else None,
                    sop_instance_uid=f"1.2.840.{view}.{phase}" if with_lineage else "",
                    measurement_id=f"m-{view}-{phase}" if with_lineage else "",
                    revision=3 if with_lineage else 0,
                )
            )
    return tuple(contours)


def _values_with_method(groups, method_id: str):
    """Rows whose origin names *method_id* — the labels are translated."""
    return [
        value
        for group in groups
        for value in group.values
        if value.origin is not None and value.origin.method_id == method_id
    ]


def test_simpson_volumes_cite_their_contours() -> None:
    from echo_personal_tool.domain.calculations.lvef_simpson import calculate
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    lvef = calculate(_lv_contours(), (0.35, 0.35))
    assert lvef is not None and lvef.method == "simpson_biplan"
    groups = build_report_groups(MeasurementSnapshot(lvef=lvef), sex="F")

    # Every Simpson row carries a derived origin with the recorded clips.
    derived = [
        value
        for group in groups
        for value in group.values
        if value.origin is not None and value.origin.method_id == "simpson_biplan"
    ]
    assert derived, "the Simpson rows must report where they came from"
    for value in derived:
        origin = value.origin
        assert origin.kind == "derived"
        assert origin.recorded, f"{value.label} lost its recorded lineage"
        assert origin.clips, f"{value.label} must name the clip it was traced on"

    # EDV rows cite diastole, ESV rows cite systole — not the first contour.
    for group in groups:
        for value in group.values:
            origin = value.origin
            if origin is None or origin.method_id != "simpson_biplan":
                continue
            clips = {clip.sop_instance_uid for clip in origin.clips}
            if "kdo_lv" in value.label or value.label.endswith("EDV 4C"):
                assert all(clip.endswith(".ed") for clip in clips), (value.label, clips)
            if "kso_lv" in value.label or value.label.endswith("ESV 4C"):
                assert all(clip.endswith(".es") for clip in clips), (value.label, clips)


def test_simpson_without_recorded_lineage_stays_unrecorded() -> None:
    """Honesty rule: nothing is invented when the contour recorded nothing."""
    from echo_personal_tool.domain.calculations.lvef_simpson import calculate
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    lvef = calculate(_lv_contours(with_lineage=False), (0.35, 0.35))
    groups = build_report_groups(MeasurementSnapshot(lvef=lvef), sex="F")
    derived = [
        value
        for group in groups
        for value in group.values
        if value.origin is not None and value.origin.method_id == "simpson_biplan"
    ]
    assert derived
    for value in derived:
        assert not value.origin.recorded, f"{value.label} must not pretend to a source"
        assert not value.origin.clips
        assert value.origin.reason == "provenance_not_recorded"


def test_teichholz_volumes_cite_their_own_caliper() -> None:
    from echo_personal_tool.domain.calculations.teichholz import from_linear_measurements
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    def caliper(label: str, mm: float, uid: str, frame: int, mid: str) -> LinearMeasurement:
        return LinearMeasurement(
            label=label,
            millimeter_length=mm,
            pixel_length=mm * 3,
            sop_instance_uid=uid,
            frame_index=frame,
            measurement_id=mid,
        )

    calipers = (
        caliper("LVEDD", 50.0, "clip1", 11, "m1"),
        caliper("LVESD", 33.0, "clip2", 21, "m2"),
    )
    teichholz = from_linear_measurements(calipers)
    groups = build_report_groups(MeasurementSnapshot(teichholz=teichholz, linear_measurements=calipers), sex="F")

    # The Teichholz section, in order: EDV, ESV, EF, SV, then the calipers.
    teichholz_rows = [value for value in _values_with_method(groups, "teichholz")]
    assert len(teichholz_rows) == 4, [value.label for value in teichholz_rows]
    edv, esv, ef, sv = teichholz_rows
    # Each volume names its own caliper: EDV the diastolic, ESV the systolic.
    assert [clip.sop_instance_uid for clip in edv.origin.clips] == ["clip1"]
    assert [clip.sop_instance_uid for clip in esv.origin.clips] == ["clip2"]
    # EF and SV consume both calipers, so they cite both clips.
    assert [clip.sop_instance_uid for clip in ef.origin.clips] == ["clip1", "clip2"]
    assert [clip.sop_instance_uid for clip in sv.origin.clips] == ["clip1", "clip2"]
    assert sv.value is not None and float(sv.value) > 0


def test_lv_mass_and_rwt_cite_the_calipers() -> None:
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    calipers = (
        LinearMeasurement(
            label="LVEDD",
            millimeter_length=52.0,
            pixel_length=156.0,
            sop_instance_uid="clip1",
            frame_index=8,
            measurement_id="m1",
        ),
    )
    groups = build_report_groups(MeasurementSnapshot(lvm_g=170.0, rwt=0.42, linear_measurements=calipers), sex="M")
    derived = _values_with_method(groups, "linear_derived")
    assert len(derived) == 2, [value.label for value in derived]  # LV mass and RWT
    for value in derived:
        assert value.origin.recorded
        assert value.origin.clips[0].sop_instance_uid == "clip1"


def test_planimeter_areas_cite_the_traced_contour() -> None:
    from echo_personal_tool.domain.models.contour import Contour
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.planimeter_formatter import planimeter_results_from_contours
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    contour = Contour(
        phase="ed",
        chamber="AREA",
        points=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        sop_instance_uid="clip-area",
        frame_index=4,
        measurement_id="m-area",
        revision=2,
    )
    results = planimeter_results_from_contours((contour,), (0.5, 0.5), spacing_calibrated=True)
    assert results and results[0].contour is not None

    snapshot = MeasurementSnapshot(planimeter=results)
    values = [v for group in build_report_groups(snapshot) for v in group.values if v.origin is not None]
    assert values, "the planimeter row must carry an origin"
    origin = values[0].origin
    assert origin.recorded
    assert origin.measurement_id == "m-area"
    assert origin.clips[0].sop_instance_uid == "clip-area"
    assert origin.clips[0].frame_index == 4


def test_a_legacy_planimeter_result_still_says_unrecorded() -> None:
    """No lineage stored (older documents): the method is all the card can name."""
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, PlanimeterResult
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    snapshot = MeasurementSnapshot(planimeter=(PlanimeterResult(label="Area", kind="area", value=12.0, unit="cm²"),))
    values = [v for group in build_report_groups(snapshot) for v in group.values if v.origin is not None]
    assert values
    assert not values[0].origin.recorded
    assert values[0].origin.method_id == "planimeter"
