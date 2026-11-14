"""Calibration consumers: every physical path uses its own frame/panel (#547).

The audit behind #547 found that a frame/region-scoped calibration was resolved
correctly and then ignored by most consumers: areas, volumes, Simpson bases and
persistence still used one instance-level spacing.  These tests are the consumer
matrix — they pin the *correct* behavior for each path:

* geometry selection: a contour/area uses the panel under it, and a measurement
  spanning two panels is refused rather than measured with one of them;
* planimetry: two contours in two panels produce two areas, each from its own
  scale; an ambiguous scoped contour is skipped, not borrowed;
* Simpson/persistence: a record whose contours resolve to different scales does
  not freeze a physical basis (there is no single number to attribute);
* provenance policy: ``ASSUMED`` carries a reason, ``UNKNOWN`` is not a
  calibration, and vendor heuristics are never promoted to ``MEASURED``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydicom.dataset import Dataset

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.measurement_persistence import record_simpson_basis
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, StudyMeasurementSessionStore
from echo_personal_tool.domain.models.calibration import (
    ASSUMPTION_IMAGER_PLANE,
    ASSUMPTION_ISOTROPIC,
    ASSUMPTION_SECONDS_AS_LENGTH,
    CALIBRATION_MIXED,
    CalibrationConfidence,
    CalibrationContext,
    CalibrationRegion,
    CalibrationScope,
    select_calibration_for_points,
    select_common_calibration,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    manual_calibration_context,
    resolve_calibration_contexts,
)
from echo_personal_tool.domain.services.planimeter_formatter import planimeter_results_from_contours

_LEFT = CalibrationRegion(0, 50, 0, 50)
_RIGHT = CalibrationRegion(50, 100, 0, 50)

_LEFT_AREA = [(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]
_RIGHT_AREA = [(55.0, 5.0), (65.0, 5.0), (65.0, 15.0), (55.0, 15.0)]
_SPANNING = [(45.0, 5.0), (55.0, 5.0), (55.0, 15.0), (45.0, 15.0)]


def _region_context(
    spacing: tuple[float, float],
    region: CalibrationRegion,
    *,
    source: str = "SequenceOfUltrasoundRegions",
    revision: int = 0,
) -> CalibrationContext:
    return CalibrationContext(
        spacing=spacing,
        source=source,
        scope=CalibrationScope.REGION,
        region=region,
        revision=revision,
    )


def _instance(calibrations: tuple[CalibrationContext, ...]) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.4",
        modality="US",
        number_of_frames=2,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=Path("/data/test.dcm"),
        calibrations=calibrations,
    )


def _area(points: list[tuple[float, float]], *, uid: str = "1.2.3", frame: int = 0) -> Contour:
    return Contour(
        phase="GEN",
        view="A4C",
        chamber="AREA",
        points=points,
        frame_index=frame,
        sop_instance_uid=uid,
        measurement_id=f"area-{uid}-{frame}",
    )


class TestGeometrySelection:
    def test_contour_uses_the_panel_under_it(self) -> None:
        left = _region_context((0.1, 0.1), _LEFT)
        right = _region_context((0.2, 0.2), _RIGHT)
        contexts = (left, right)

        assert select_calibration_for_points(contexts, _LEFT_AREA, frame_index=0).context is left
        assert select_calibration_for_points(contexts, _RIGHT_AREA, frame_index=0).context is right

    def test_contour_spanning_two_panels_is_refused(self) -> None:
        contexts = (_region_context((0.1, 0.1), _LEFT), _region_context((0.2, 0.2), _RIGHT))
        selection = select_calibration_for_points(contexts, _SPANNING, frame_index=0)
        assert selection.context is None
        assert selection.reason == "crosses_region"

    def test_viewer_state_selects_by_geometry_not_only_by_frame(self) -> None:
        left = _region_context((0.1, 0.1), _LEFT)
        right = _region_context((0.2, 0.2), _RIGHT)
        state = ViewerState(
            instance=_instance((left, right)),
            current_frame_index=0,
            total_frames=2,
            frame_time_ms=33.3,
            is_playing=False,
        )
        assert state.calibration_for_points(_LEFT_AREA).context is left
        assert state.calibration_for_points(_RIGHT_AREA).context is right
        assert state.calibration_for_points(_SPANNING).context is None
        # The frame-only property cannot pick a panel, so it must not invent one.
        assert state.effective_pixel_spacing is None


class TestControllerConsumer:
    """The app-level resolver used for contours from any clip of the study."""

    @staticmethod
    def _controller(instance: InstanceMetadata) -> AppController:
        controller = AppController(thread_pool=SimpleNamespace(start=lambda *args: None))
        controller._current_instance = instance
        controller._studies = []
        controller.measurement_persistence = SimpleNamespace(sources={})
        return controller

    @staticmethod
    def _state(instance: InstanceMetadata) -> ViewerState:
        return ViewerState(
            instance=instance,
            current_frame_index=0,
            total_frames=2,
            frame_time_ms=33.3,
            is_playing=False,
        )

    def test_frame_scoped_contour_uses_its_own_frame_scale(self) -> None:
        first = CalibrationContext(
            spacing=(0.1, 0.1),
            source="PerFrameFunctionalGroupsSequence/PixelSpacing",
            scope=CalibrationScope.FRAME,
            frame_index=0,
            confidence=CalibrationConfidence.DERIVED,
        )
        second = CalibrationContext(
            spacing=(0.2, 0.2),
            source="PerFrameFunctionalGroupsSequence/PixelSpacing",
            scope=CalibrationScope.FRAME,
            frame_index=1,
            confidence=CalibrationConfidence.DERIVED,
        )
        instance = _instance((first, second))
        controller = self._controller(instance)
        state = self._state(instance)
        assert controller._spacing_for_contour(_area(_LEFT_AREA, frame=0), state) == ((0.1, 0.1), True)
        assert controller._spacing_for_contour(_area(_LEFT_AREA, frame=1), state) == ((0.2, 0.2), True)

    def test_panel_contour_and_spanning_contour_are_not_borrowed(self) -> None:
        contexts = (_region_context((0.1, 0.1), _LEFT), _region_context((0.2, 0.2), _RIGHT))
        instance = _instance(contexts)
        controller = self._controller(instance)
        state = self._state(instance)
        assert controller._spacing_for_contour(_area(_RIGHT_AREA), state) == ((0.2, 0.2), True)
        assert controller._spacing_for_contour(_area(_SPANNING), state) == (None, True)


class TestCommonCalibration:
    def test_identical_signatures_are_one_basis(self) -> None:
        context = manual_calibration_context((0.1, 0.1), revision=2)
        selection = select_common_calibration(
            (
                select_common_calibration((_context_selection(context),)),
                select_common_calibration((_context_selection(context),)),
            )
        )
        assert selection.context is context

    def test_different_revisions_or_scales_have_no_common_basis(self) -> None:
        first = manual_calibration_context((0.1, 0.1), revision=1)
        second = manual_calibration_context((0.1, 0.1), revision=2)
        third = manual_calibration_context((0.2, 0.2), revision=1)
        assert select_common_calibration((_context_selection(first), _context_selection(second))).reason == (
            CALIBRATION_MIXED
        )
        assert select_common_calibration((_context_selection(first), _context_selection(third))).reason == (
            CALIBRATION_MIXED
        )


def _context_selection(context: CalibrationContext):
    from echo_personal_tool.domain.models.calibration import CalibrationSelection

    return CalibrationSelection(context=context)


class TestPlanimetryConsumers:
    def test_each_area_is_computed_with_its_own_panel_scale(self) -> None:
        left = _region_context((0.1, 0.1), _LEFT)
        right = _region_context((0.2, 0.2), _RIGHT)
        contexts = (left, right)
        contours = (_area(_LEFT_AREA), _area(_RIGHT_AREA))

        results = planimeter_results_from_contours(
            contours,
            (0.1, 0.1),  # the active 2D panel: must not leak into the right contour
            spacing_calibrated=True,
            calibration_for=lambda contour: _selection_spacing(contexts, contour),
        )

        assert [result.kind for result in results] == ["area", "area"]
        assert results[0].unit == "cm²"
        assert results[1].unit == "cm²"
        # Same pixel polygon, twice the spacing -> four times the area.
        assert results[1].value == pytest.approx(4.0 * results[0].value)

    def test_ambiguous_scoped_contour_is_skipped_not_borrowed(self) -> None:
        contexts = (_region_context((0.1, 0.1), _LEFT), _region_context((0.2, 0.2), _RIGHT))
        contours = (_area(_LEFT_AREA), _area(_SPANNING))
        results = planimeter_results_from_contours(
            contours,
            (0.1, 0.1),
            spacing_calibrated=True,
            calibration_for=lambda contour: _selection_spacing(contexts, contour),
        )
        assert len(results) == 1
        assert results[0].value == pytest.approx(0.01)


def _selection_spacing(
    contexts: tuple[CalibrationContext, ...], contour: Contour
) -> tuple[tuple[float, float] | None, bool]:
    selection = select_calibration_for_points(contexts, contour.points, frame_index=contour.frame_index)
    if selection.context is None:
        return None, True
    return selection.context.spacing, selection.context.is_calibrated


class TestSimpsonPersistenceConsumer:
    def test_mixed_scales_do_not_freeze_a_simpson_basis(self) -> None:
        first = _region_context((0.1, 0.1), _LEFT)
        second = _region_context((0.2, 0.2), _RIGHT)
        data = StudyMeasurementData(
            contours=(
                Contour(
                    phase="ed",
                    view="A4C",
                    points=_LEFT_AREA,
                    frame_index=0,
                    sop_instance_uid="1.2.3",
                    measurement_id="ed",
                ),
                Contour(
                    phase="es",
                    view="A4C",
                    points=_RIGHT_AREA,
                    frame_index=1,
                    sop_instance_uid="1.4.7",
                    measurement_id="es",
                ),
            ),
            calibration_by_instance=(("1.2.3", first), ("1.4.7", second)),
        )
        recorded = record_simpson_basis(
            data,
            {
                "1.2.3": {"spacing": [0.1, 0.1], "frames": 2},
                "1.4.7": {"spacing": [0.2, 0.2], "frames": 2},
            },
        )
        assert recorded.simpson_basis is None

    def test_one_scale_still_records_its_provenance(self) -> None:
        context = manual_calibration_context((0.1, 0.1), revision=3)
        data = StudyMeasurementData(
            contours=(
                Contour(
                    phase="ed",
                    view="A4C",
                    points=_LEFT_AREA,
                    frame_index=0,
                    sop_instance_uid="1.2.3",
                    measurement_id="ed",
                ),
            ),
            calibration_by_instance=(("1.2.3", context),),
        )
        recorded = record_simpson_basis(data, {"1.2.3": {"spacing": [0.1, 0.1], "frames": 2}})
        assert recorded.simpson_basis is not None
        assert recorded.simpson_basis.calibration == context


class TestAreaCurveConsumer:
    def test_curve_area_uses_the_contour_scale_and_skips_ambiguity(self) -> None:
        store = StudyMeasurementSessionStore()
        left = _region_context((0.1, 0.1), _LEFT)
        right = _region_context((0.2, 0.2), _RIGHT)
        contexts = (left, right)
        store.merge_simpson_areas(
            "study",
            (
                Contour(
                    phase="ed",
                    view="A4C",
                    chamber="LV",
                    points=_LEFT_AREA,
                    frame_index=0,
                    sop_instance_uid="1.2.3",
                ),
                Contour(
                    phase="es",
                    view="A4C",
                    chamber="LV",
                    points=_SPANNING,
                    frame_index=1,
                    sop_instance_uid="1.2.3",
                ),
            ),
            (0.1, 0.1),
            calibration_for=lambda contour: _selection_spacing(contexts, contour),
        )
        curve = store.get_simpson_area_curve("study", "1.2.3", "A4C")
        assert [frame for frame, _area in curve] == [0]
        assert curve[0][1] == pytest.approx(1.0)

    def test_recalibration_marks_previous_areas_stale_by_revision(self) -> None:
        store = StudyMeasurementSessionStore()
        store.set_instance_spacing("study", "1.2.3", (0.1, 0.1))
        first = store.get_instance_calibration("study", "1.2.3")
        assert first is not None and first.revision == 1
        store.set_instance_spacing("study", "1.2.3", (0.1, 0.1))
        second = store.get_instance_calibration("study", "1.2.3")
        assert second is not None and second.revision == 2
        assert second.signature() != first.signature()


class TestAssumptionPolicy:
    def test_measured_cannot_carry_an_assumption(self) -> None:
        with pytest.raises(ValueError):
            CalibrationContext(
                spacing=(0.1, 0.1),
                source="PixelSpacing",
                confidence=CalibrationConfidence.MEASURED,
                assumption=ASSUMPTION_IMAGER_PLANE,
            )

    def test_manual_isotropic_is_assumed_and_says_why(self) -> None:
        context = manual_calibration_context((0.1, 0.1))
        assert context.confidence is CalibrationConfidence.ASSUMED
        assert context.assumption == ASSUMPTION_ISOTROPIC
        assert context.needs_assumption_note

    def test_imager_spacing_is_assumed_with_its_plane_reason(self) -> None:
        ds = Dataset()
        ds.ImagerPixelSpacing = [0.2, 0.2]
        context = resolve_calibration_contexts(ds)[0]
        assert context.confidence is CalibrationConfidence.ASSUMED
        assert context.assumption == ASSUMPTION_IMAGER_PLANE

    def test_seconds_used_as_length_is_an_assumption_not_measured(self) -> None:
        ds = Dataset()
        region = Dataset()
        region.RegionSpatialFormat = 1
        region.RegionDataType = 1
        region.PhysicalDeltaX = 0.03
        region.PhysicalUnitsXDirection = 3  # seconds, the vendor mis-tag
        region.PhysicalDeltaY = 0.03
        region.PhysicalUnitsYDirection = 1  # centimetres
        region.RegionLocationMinX0 = 0
        region.RegionLocationMaxX1 = 49
        region.RegionLocationMinY0 = 0
        region.RegionLocationMaxY1 = 49
        ds.SequenceOfUltrasoundRegions = [region]

        context = resolve_calibration_contexts(ds)[0]
        assert context.confidence is CalibrationConfidence.ASSUMED
        assert context.assumption == ASSUMPTION_SECONDS_AS_LENGTH
        assert context.spacing == (0.3, 0.3)
        assert context.needs_assumption_note

    def test_unknown_is_not_a_calibration(self) -> None:
        context = CalibrationContext(
            spacing=(0.1, 0.1), source="saved_spacing", confidence=CalibrationConfidence.UNKNOWN
        )
        assert not context.is_calibrated
