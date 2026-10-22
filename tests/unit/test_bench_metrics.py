"""Tests for segmentation accuracy metrics (bench_metrics)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.bench_metrics import (
    aggregate_bench_results,
    annulus_endpoint_error,
    light_edit_accept,
    lvef_delta,
    lvef_reject_gate,
    mask_iou,
    zero_edit_accept,
)


class TestMaskIou:
    def test_identical_masks(self) -> None:
        mask = np.array([[0, 1, 1], [1, 1, 0]], dtype=np.uint8)
        assert mask_iou(mask, mask) == 1.0

    def test_disjoint_masks(self) -> None:
        a = np.array([[1, 0], [0, 0]], dtype=np.uint8)
        b = np.array([[0, 0], [0, 1]], dtype=np.uint8)
        assert mask_iou(a, b) == 0.0

    def test_partial_overlap(self) -> None:
        a = np.array([[1, 1, 0], [0, 0, 0]], dtype=np.uint8)
        b = np.array([[1, 0, 0], [0, 0, 0]], dtype=np.uint8)
        # inter=1, union=2 → 0.5
        assert abs(mask_iou(a, b) - 0.5) < 1e-6

    def test_both_empty(self) -> None:
        a = np.zeros((3, 3), dtype=np.uint8)
        b = np.zeros((3, 3), dtype=np.uint8)
        assert mask_iou(a, b) == 1.0


class TestAnnulusEndpointError:
    def test_identical(self) -> None:
        ann = ((10.0, 20.0), (30.0, 40.0))
        se, le = annulus_endpoint_error(ann, ann)
        assert se == 0.0
        assert le == 0.0

    def test_known_distance(self) -> None:
        pred = ((0.0, 0.0), (3.0, 4.0))
        gold = ((0.0, 0.0), (0.0, 0.0))
        se, le = annulus_endpoint_error(pred, gold)
        assert se == 0.0
        assert abs(le - 5.0) < 1e-6


class TestLvefDelta:
    def test_both_present(self) -> None:
        assert abs(lvef_delta(55.0, 50.0) - 5.0) < 1e-6

    def test_one_none(self) -> None:
        assert lvef_delta(None, 50.0) is None
        assert lvef_delta(55.0, None) is None


class TestZeroEditAccept:
    def test_low_lvef_delta(self) -> None:
        assert zero_edit_accept(3.0, 0.70) is True

    def test_high_lvef_delta_high_iou(self) -> None:
        assert zero_edit_accept(10.0, 0.85) is True

    def test_high_lvef_delta_low_iou(self) -> None:
        assert zero_edit_accept(10.0, 0.70) is False

    def test_none_lvef_high_iou(self) -> None:
        assert zero_edit_accept(None, 0.85) is True

    def test_none_lvef_low_iou(self) -> None:
        assert zero_edit_accept(None, 0.70) is False

    def test_zero_edit_from_pair_delta(self) -> None:
        """delta ≤ 5% → zero_edit even if IoU is low."""
        assert zero_edit_accept(3.0, 0.65) is True


class TestLightEditAccept:
    def test_zero_edits(self) -> None:
        assert light_edit_accept(3.0, 0.70, 0) is True

    def test_two_edits(self) -> None:
        assert light_edit_accept(3.0, 0.70, 2) is True

    def test_three_edits(self) -> None:
        assert light_edit_accept(3.0, 0.70, 3) is False


class TestLvefRejectGate:
    def test_reject_when_delta_high(self) -> None:
        assert lvef_reject_gate(20.0) is True

    def test_accept_when_delta_low(self) -> None:
        assert lvef_reject_gate(10.0) is False

    def test_accept_when_delta_none(self) -> None:
        assert lvef_reject_gate(None) is False

    def test_custom_threshold(self) -> None:
        assert lvef_reject_gate(8.0, threshold=5.0) is True
        assert lvef_reject_gate(4.0, threshold=5.0) is False


class TestAggregateResults:
    def test_empty_rows(self) -> None:
        result = aggregate_bench_results([])
        assert result["total"] == 0
        assert result["median_iou"] is None

    def test_single_row(self) -> None:
        rows = [
            {
                "iou": 0.85,
                "septal_err": 3.0,
                "lateral_err": 4.0,
                "lvef_delta": 2.0,
                "zero_edit": True,
                "light_edit": True,
                "reject": False,
            }
        ]
        result = aggregate_bench_results(rows)
        assert result["total"] == 1
        assert result["median_iou"] == 0.85
        assert result["zero_edit_rate"] == 1.0
        assert result["reject_rate"] == 0.0

    def test_mixed_rows(self) -> None:
        rows = [
            {
                "iou": 0.90,
                "septal_err": 2.0,
                "lateral_err": 3.0,
                "lvef_delta": 1.0,
                "zero_edit": True,
                "light_edit": True,
                "reject": False,
            },
            {
                "iou": 0.50,
                "septal_err": 8.0,
                "lateral_err": 9.0,
                "lvef_delta": 8.0,
                "zero_edit": False,
                "light_edit": False,
                "reject": True,
            },
        ]
        result = aggregate_bench_results(rows)
        assert result["total"] == 2
        assert result["reject_rate"] == 0.5
        assert result["zero_edit_rate"] == 0.5
