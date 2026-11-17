"""Synthetic research IMT acceptance, not vendor/clinical validation (#558)."""

from dataclasses import replace

import numpy as np
import pytest

from echo_personal_tool.application.imt import correct_imt, propose_imt
from echo_personal_tool.domain.measurement_catalog import measurement_for_caliper
from echo_personal_tool.domain.models.calibration import (
    CalibrationConfidence,
    CalibrationContext,
    CalibrationRegion,
    CalibrationScope,
)
from echo_personal_tool.domain.models.imt import ImtPolicy, ImtRefusal, ImtSource
from echo_personal_tool.domain.services.imt_geometry import measure_boundaries


@pytest.fixture
def source():
    return ImtSource(
        study_uid="study",
        instance_uid="sop",
        generation=1,
        frame_index=2,
        frame_count=10,
        side="R",
        phase="operator_selected",
        roi=(0, 0, 96, 64),
        calibration=CalibrationContext((0.1, 0.2), source="PixelSpacing"),
    )


@pytest.fixture
def policy():
    # These are synthetic phantom settings, not a recommendation for patients.
    return ImtPolicy(0.3, 1.5, 0.75, 0.05)


def _lines(offset=8.0, slope=0.0):
    xs = np.linspace(2, 93, 92)
    return (
        tuple((float(x), float(15 + slope * x)) for x in xs),
        tuple((float(x), float(15 + slope * x + offset)) for x in xs),
    )


def _frame():
    # Bright intimal stripe, darker media, bright adventitia, dark lumen.
    image = np.full((64, 96), 10.0)
    image[20:23] = 140.0
    image[23:28] = 40.0
    image[28:] = 220.0
    return image


def test_horizontal_normals_and_population_statistics(source, policy):
    draft = measure_boundaries(source, policy, *_lines(), np.ones((64, 96)))
    assert draft.mean_mm == pytest.approx(0.8)
    assert draft.max_mm == pytest.approx(0.8)
    assert draft.sd_mm == pytest.approx(0)
    assert draft.coverage == 1
    assert draft.sampled_length_mm == pytest.approx(91 * 0.2)
    assert len(draft.accepted_sample_indices) == len(draft.distances_mm)
    assert not draft.confirmed


@pytest.mark.parametrize("spacing,slope", [((0.1, 0.2), 0.3), ((0.2, 0.1), 0.2), ((0.1, 0.1), -0.1)])
def test_tilted_anisotropic_wall_uses_physical_normals_not_vertical_gap(source, policy, spacing, slope):
    source = replace(source, calibration=CalibrationContext(spacing, source="phantom"))
    physical_slope = slope * spacing[0] / spacing[1]
    offset = 0.8 * np.sqrt(1 + physical_slope**2) / spacing[0]
    draft = measure_boundaries(source, policy, *_lines(offset, slope), np.ones((64, 96)))
    assert draft.mean_mm == pytest.approx(0.8, abs=1e-8)
    assert draft.sd_mm < 1e-8
    assert offset * spacing[0] > draft.mean_mm


def test_shadow_remains_visible_in_coverage_and_can_refuse_a_mean(source, policy):
    evidence = np.ones((64, 96))
    evidence[:, 30:48] = 0
    draft = measure_boundaries(source, replace(policy, min_coverage=0.5), *_lines(), evidence)
    assert 0.7 < draft.coverage < 0.9
    assert draft.mean_mm == pytest.approx(0.8)
    with pytest.raises(ImtRefusal, match="insufficient_quality_coverage"):
        measure_boundaries(source, replace(policy, min_coverage=0.95), *_lines(), evidence)


@pytest.mark.parametrize("confidence", [CalibrationConfidence.ASSUMED, CalibrationConfidence.UNKNOWN])
def test_untrusted_scale_is_refused(source, confidence):
    with pytest.raises(ImtRefusal, match="unverified_calibration"):
        replace(source, calibration=replace(source.calibration, confidence=confidence))


def test_frame_and_region_scale_scopes_are_enforced(source):
    with pytest.raises(ImtRefusal, match="calibration_scope_mismatch"):
        replace(source, calibration=replace(source.calibration, scope=CalibrationScope.FRAME, frame_index=1))
    valid_frame = replace(source.calibration, scope=CalibrationScope.FRAME, frame_index=2)
    assert replace(source, calibration=valid_frame).calibration == valid_frame
    invalid_region = replace(source.calibration, scope=CalibrationScope.REGION, region=CalibrationRegion(0, 90, 0, 64))
    with pytest.raises(ImtRefusal, match="calibration_scope_mismatch"):
        replace(source, calibration=invalid_region)
    frame_region = replace(
        source.calibration, scope=CalibrationScope.REGION, frame_index=1, region=CalibrationRegion(0, 96, 0, 64)
    )
    with pytest.raises(ImtRefusal, match="calibration_scope_mismatch"):
        replace(source, calibration=frame_region)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"clip_mode": "doppler"}, "bmode_required"),
        ({"side": "unknown"}, "invalid_context"),
        ({"phase": ""}, "invalid_context"),
        ({"segment": "plaque"}, "invalid_context"),
        ({"frame_index": 10}, "invalid_source"),
        ({"roi": (0, 0, 600, 64)}, "roi_too_large"),
        ({"roi": (0, 0, 2, 64)}, "invalid_roi"),
    ],
)
def test_invalid_context_is_refused(source, change, code):
    with pytest.raises(ImtRefusal, match=code):
        replace(source, **change)


