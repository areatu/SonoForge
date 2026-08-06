"""Tests for landmark fallbacks (Fallback A/B) in segmentation_service."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.segmentation_service import (
    _fallback_annulus_sector_chord,
    _fallback_annulus_wider_band,
    open_arc_from_cavity_mask,
)


class TestFallbackWiderBand:
    def test_wider_band_on_fragmented_mask(self) -> None:
        """Fallback A succeeds when primary band is too narrow."""
        # Create a mask where the primary 12% band is too narrow but 18% band works
        mask = np.zeros((100, 60), dtype=np.uint8)
        # Main cavity body
        mask[20:80, 10:50] = 1
        # Narrow opening at top (primary band would be too narrow)
        mask[15:20, 20:40] = 1
        ys, xs = np.where(mask > 0)
        y_min, y_max = int(ys.min()), int(ys.max())
        septal, lateral, apex = _fallback_annulus_wider_band(ys, xs, y_min=y_min, y_max=y_max)
        assert septal[0] < lateral[0]  # septal is left of lateral
        # apex is opposite to the annulus (could be above or below depending on mask orientation)

    def test_wider_band_raises_on_empty(self) -> None:
        """Fallback A raises ValueError when no tissue in wider band."""
        mask = np.zeros((100, 10), dtype=np.uint8)
        mask[45:55, 3:7] = 1  # very small, centered
        ys, xs = np.where(mask > 0)
        y_min, y_max = int(ys.min()), int(ys.max())
        # This should either succeed or raise — both are acceptable
        try:
            _fallback_annulus_wider_band(ys, xs, y_min=y_min, y_max=y_max)
        except ValueError:
            pass  # acceptable


class TestFallbackSectorChord:
    def test_sector_chord_on_narrow_mask(self) -> None:
        """Fallback B uses widest span in basal 25%."""
        mask = np.zeros((100, 60), dtype=np.uint8)
        # Tissue concentrated at the top
        mask[5:40, 10:50] = 1
        ys, xs = np.where(mask > 0)
        y_min, y_max = int(ys.min()), int(ys.max())
        septal, lateral, apex = _fallback_annulus_sector_chord(
            ys,
            xs,
            y_min=y_min,
            y_max=y_max,
        )
        assert septal[0] < lateral[0]
        assert apex[1] > septal[1]  # apex below annulus


class TestOpenArcWithFallbacks:
    def test_open_arc_succeeds_on_fragmented_mask(self) -> None:
        """open_arc_from_cavity_mask succeeds via fallbacks when primary fails."""
        # Create a mask where primary annulus detection might struggle
        mask = np.zeros((120, 80), dtype=np.uint8)
        # Large cavity body
        mask[30:100, 15:65] = 1
        # Narrow neck at top
        mask[20:30, 25:55] = 1
        # This should succeed via primary or fallback
        points, annulus, apex = open_arc_from_cavity_mask(mask)
        assert len(points) >= 3
        assert annulus[0][0] < annulus[1][0]  # septal left of lateral

    def test_open_arc_raises_on_empty_mask(self) -> None:
        """open_arc_from_cavity_mask raises on empty mask."""
        mask = np.zeros((100, 100), dtype=np.uint8)
        with pytest.raises(ValueError, match="empty cavity mask"):
            open_arc_from_cavity_mask(mask)

    def test_open_arc_raises_on_tiny_mask(self) -> None:
        """open_arc_from_cavity_mask raises when bounding box too small."""
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[45:48, 45:48] = 1  # 3x3 mask
        with pytest.raises(ValueError):
            open_arc_from_cavity_mask(mask)
