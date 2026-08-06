"""Tests for ROI v2 (apex guard on sector trim)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.segment_roi import (
    _trim_sector_content_bounds,
)


class TestApexGuard:
    def test_trim_no_guard_allows_large_removal(self) -> None:
        """Without guard, trim proceeds even if >15% removed."""
        frame = np.zeros((100, 100), dtype=np.uint8)
        frame[40:60, 20:80] = 200  # small tissue band in center
        roi = (0.0, 0.0, 100.0, 100.0)
        result = _trim_sector_content_bounds(frame, roi, apex_guard=False)
        # Trim should succeed (no guard)
        assert result[1] >= 30  # y0 moved down
        assert result[3] <= 70  # y1 moved up

    def test_trim_with_guard_aborts_when_large_removal(self) -> None:
        """With guard, trim aborts if >15% of height is removed."""
        frame = np.zeros((100, 100), dtype=np.uint8)
        frame[45:55, 20:80] = 200  # very small tissue — trim would remove >15%
        roi = (0.0, 0.0, 100.0, 100.0)
        result = _trim_sector_content_bounds(frame, roi, apex_guard=True)
        # Guard should abort — return original ROI
        assert result == roi

    def test_trim_with_guard_allows_small_removal(self) -> None:
        """With guard, trim proceeds if <=15% removed and apex band has tissue."""
        frame = np.zeros((100, 100), dtype=np.uint8)
        frame[10:90, 10:90] = 150  # large tissue — trim removes <15%
        roi = (0.0, 0.0, 100.0, 100.0)
        result = _trim_sector_content_bounds(frame, roi, apex_guard=True)
        # Should trim normally
        assert result != roi

    def test_trim_with_guard_aborts_when_apex_band_empty(self) -> None:
        """With guard, trim aborts if apex band has no tissue."""
        frame = np.zeros((100, 100), dtype=np.uint8)
        # Tissue only in bottom half — apex (top) band is empty
        frame[50:90, 10:90] = 200
        roi = (0.0, 0.0, 100.0, 100.0)
        result = _trim_sector_content_bounds(frame, roi, apex_guard=True)
        # Apex band (top 12% of original height) is empty → abort
        assert result == roi

    def test_guard_max_removal_ratio_parameter(self) -> None:
        """Custom removal ratio threshold works."""
        frame = np.zeros((100, 100), dtype=np.uint8)
        frame[30:70, 10:90] = 200  # removes ~30%
        roi = (0.0, 0.0, 100.0, 100.0)
        # With 50% threshold, should allow trim
        result = _trim_sector_content_bounds(
            frame,
            roi,
            apex_guard=True,
            apex_guard_max_removal_ratio=0.50,
        )
        assert result != roi