@pytest.mark.parametrize("kind", ["cross", "reverse", "nan", "outside", "nonmonotone", "span"])
def test_invalid_boundaries_do_not_produce_a_number(source, policy, kind):
    li, ma = _lines()
    if kind == "cross":
        ma = tuple((x, 14 + (x - 2) / 10) for x, _ in ma)
    elif kind == "reverse":
        li, ma = ma, li
    elif kind == "nan":
        li = ((float("nan"), 15), *li[1:])
    elif kind == "outside":
        li = ((-1, 15), *li[1:])
    elif kind == "nonmonotone":
        li = tuple(reversed(li))
    else:
        ma = ma[1:]
    with pytest.raises(ImtRefusal):
        measure_boundaries(source, policy, li, ma, np.ones((64, 96)))


def test_insufficient_normal_resolution_is_refused(source, policy):
    with pytest.raises(ImtRefusal, match="insufficient_quality_coverage"):
        measure_boundaries(source, replace(policy, min_thickness_mm=0.01), *_lines(offset=1), np.ones((64, 96)))


def test_seeded_proposal_is_subpixel_and_does_not_mutate_frame(source, policy):
    image = _frame()
    image.flags.writeable = False
    before = image.copy()
    draft = propose_imt(image, source, policy, lumen_y=20, adventitia_y=28)
    assert not draft.confirmed
    assert draft.mean_mm == pytest.approx(0.8, abs=0.02)
    assert draft.coverage > 0.95
    assert any(y != int(y) for _, y in draft.lumen_intima)
    np.testing.assert_array_equal(image, before)


def test_correction_recomputes_statistics_and_revokes_confirmation(source, policy):
    image = _frame()
    original = propose_imt(image, source, policy, lumen_y=20, adventitia_y=28).confirm(source)
    corrected = correct_imt(
        original,
        source,
        image,
        lumen_intima=original.lumen_intima,
        media_adventitia=original.media_adventitia,
    )
    assert original.confirmed
    assert not corrected.confirmed
    assert corrected.revision == original.revision + 1
    assert corrected.mean_mm == pytest.approx(original.mean_mm)
    with pytest.raises(ImtRefusal, match="confirmation_required"):
        corrected.report_record(source)


@pytest.mark.parametrize("kind", ["blank", "nan", "colour", "cropped"])
def test_unusable_images_refuse_instead_of_finding_plausible_lines(source, policy, kind):
    image = _frame()
    if kind == "blank":
        image[:] = 0
    elif kind == "nan":
        image[25, 25] = np.nan
    elif kind == "colour":
        image = np.stack([image] * 3, axis=-1)
    else:
        image = image[:30]
    with pytest.raises(ImtRefusal):
        propose_imt(image, source, policy, lumen_y=20, adventitia_y=28)


@pytest.mark.parametrize("hints", [(28, 20), (-1, 28), (20, 64), (float("nan"), 28)])
def test_invalid_hints_refuse(source, policy, hints):
    with pytest.raises(ImtRefusal, match="invalid_boundary_hints"):
        propose_imt(_frame(), source, policy, lumen_y=hints[0], adventitia_y=hints[1])


@pytest.mark.parametrize(
    "change",
    [
        {"frame_index": 3},
        {"generation": 2},
        {"side": "L"},
        {"instance_uid": "other"},
        {"study_uid": "other"},
        {"roi": (1, 0, 96, 64)},
    ],
)
def test_stale_draft_cannot_be_corrected_confirmed_or_exported(source, policy, change):
    draft = propose_imt(_frame(), source, policy, lumen_y=20, adventitia_y=28)
    current = replace(source, **change)
    with pytest.raises(ImtRefusal, match="stale_draft"):
        draft.confirm(current)
    with pytest.raises(ImtRefusal, match="stale_draft"):
        draft.confirm(source).report_record(current)
    with pytest.raises(ImtRefusal, match="stale_draft"):
        correct_imt(draft, current, _frame(), lumen_intima=draft.lumen_intima, media_adventitia=draft.media_adventitia)


def test_same_scale_new_revision_is_stale_and_export_keeps_provenance(source, policy):
    draft = propose_imt(_frame(), source, policy, lumen_y=20, adventitia_y=28)
    current = replace(source, calibration=replace(source.calibration, revision=1))
    with pytest.raises(ImtRefusal, match="stale_draft"):
        draft.confirm(current)
    record = draft.confirm(source).report_record(source)
    assert record["calibration"] == source.calibration.signature()
    assert record["research_only"] is True
    assert record["policy"]["min_coverage"] == policy.min_coverage
    assert record["caliper_label"] == "IMT-R"
    assert record["measurement_key"] == measurement_for_caliper("IMT-R")
    left = replace(source, side="L")
    assert left.measurement_key == measurement_for_caliper("IMT-L")


