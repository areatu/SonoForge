"""Measurements must survive frame and file switches inside one study.

The session store is the only place where measurements live between clips, so
its merge rules decide what the operator sees after switching files and what
ends up in the study report.
"""

from __future__ import annotations

from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementSessionStore,
    merge_contours,
    replace_linear_measurements_for_instance,
)
from echo_personal_tool.domain.models import Contour, LinearMeasurement


def _m(label: str, mm: float, uid: str, frame: int = 0) -> LinearMeasurement:
    return LinearMeasurement(
        label=label,
        pixel_length=mm * 2,
        millimeter_length=mm,
        frame_index=frame,
        sop_instance_uid=uid,
    )


def _area_contour(label: str, uid: str) -> Contour:
    return Contour(
        phase="GEN",
        view="A4C",
        chamber="AREA",
        points=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)],
        measurement_label=label,
        sop_instance_uid=uid,
    )


def _lv_contour(phase: str, uid: str) -> Contour:
    return Contour(
        phase=phase,
        view="A4C",
        chamber="LV",
        points=[(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)],
        sop_instance_uid=uid,
    )


class TestPerInstanceCaliperReplacement:
    def test_deletion_in_one_clip_does_not_resurrect(self) -> None:
        existing = (_m("LVEDD", 50.0, "clip-a"), _m("IVSd", 10.0, "clip-a"))
        # The viewer of clip-a now reports only IVSd: LVEDD was deleted.
        result = replace_linear_measurements_for_instance(existing, "clip-a", (_m("IVSd", 10.0, "clip-a"),))
        assert [m.label for m in result] == ["IVSd"]

    def test_other_clips_are_untouched(self) -> None:
        existing = (_m("LVEDD", 50.0, "clip-a"), _m("E", 80.0, "clip-b"))
        result = replace_linear_measurements_for_instance(existing, "clip-a", (_m("LVEDD", 52.0, "clip-a"),))
        by_uid = {m.sop_instance_uid: m for m in result}
        assert by_uid["clip-a"].millimeter_length == 52.0
        assert by_uid["clip-b"].label == "E"

    def test_empty_report_clears_only_that_clip(self) -> None:
        existing = (_m("LVEDD", 50.0, "clip-a"), _m("E", 80.0, "clip-b"))
        result = replace_linear_measurements_for_instance(existing, "clip-a", ())
        assert [m.sop_instance_uid for m in result] == ["clip-b"]


class TestSessionStoreAcrossClips:
    def test_measurements_accumulate_over_clips(self) -> None:
        store = StudyMeasurementSessionStore()
        store.set_linear_measurements_for_instance("study", "clip-a", (_m("LVEDD", 50.0, "clip-a"),))
        store.set_linear_measurements_for_instance("study", "clip-b", (_m("E", 80.0, "clip-b"),))
        # Opening a clip with nothing measured must not drop the others.
        store.merge_linear_measurements("study", ())
        labels = {m.label for m in store.get("study").linear_measurements}
        assert labels == {"LVEDD", "E"}

    def test_clear_instance_measurements(self) -> None:
        store = StudyMeasurementSessionStore()
        store.set_linear_measurements_for_instance("study", "clip-a", (_m("LVEDD", 50.0, "clip-a"),))
        store.set_linear_measurements_for_instance("study", "clip-b", (_m("E", 80.0, "clip-b"),))
        store.clear_instance_measurements("study", "clip-a")
        labels = {m.label for m in store.get("study").linear_measurements}
        assert labels == {"E"}


class TestContourDeletionPropagation:
    def test_deleted_planimeter_contour_is_dropped(self) -> None:
        existing = (_area_contour("Площадь1", "clip-a"), _area_contour("Площадь2", "clip-a"))
        merged = merge_contours(
            existing,
            (_area_contour("Площадь1", "clip-a"),),
            authoritative_instance_uid="clip-a",
        )
        assert [c.measurement_label for c in merged] == ["Площадь1"]

    def test_lv_contours_survive_a_partial_report(self) -> None:
        existing = (_lv_contour("ED", "clip-a"), _lv_contour("ES", "clip-a"))
        merged = merge_contours(
            existing,
            (_lv_contour("ED", "clip-a"),),
            authoritative_instance_uid="clip-a",
        )
        assert sorted(c.phase for c in merged) == ["ED", "ES"]

    def test_other_clips_planimetry_is_untouched(self) -> None:
        existing = (_area_contour("Площадь1", "clip-a"), _area_contour("Площадь1", "clip-b"))
        merged = merge_contours(
            existing,
            (),
            authoritative_instance_uid="clip-a",
        )
        assert len(merged) == 2  # an empty report is ignored, nothing is lost

    def test_updated_planimeter_contour_replaces_the_old_one(self) -> None:
        existing = (_area_contour("Площадь1", "clip-a"),)
        moved = Contour(
            phase="GEN",
            view="A4C",
            chamber="AREA",
            points=[(1.0, 1.0), (11.0, 1.0), (11.0, 11.0)],
            measurement_label="Площадь1",
            sop_instance_uid="clip-a",
        )
        merged = merge_contours(existing, (moved,), authoritative_instance_uid="clip-a")
        assert len(merged) == 1
        assert merged[0].points[0] == (1.0, 1.0)
