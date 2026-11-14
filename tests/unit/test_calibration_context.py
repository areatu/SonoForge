"""Calibration provenance and scoped selection (#547, #553 6.1)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydicom.dataset import Dataset

from echo_personal_tool.application.measurement_persistence import record_simpson_basis
from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, StudyMeasurementSessionStore
from echo_personal_tool.domain.models.calibration import (
    CALIBRATION_AMBIGUOUS,
    CALIBRATION_CROSSES_REGION,
    CALIBRATION_REGION_REQUIRED,
    CalibrationConfidence,
    CalibrationContext,
    CalibrationRegion,
    CalibrationScope,
    invalidate_dependents,
    select_calibration,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.result_provenance import REASON_CALIBRATION_CHANGED
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    manual_calibration_context,
    resolution_from_contexts,
    resolve_calibration_contexts,
    resolve_pixel_spacing,
)
from echo_personal_tool.domain.services.simpson_freshness import (
    evaluate_simpson_freshness,
    simpson_basis_from_contours,
)
from echo_personal_tool.infrastructure import measurement_codec

_UTC = timezone.utc  # noqa: UP017 - datetime.UTC migration deferred (ruff target py310)


def _instance(calibrations: tuple[CalibrationContext, ...] = ()) -> InstanceMetadata:
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


def _context(spacing: tuple[float, float] = (0.1, 0.1), **kwargs) -> CalibrationContext:
    return CalibrationContext(spacing=spacing, source="PixelSpacing", **kwargs)


class TestCalibrationContextValidation:
    @pytest.mark.parametrize(
        "spacing",
        [(float("nan"), 0.1), (0.1, float("inf")), (0.0, 0.1), (-0.1, 0.1)],
    )
    def test_non_finite_or_non_positive_spacing_is_rejected(self, spacing) -> None:
        with pytest.raises(ValueError):
            _context(spacing)

    def test_frame_scope_requires_frame(self) -> None:
        with pytest.raises(ValueError):
            _context(scope=CalibrationScope.FRAME)

    def test_region_scope_requires_region(self) -> None:
        with pytest.raises(ValueError):
            _context(scope=CalibrationScope.REGION)

    def test_instance_scope_cannot_carry_frame_or_region(self) -> None:
        with pytest.raises(ValueError):
            _context(frame_index=1)
        with pytest.raises(ValueError):
            _context(region=CalibrationRegion(0, 10, 0, 10))

    def test_isotropy_marker(self) -> None:
        assert _context((0.1, 0.1)).is_isotropic
        assert not _context((0.1, 0.2)).is_isotropic
        manual = manual_calibration_context((0.1, 0.1))
        assert manual.confidence is CalibrationConfidence.ASSUMED
        assert manual.assumed_isotropic is True

    def test_revision_bump_changes_signature(self) -> None:
        context = _context(revision=1)
        bumped = invalidate_dependents(context)
        assert bumped.revision == 2
        assert bumped.signature() != context.signature()


class TestRegionSelection:
    def test_region_contains_half_open_bbox(self) -> None:
        region = CalibrationRegion(10, 20, 30, 40)
        assert region.contains(10, 30)
        assert not region.contains(20, 30)
        assert region.contains_bbox((10, 30, 19, 39))
        assert not region.contains_bbox((9, 30, 19, 39))

    def test_bbox_selects_the_enclosing_region(self) -> None:
        left = _context((0.1, 0.1), scope=CalibrationScope.REGION, region=CalibrationRegion(0, 50, 0, 50))
        right = _context((0.2, 0.2), scope=CalibrationScope.REGION, region=CalibrationRegion(50, 100, 0, 50))
        selection = select_calibration((left, right), frame_index=0, bbox=(10, 10, 20, 20))
        assert selection.context is left
        assert select_calibration((left, right), frame_index=0, bbox=(60, 10, 70, 20)).context is right

    def test_crossing_regions_is_refused(self) -> None:
        left = _context((0.1, 0.1), scope=CalibrationScope.REGION, region=CalibrationRegion(0, 50, 0, 50))
        right = _context((0.2, 0.2), scope=CalibrationScope.REGION, region=CalibrationRegion(50, 100, 0, 50))
        selection = select_calibration((left, right), frame_index=0, bbox=(40, 10, 60, 20))
        assert selection.context is None
        assert selection.reason == CALIBRATION_CROSSES_REGION

    def test_crossing_a_region_is_refused_even_with_instance_fallback(self) -> None:
        instance = _context((0.1, 0.1))
        region = _context((0.2, 0.2), scope=CalibrationScope.REGION, region=CalibrationRegion(50, 100, 0, 50))
        selection = select_calibration((instance, region), frame_index=0, bbox=(40, 10, 60, 20))
        assert selection.context is None
        assert selection.reason == CALIBRATION_CROSSES_REGION
        # Entirely outside the panel, the instance fallback remains usable.
        assert select_calibration((instance, region), frame_index=0, bbox=(0, 0, 10, 10)).context is instance

    def test_region_geometry_required_without_bbox(self) -> None:
        left = _context((0.1, 0.1), scope=CalibrationScope.REGION, region=CalibrationRegion(0, 50, 0, 50))
        right = _context((0.2, 0.2), scope=CalibrationScope.REGION, region=CalibrationRegion(50, 100, 0, 50))
        selection = select_calibration((left, right), frame_index=0)
        assert selection.reason == CALIBRATION_REGION_REQUIRED

    def test_different_regions_with_same_spacing_are_unambiguous(self) -> None:
        first = _context((0.1, 0.1), scope=CalibrationScope.REGION, region=CalibrationRegion(0, 50, 0, 50))
        second = _context((0.1, 0.1), scope=CalibrationScope.REGION, region=CalibrationRegion(50, 100, 0, 50))
        assert select_calibration((first, second)).context is not None

    def test_mixed_instance_and_region_different_spacing_needs_geometry(self) -> None:
        instance = _context((0.1, 0.1))
        region = _context((0.2, 0.2), scope=CalibrationScope.REGION, region=CalibrationRegion(0, 50, 0, 50))
        assert select_calibration((instance, region)).reason == CALIBRATION_AMBIGUOUS


class TestFrameScopedSelection:
    def test_frame_context_only_applies_to_its_frame(self) -> None:
        first = _context((0.1, 0.1), scope=CalibrationScope.FRAME, frame_index=0)
        second = _context((0.2, 0.2), scope=CalibrationScope.FRAME, frame_index=1)
        assert select_calibration((first, second), frame_index=0).context is first
        assert select_calibration((first, second), frame_index=1).context is second
        assert select_calibration((first, second), frame_index=None).context is None

    def test_viewer_state_uses_current_frame_calibration(self) -> None:
        first = _context((0.1, 0.1), scope=CalibrationScope.FRAME, frame_index=0)
        second = _context((0.2, 0.2), scope=CalibrationScope.FRAME, frame_index=1)
        state = ViewerState(
            instance=_instance((first, second)),
            current_frame_index=1,
            total_frames=2,
            frame_time_ms=33.3,
            is_playing=False,
        )
        assert state.effective_pixel_spacing == (0.2, 0.2)
        assert state.calibration_scope is CalibrationScope.FRAME
        assert state.calibration_revision == 0


class TestResolverScopes:
    def _per_frame_dataset(self, spacings: list[tuple[float, float]]) -> Dataset:
        ds = Dataset()
        items = []
        for spacing in spacings:
            item = Dataset()
            measures = Dataset()
            measures.PixelSpacing = list(spacing)
            item.PixelMeasuresSequence = [measures]
            items.append(item)
        ds.PerFrameFunctionalGroupsSequence = items
        return ds

    def test_varying_per_frame_spacing_is_not_collapsed_to_one_value(self) -> None:
        ds = self._per_frame_dataset([(0.1, 0.1), (0.2, 0.2)])
        contexts = resolve_calibration_contexts(ds)
        assert [context.scope for context in contexts] == [CalibrationScope.FRAME, CalibrationScope.FRAME]
        assert [context.frame_index for context in contexts] == [0, 1]
        assert resolve_pixel_spacing(ds) is None

    def test_uniform_per_frame_spacing_is_instance_scoped(self) -> None:
        ds = self._per_frame_dataset([(0.1, 0.1), (0.1, 0.1)])
        contexts = resolve_calibration_contexts(ds)
        assert len(contexts) == 1
        assert contexts[0].scope is CalibrationScope.INSTANCE
        assert resolve_pixel_spacing(ds).spacing == (0.1, 0.1)

    def test_multiple_us_regions_keep_bounds_and_are_not_guessed(self) -> None:
        ds = Dataset()
        regions = []
        for x0, spacing in ((0, 0.1), (50, 0.2)):
            region = Dataset()
            region.RegionSpatialFormat = 1
            region.RegionDataType = 1
            region.PhysicalDeltaX = spacing
            region.PhysicalDeltaY = spacing
            region.RegionLocationMinX0 = x0
            region.RegionLocationMaxX1 = x0 + 49
            region.RegionLocationMinY0 = 0
            region.RegionLocationMaxY1 = 49
            regions.append(region)
        ds.SequenceOfUltrasoundRegions = regions
        contexts = resolve_calibration_contexts(ds)
        assert len(contexts) == 2
        assert all(context.scope is CalibrationScope.REGION for context in contexts)
        assert resolve_pixel_spacing(ds) is None

    def test_imager_spacing_is_assumed_not_measured(self) -> None:
        ds = Dataset()
        ds.ImagerPixelSpacing = [0.2, 0.2]
        context = resolve_calibration_contexts(ds)[0]
        assert context.confidence is CalibrationConfidence.ASSUMED


class TestInvalidationAndPersistence:
    def test_recalibration_revision_makes_simpson_stale(self) -> None:
        contours = (
            Contour(phase="ed", view="A4C", points=[(1.0, 2.0), (4.0, 9.0), (6.0, 2.0)], measurement_id="ed"),
            Contour(phase="es", view="A4C", points=[(1.0, 2.0), (4.0, 9.0), (6.0, 2.0)], measurement_id="es"),
        )
        first = manual_calibration_context((0.1, 0.1), revision=1)
        second = invalidate_dependents(first)
        recorded = simpson_basis_from_contours(contours, first.spacing, calibration=first)
        current = simpson_basis_from_contours(contours, second.spacing, calibration=second)
        verdict = evaluate_simpson_freshness(recorded, current)
        assert verdict.reasons == (REASON_CALIBRATION_CHANGED,)

    def test_state_manager_bumps_manual_revision_and_clear_resets(self) -> None:
        manager = StateManager()
        manager.set_manual_pixel_spacing((0.1, 0.1), emit=False)
        assert manager.snapshot.calibration_revision == 1
        manager.set_manual_pixel_spacing((0.1, 0.1), emit=False)
        assert manager.snapshot.calibration_revision == 2
        manager.clear_manual_pixel_spacing()
        assert manager.snapshot.effective_calibration is None

    def test_store_activation_exposes_registered_calibration(self) -> None:
        store = StudyMeasurementSessionStore()
        context = manual_calibration_context((0.08, 0.08))
        store.set_instance_calibration("study", "1.2.3", context)
        store.activate_instance("study", "1.2.3")
        assert store.get("study").manual_calibration == context
        assert store.get("study").active_calibration == context

    def test_clearing_a_manual_override_restores_and_bumps_dicom_scale(self) -> None:
        store = StudyMeasurementSessionStore()
        dicom = _context((0.12, 0.12))
        store.set_instance_calibration("study", "1.2.3", dicom)
        store.set_instance_spacing("study", "1.2.3", (0.2, 0.2))
        store.set_instance_spacing("study", "1.2.3", None, fallback_calibration=dicom)
        restored = store.get_instance_calibration("study", "1.2.3")
        assert restored is not None and restored.source == "PixelSpacing"
        assert restored.revision == dicom.revision + 1
        assert store.get("study").manual_calibration is None
        assert store.get("study").manual_spacing_by_instance == ()

    def test_calibration_and_simpson_basis_round_trip(self) -> None:
        context = manual_calibration_context((0.1, 0.1), revision=3)
        basis = simpson_basis_from_contours(
            (Contour(phase="ed", view="A4C", points=[(1.0, 2.0), (4.0, 9.0), (6.0, 2.0)], measurement_id="ed"),),
            (0.1, 0.1),
            calibration=context,
        )
        data = StudyMeasurementData(
            calibration_by_instance=(("1.2.3", context),),
            simpson_basis=basis,
        )
        wire = json.loads(
            measurement_codec.dumps(
                dict(
                    format=measurement_codec.FORMAT,
                    schema_version=measurement_codec.VERSION,
                    measurement_semantics_version=measurement_codec.SEMANTICS_VERSION,
                    study_uid="1.2.3",
                    revision=1,
                    saved_at=datetime.now(_UTC).isoformat(),
                    sources={"1.2.3": {"fingerprint": "a" * 64, "frames": 2, "spacing": [0.1, 0.1]}},
                    data=data,
                )
            )
        )
        loaded = measurement_codec.loads(json.dumps(wire).encode())
        loaded_context = loaded["data"].calibration_by_instance[0][1]
        assert loaded_context.revision == 3
        assert loaded_context.source == "manual"
        assert loaded["data"].simpson_basis.calibration.signature() == context.signature()

    def test_record_simpson_basis_keeps_scoped_calibration(self) -> None:
        context = manual_calibration_context((0.1, 0.1), revision=2)
        data = StudyMeasurementData(
            contours=(
                Contour(
                    phase="ed",
                    view="A4C",
                    points=[(1.0, 2.0), (4.0, 9.0), (6.0, 2.0)],
                    sop_instance_uid="1.2.3",
                    measurement_id="ed",
                ),
            ),
            manual_calibration=context,
        )
        recorded = record_simpson_basis(data, {"1.2.3": {"spacing": [0.1, 0.1], "frames": 2}})
        assert recorded.simpson_basis.calibration == context

    def test_resolution_from_contexts_keeps_context(self) -> None:
        context = _context()
        resolution = resolution_from_contexts((context,))
        assert resolution.calibration == context
