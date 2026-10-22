"""Tests for LA mask→contour + quality gate (synthetic masks)."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.la_segmentation_service import (
    explain_la_auto_reject_reason,
    la_mask_to_contour,
)


def _ellipse_mask(
    cy: int,
    cx: int,
    ry: int,
    rx: int,
    shape: tuple[int, int] = (224, 224),
) -> np.ndarray:
    """Synthetic filled ellipse mask (simulates LA cavity on A4C)."""
    mask = np.zeros(shape, dtype=np.uint8)
    y_grid, x_grid = np.ogrid[: shape[0], : shape[1]]
    ((y_grid - cy) / max(ry, 1)) ** 2 + ((x_grid - cx) / max(rx, 1)) ** 2 <= 1.0
    inside = ((y_grid - cy) / max(ry, 1)) ** 2 + ((x_grid - cx) / max(rx, 1)) ** 2 <= 1.0
    mask[inside] = 1
    return mask


def _make_contour(
    points: list[tuple[float, float]],
    ma: tuple[tuple[float, float], tuple[float, float]] | None = None,
    apex: tuple[float, float] | None = None,
    chamber: str = "LA",
) -> Contour:
    return Contour(
        phase="ES",
        view="A4C",
        chamber=chamber,
        points=points,
        mitral_annulus=ma,
        apex_landmark=apex,
        source="model",
    )


# ---------------------------------------------------------------------------
# la_mask_to_contour — synthetic masks
# ---------------------------------------------------------------------------


class TestLaMaskToContour:
    def test_ellipse_produces_valid_open_arc(self) -> None:
        mask = _ellipse_mask(cy=140, cx=112, ry=50, rx=40)
        points, (septal, lateral), apex = la_mask_to_contour(mask)

        assert len(points) == 32
        # Endpoints match MV landmarks
        assert points[0] == pytest.approx(septal, abs=0.5)
        assert points[-1] == pytest.approx(lateral, abs=0.5)
        # Septal is left of lateral
        assert septal[0] < lateral[0]

    def test_ellipse_apex_above_ma(self) -> None:
        """Roof apex should be above (smaller Y) the MV chord midpoint."""
        mask = _ellipse_mask(cy=130, cx=112, ry=50, rx=35)
        _, (septal, lateral), apex = la_mask_to_contour(mask)

        ma_mid_y = (septal[1] + lateral[1]) / 2.0
        assert apex[1] < ma_mid_y

    def test_empty_mask_raises(self) -> None:
        mask = np.zeros((224, 224), dtype=np.uint8)
        with pytest.raises(ValueError, match="empty"):
            la_mask_to_contour(mask)

    def test_custom_num_nodes(self) -> None:
        mask = _ellipse_mask(cy=140, cx=112, ry=50, rx=40)
        points, _, _ = la_mask_to_contour(mask, num_nodes=16)
        assert len(points) == 16

    def test_small_mask_still_works(self) -> None:
        mask = _ellipse_mask(cy=112, cx=112, ry=20, rx=15)
        points, _, _ = la_mask_to_contour(mask)
        assert len(points) == 32

    def test_very_small_mask_raises(self) -> None:
        mask = np.zeros((224, 224), dtype=np.uint8)
        mask[110:114, 110:114] = 1  # 4×4 pixels — too small for landmarks
        with pytest.raises(ValueError):
            la_mask_to_contour(mask)

    def test_asymmetric_ellipse(self) -> None:
        """Non-square ellipse still produces valid landmarks."""
        mask = _ellipse_mask(cy=150, cx=112, ry=60, rx=25)
        points, (septal, lateral), apex = la_mask_to_contour(mask)
        assert len(points) == 32
        assert septal[0] < lateral[0]

    def test_la_chamber_in_result(self) -> None:
        """The contour should be usable with chamber=LA in fit_contour_from_landmarks."""
        from echo_personal_tool.domain.services.mbs_lite_service import fit_contour_from_landmarks

        mask = _ellipse_mask(cy=140, cx=112, ry=50, rx=40)
        _, (septal, lateral), apex = la_mask_to_contour(mask)
        contour = fit_contour_from_landmarks(
            septal=septal,
            lateral=lateral,
            apex=apex,
            phase="ES",
            view="A4C",
            chamber="LA",
        )
        assert contour.chamber == "LA"
        assert len(contour.points) == 32


# ---------------------------------------------------------------------------
# explain_la_auto_reject_reason — quality gate
# ---------------------------------------------------------------------------


class TestExplainLaAutoRejectReason:
    def test_valid_contour_passes(self) -> None:
        pts = [
            (80.0, 180.0),
            (100.0, 130.0),
            (120.0, 100.0),
            (140.0, 80.0),
            (160.0, 100.0),
            (180.0, 130.0),
            (200.0, 180.0),
        ]
        ma = ((80.0, 180.0), (200.0, 180.0))
        apex = (140.0, 80.0)
        c = _make_contour(pts, ma=ma, apex=apex)
        assert explain_la_auto_reject_reason(c, (0.15, 0.15)) is None

    def test_no_annulus_rejects(self) -> None:
        c = _make_contour([(0, 0), (1, 1), (2, 2)])
        assert explain_la_auto_reject_reason(c, None) is not None

    def test_tiny_mv_span_rejects(self) -> None:
        c = _make_contour(
            [(100, 180), (101, 150), (100, 120)],
            ma=((100.0, 180.0), (100.5, 180.0)),
            apex=(100, 120),
        )
        reason = explain_la_auto_reject_reason(c, None)
        assert reason is not None

    def test_mv_span_mm_too_small_rejects(self) -> None:
        c = _make_contour(
            [(100, 180), (105, 150), (110, 120)],
            ma=((100.0, 180.0), (110.0, 180.0)),
            apex=(105, 120),
        )
        # 10px * 0.15mm/px = 1.5mm < 3mm threshold
        reason = explain_la_auto_reject_reason(c, (0.15, 0.15))
        assert reason is not None
        assert "мало" in reason

    def test_inverted_geometry_rejects(self) -> None:
        """Apex below MV chord → inverted LA."""
        c = _make_contour(
            [(80, 100), (140, 80), (200, 100)],
            ma=((80.0, 100.0), (200.0, 100.0)),
            apex=(140, 200),  # below MA
        )
        reason = explain_la_auto_reject_reason(c, None)
        assert reason is not None
        assert "инвертирована" in reason

    def test_centroid_outside_roi_rejects(self) -> None:
        pts = [(80, 180), (100, 130), (120, 100), (140, 80), (160, 100), (180, 130), (200, 180)]
        ma = ((80.0, 180.0), (200.0, 180.0))
        apex = (140.0, 80.0)
        c = _make_contour(pts, ma=ma, apex=apex)
        # ROI far away from contour
        reason = explain_la_auto_reject_reason(c, None, roi_xyxy=(0, 0, 10, 10))
        assert reason is not None
        assert "ROI" in reason

    def test_ellipse_residual_passes_for_matching_mask(self) -> None:
        mask = _ellipse_mask(cy=140, cx=112, ry=50, rx=40)
        points, ma, apex = la_mask_to_contour(mask)
        c = _make_contour(points, ma=ma, apex=apex)
        assert explain_la_auto_reject_reason(c, (0.15, 0.15), mask=mask) is None

    def test_ellipse_residual_rejects_irregular_mask(self) -> None:
        mask = _ellipse_mask(cy=140, cx=112, ry=50, rx=40)
        points, ma, apex = la_mask_to_contour(mask)
        c = _make_contour(points, ma=ma, apex=apex)
        irregular = mask.copy()
        irregular[40:90, 40:90] = 1
        reason = explain_la_auto_reject_reason(c, None, mask=irregular)
        assert reason is not None
        assert "нерегулярна" in reason
