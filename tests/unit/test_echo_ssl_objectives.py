"""ML.4 pure-core phase, NCC, motion, reservoir and held-out acceptance gates."""

from dataclasses import replace

import cv2
import numpy as np
import pytest

from echo_personal_tool.domain.services.echo_ssl_objectives import (
    candidate_reject_reasons,
    cycle_triplets,
    cycle_view_loss,
    ncc_weights,
    phase_shape_weights,
    physiology_terms,
    trusted_cycles,
    warp_consistency_loss,
)
from echo_personal_tool.domain.services.echo_ssl_tracking import track_ssl_nodes
from echo_personal_tool.domain.services.phase_field import PhaseField, PhaseFieldCycle, build_phase_field


def field(confidence=0.9):
    return PhaseField(
        24,
        40.0,
        np.tile(np.arange(12) / 12, 2),
        (0, 12),
        (5, 17),
        (PhaseFieldCycle(0, 5, 12, 0.9), PhaseFieldCycle(12, 17, 24, 0.9)),
        "synthetic",
        12.0,
        confidence,
    )


def curves():
    contraction = phase_shape_weights(field())
    return {"LV": 100 - 30 * contraction, "RV": 80 - 20 * contraction, "LA": 40 + 15 * contraction}


def test_ventricular_and_la_reservoir_have_opposite_order_at_measured_es():
    areas = curves()
    assert physiology_terms(areas, field()) == {"ventricles": 0.0, "la_reservoir": 0.0, "landmark_motion": 0.0}
    wrong = {**areas, "LA": 100 - 30 * phase_shape_weights(field())}
    assert physiology_terms(wrong, field())["la_reservoir"] > 0.1
    wrong = {**areas, "LV": 200 - areas["LV"], "RV": 200 - areas["RV"]}
    assert physiology_terms(wrong, field())["ventricles"] > 0.1
    assert cycle_triplets(field()) == ((0, 2, 5), (12, 14, 17))
    weights = phase_shape_weights(field())
    assert weights[0] == 0 and weights[5] == 1 and weights[12] == 0


@pytest.mark.parametrize("confidence", [0.0, 0.599, np.nan, np.inf, 1.1])
def test_low_or_invalid_confidence_is_exactly_zero_even_for_nonsensical_curves(confidence):
    rejected = field(confidence)
    assert not trusted_cycles(rejected) and phase_shape_weights(rejected) is None
    assert all(value == 0 for value in physiology_terms({"LA": np.array([np.nan])}, rejected).values())


def test_partial_and_invalid_phase_cycles_cannot_become_physiology_targets():
    original = field()
    partial = replace(original, cycles=tuple(replace(c, partial=True) for c in original.cycles))
    assert not trusted_cycles(partial)
    assert not trusted_cycles(replace(original, phi=np.full(24, np.nan)))
    assert not trusted_cycles(replace(original, phi=np.tile(np.arange(12)[::-1] / 12, 2)))
    missing = replace(original, cycles=(original.cycles[1],))
    assert np.isnan(phase_shape_weights(missing)[:12]).all()
    assert len(trusted_cycles(missing)) == 1


def test_kinematic_bounds_use_real_time_and_are_also_phase_gated():
    points = np.zeros((24, 2, 2))
    points[3] = 10.0
    assert physiology_terms(curves(), field(), landmarks=points)["landmark_motion"] > 0
    assert physiology_terms(curves(), replace(field(), frame_time_ms=None), landmarks=points)["landmark_motion"] == 0
    assert physiology_terms(curves(), field(0.1), landmarks=points)["landmark_motion"] == 0
    with pytest.raises(ValueError):
        physiology_terms({"RV": np.zeros(24)}, field())


def test_ncc_round_trip_and_masked_nan_targets_are_fail_closed():
    scores = np.array([0.65, 0.649, 1.0, np.nan, 1.1, 0.9])
    quality = ncc_weights(scores, np.array([1.5, 0, 0, 0, 0, 1.51]))
    np.testing.assert_allclose(quality, [0.65, 0, 1, 0, 0, 0])
    pred = np.array([[1.0, 2.0], [np.nan, np.nan]])
    target = np.array([[4.0, 6.0], [np.nan, np.nan]])
    assert warp_consistency_loss(pred, target, np.array([1.0, 0.0])) == 5.0
    assert warp_consistency_loss(pred, target, np.zeros(2)) == 0.0
    with pytest.raises(ValueError):
        warp_consistency_loss(pred, target, np.ones(2))
    with pytest.raises(ValueError):
        ncc_weights(np.ones(2), np.ones(3))


def test_existing_speckle_tracker_translates_textured_nodes_but_not_flat_dropout():
    rng = np.random.default_rng(692)
    reference = rng.uniform(0, 1, (96, 96)).astype(np.float32)
    target = cv2.warpAffine(reference, np.array([[1.0, 0.0, 2.0], [0.0, 1.0, 1.0]]), (96, 96))
    points = np.array([[30.0, 30.0], [45.0, 45.0], [60.0, 60.0]])
    warp = track_ssl_nodes(reference, target, points)
    assert (warp.weights >= 0.65).all()
    np.testing.assert_allclose(warp.positions - points, np.tile([2, 1], (3, 1)), atol=0.3)
    assert np.max(warp.closure_error) < 0.3
    assert not track_ssl_nodes(np.zeros((32, 32)), np.zeros((32, 32)), np.array([[16.0, 16.0]])).weights.any()
    sector = np.ones((96, 96), bool)
    sector[20:40, 20:40] = False
    assert track_ssl_nodes(reference, target, points, reference_sector=sector).weights[0] == 0
    assert not track_ssl_nodes(reference, target, np.array([[np.nan, 2.0], [0.0, 0.0]])).weights.any()


def test_image_phase_builder_is_used_without_external_labels_or_clock_extrapolation():
    areas = 100 + 20 * np.cos(2 * np.pi * np.arange(72) / 12)
    result = build_phase_field(area_curve=areas, frame_time_ms=40.0, min_confidence=0.6)
    assert result.confidence >= 0.6 and trusted_cycles(result)
    assert all(not c.partial for c in result.cycles if any(t.ed == c.ed_frame for t in trusted_cycles(result)))


def test_cycle_view_consistency_and_acceptance_need_real_held_out_evidence():
    a = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert cycle_view_loss(a, a) == 0.0
    assert cycle_view_loss(a, -a) == 2.0
    before, after = {"LA": 2.0, "RV": 3.0}, {"LA": 1.0, "RV": 2.0}
    gold = {"LV_iou": 0.9, "LA_iou": 0.85, "RV_iou": 0.8, "node_error_px": 1.0, "frames": 6.0}
    assert candidate_reject_reasons(before, after, gold, gold) == ()
    assert "missing_rv_jitter" in candidate_reject_reasons(before, {**after, "RV": None}, gold, gold)
    assert "la_jitter_not_improved" in candidate_reject_reasons(before, {**after, "LA": 2.0}, gold, gold)
    assert "la_iou_degraded" in candidate_reject_reasons(before, after, gold, {**gold, "LA_iou": 0.7})
    assert "gold_nodes_degraded" in candidate_reject_reasons(before, after, gold, {**gold, "node_error_px": 2.0})
    assert "invalid_gold_coverage" in candidate_reject_reasons(before, after, gold, {**gold, "frames": 5.0})
    assert "incomplete_gold" in candidate_reject_reasons(before, after, {}, {})
