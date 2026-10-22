"""Lightweight integration tests for run_lv_auto_bench."""

from __future__ import annotations

from echo_personal_tool.domain.services.bench_metrics import zero_edit_accept


class TestZeroEditFromPairDelta:
    """Verify zero_edit integration in bench context."""

    def test_zero_edit_when_delta_low(self) -> None:
        assert zero_edit_accept(3.0, 0.65) is True

    def test_zero_edit_when_iou_high(self) -> None:
        assert zero_edit_accept(10.0, 0.85) is True

    def test_no_zero_edit_when_both_high(self) -> None:
        assert zero_edit_accept(10.0, 0.70) is False