@pytest.mark.parametrize(
    "change",
    [
        {"min_thickness_mm": 0},
        {"max_thickness_mm": float("inf")},
        {"min_coverage": 0},
        {"min_edge_contrast": 0},
        {"max_step_px": 1.5},
        {"search_radius_px": 1.5},
    ],
)
def test_invalid_research_policies_are_refused(policy, change):
    with pytest.raises(ImtRefusal):
        replace(policy, **change)


@pytest.mark.parametrize("slope", [0.05, 0.15, 0.3])
def test_seeded_detection_on_rasterised_tilted_phantom(source, policy, slope):
    y, x = np.indices((64, 96))
    gap = 0.8 * np.sqrt(1 + (slope * 0.1 / 0.2) ** 2) / 0.1
    first = 18 + slope * x
    image = np.where(y < first, 10, np.where(y < first + 3, 140, np.where(y < first + gap, 40, 220)))
    draft = propose_imt(
        image,
        source,
        policy,
        lumen_y=(18.0, 18 + 95 * slope),
        adventitia_y=(18 + gap, 18 + 95 * slope + gap),
    )
    # Rasterisation tolerance of this synthetic fixture, not a clinical limit.
    assert draft.mean_mm == pytest.approx(0.8, abs=0.03)
    assert draft.coverage > 0.95


@pytest.mark.parametrize("seed", range(5))
def test_random_texture_does_not_pass_this_phantom_policy(source, policy, seed):
    texture = np.random.default_rng(seed).normal(100, 10, (64, 96))
    with pytest.raises(ImtRefusal, match="insufficient_quality_coverage|boundaries_cross_or_reversed"):
        propose_imt(texture, source, policy, lumen_y=20, adventitia_y=28)


def test_failed_correction_does_not_change_accepted_original(source, policy):
    original = propose_imt(_frame(), source, policy, lumen_y=20, adventitia_y=28).confirm(source)
    with pytest.raises(ImtRefusal, match="boundaries_cross_or_reversed"):
        correct_imt(
            original, source, _frame(), lumen_intima=original.media_adventitia, media_adventitia=original.lumen_intima
        )
    assert original.confirmed
    assert original.revision == 0


def test_research_record_is_json_serializable_and_preserves_both_lines(source, policy):
    import json

    result = propose_imt(_frame(), source, policy, lumen_y=20, adventitia_y=28).confirm(source)
    record = json.loads(json.dumps(result.report_record(source), allow_nan=False))
    assert len(record["lumen_intima"]) == 96
    assert len(record["media_adventitia"]) == 96
    assert record["accepted_samples"] == len(record["accepted_sample_indices"])
    assert record["accepted_samples"] == len(record["distances_mm"])
    assert record["phase"] == "operator_selected"


def test_missing_calibration_has_an_explicit_refusal(source):
    with pytest.raises(ImtRefusal, match="calibration_required"):
        replace(source, calibration=None)


def test_no_result_when_an_edge_is_missing(source, policy):
    image = _frame()
    image[23:] = 40  # only the first positive interface remains
    with pytest.raises(ImtRefusal):
        propose_imt(image, source, policy, lumen_y=20, adventitia_y=28)


def test_roi_coordinates_are_full_frame_not_crop_relative(source, policy):
    image = np.zeros((100, 140))
    image[10:74, 20:116] = _frame()
    source = replace(source, roi=(20, 10, 116, 74))
    draft = propose_imt(image, source, policy, lumen_y=30, adventitia_y=38)
    assert draft.mean_mm == pytest.approx(0.8, abs=0.02)
    assert draft.lumen_intima[0][0] == 20
    assert draft.lumen_intima[0][1] == pytest.approx(29.5, abs=0.5)


def test_detector_evidence_is_intensity_affine_invariant(source):
    from echo_personal_tool.domain.services.imt_detection import edge_evidence

    original = edge_evidence(_frame(), source)
    high_bit_depth = edge_evidence((_frame() * 2048 + 17).astype(np.uint32), source)
    np.testing.assert_allclose(original, high_bit_depth, atol=1e-12)


def test_impossible_guide_jump_refuses_instead_of_returning_an_inf_cost_path(source, policy):
    from echo_personal_tool.domain.services.imt_detection import detect_boundaries

    source = replace(source, roi=(0, 0, 8, 256))
    with pytest.raises(ImtRefusal, match="no_continuous_boundary"):
        detect_boundaries(
            np.ones((256, 8)),
            source,
            replace(policy, search_radius_px=1),
            lumen_y=(10.0, 200.0),
            adventitia_y=(20.0, 220.0),
        )
