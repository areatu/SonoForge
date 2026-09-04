"""Tests for quality gate v2 (spacing-aware MA, arc depth, centroid)."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.lvef_simpson import (
    _contour_arc_depth_px,
    _contour_centroid,
    explain_lv_auto_reject_reason,
)
from echo_personal_tool.domain.models.contour import Contour


def _make_contour(
    *,
    points: list[tuple[float, float]] | None = None,
    mitral_annulus: tuple[tuple[float, float], tuple[float, float]] | None = ((0, 30), (20, 30)),
    apex_landmark: tuple[float, float] | None = (10, 0),
) -> Contour:
    if points is None:
        points = [(0, 30), (10, 0), (20, 30)]
    return Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        points=points,
        mitral_annulus=mitral_annulus,
        apex_landmark=apex_landmark,
    )


class TestExplainRejectV2:
    def test_valid_contour_passes(self) -> None:
        contour = _make_contour()
        # MA=20px * 0.3mm/px = 6mm >= 5mm
        assert explain_lv_auto_reject_reason(contour, (0.3, 0.3)) is None

    def test_no_annulus_rejects(self) -> None:
        contour = _make_contour(mitral_annulus=None)
        assert "не построен" in explain_lv_auto_reject_reason(contour, None)

    def test_small_annulus_mm_rejects(self) -> None:
        """MA length < 5mm with spacing-aware check."""
        # MA length = 25px, spacing = 0.1 mm/px → 2.5mm < 5mm
        # 25px >= 20px px threshold, so passes px check
        contour = _make_contour(
            points=[(0, 30), (12, 0), (25, 30)],
            mitral_annulus=((0, 30), (25, 30)),
            apex_landmark=(12, 0),
        )
        reason = explain_lv_auto_reject_reason(contour, (0.1, 0.1))
        assert reason is not None
        assert "мм" in reason

    def test_large_annulus_mm_passes(self) -> None:
        """MA length >= 5mm passes."""
        # MA length = 40px, spacing = 0.15 mm/px → 6mm >= 5mm
        contour = _make_contour(
            points=[(0, 40), (20, 0), (40, 40)],
            mitral_annulus=((0, 40), (40, 40)),
            apex_landmark=(20, 0),
        )
        reason = explain_lv_auto_reject_reason(contour, (0.15, 0.15))
        # Should pass the MA check (may fail other checks)
        assert "мм" not in (reason or "")

    def test_flat_contour_rejects(self) -> None:
        """Arc depth < 15% of MA length → collapsed cavity."""
        # MA = 100px wide, arc depth = 5px → 5/100 = 5% < 15%
        contour = _make_contour(
            points=[(0, 100), (50, 95), (100, 100)],
            mitral_annulus=((0, 100), (100, 100)),
            apex_landmark=(50, 80),
        )
        reason = explain_lv_auto_reject_reason(contour, None)
        assert reason is not None
        assert "плоский" in reason

    def test_deep_contour_passes_depth_check(self) -> None:
        """Arc depth >= 15% of MA length passes."""
        # MA = 100px wide, arc depth = 20px → 20/100 = 20% >= 15%
        contour = _make_contour(
            points=[(0, 100), (50, 80), (100, 100)],
            mitral_annulus=((0, 100), (100, 100)),
            apex_landmark=(50, 80),
        )
        reason = explain_lv_auto_reject_reason(contour, None)
        # Should pass depth check
        assert reason is None or "плоский" not in reason

    def test_centroid_outside_roi_rejects(self) -> None:
        """Centroid outside ROI → reject."""
        contour = _make_contour(
            points=[(40, 60), (50, 40), (60, 60)],
            mitral_annulus=((40, 60), (60, 60)),
            apex_landmark=(50, 40),
        )
        reason = explain_lv_auto_reject_reason(
            contour,
            None,
            roi_xyxy=(0, 0, 30, 30),
        )
        assert reason is not None
        assert "ROI" in reason

    def test_centroid_inside_roi_passes(self) -> None:
        """Centroid inside ROI passes."""
        contour = _make_contour(
            points=[(10, 40), (20, 10), (30, 40)],
            mitral_annulus=((10, 40), (30, 40)),
            apex_landmark=(20, 10),
        )
        reason = explain_lv_auto_reject_reason(
            contour,
            None,
            roi_xyxy=(0, 0, 50, 50),
        )
        assert reason is None

    def test_no_spacing_skips_mm_check(self) -> None:
        """Without pixel_spacing, MA mm check is skipped."""
        contour = _make_contour(
            points=[(0, 30), (5, 0), (10, 30)],
            mitral_annulus=((0, 30), (10, 30)),
            apex_landmark=(5, 0),
        )
        reason = explain_lv_auto_reject_reason(contour, None)
        # Should not reject for MA too small (no spacing → no mm check)
        assert reason is None or "мм" not in reason

    def test_inverted_apex_a4c_rejects(self) -> None:
        """A4C with annulus_y < apex_y is inverted."""
        contour = _make_contour(
            points=[(0, 10), (20, 80), (40, 10)],
            mitral_annulus=((0, 10), (40, 10)),
            apex_landmark=(20, 80),
        )
        reason = explain_lv_auto_reject_reason(contour, None)
        assert reason is not None
        assert "инвертирован" in reason

    def test_steep_shallow_ma_rejects(self) -> None:
        """Steep MA chord + shallow cavity → likely the wrong opening."""
        # MA ≈ 41 px at ~76°, apex slightly off the chord.
        # MA 100 px at 53°, depth 16 px → 16% (passes flat 15%, fails steep 20%).
        contour = _make_contour(
            points=[(0.0, 100.0), (42.8, 130.4), (60.0, 180.0)],
            mitral_annulus=((0.0, 100.0), (60.0, 180.0)),
            apex_landmark=(42.8, 130.4),
        )
        reason = explain_lv_auto_reject_reason(contour, None)
        assert reason is not None
        assert "крутое" in reason

    def test_steep_deep_ma_passes_slope_check(self) -> None:
        contour = _make_contour(
            points=[(0, 0), (-30, 10), (10, 40)],
            mitral_annulus=((0, 0), (10, 40)),
            apex_landmark=(-30, 10),
        )
        reason = explain_lv_auto_reject_reason(contour, None)
        assert reason is None or "крутое" not in reason


class TestArcDepth:
    def test_zero_depth(self) -> None:
        contour = _make_contour(
            points=[(0, 30), (10, 30), (20, 30)],
            mitral_annulus=((0, 30), (20, 30)),
        )
        assert _contour_arc_depth_px(contour) == 0.0

    def test_known_depth(self) -> None:
        contour = _make_contour(
            points=[(0, 20), (10, 10), (20, 20)],
            mitral_annulus=((0, 20), (20, 20)),
        )
        depth = _contour_arc_depth_px(contour)
        assert abs(depth - 10.0) < 0.1


class TestCentroid:
    def test_triangle_centroid(self) -> None:
        contour = _make_contour(points=[(0, 0), (30, 0), (15, 30)])
        c = _contour_centroid(contour)
        assert c is not None
        assert abs(c[0] - 15.0) < 0.1
        assert abs(c[1] - 10.0) < 0.1

    def test_too_few_points(self) -> None:
        contour = _make_contour(points=[(0, 0), (10, 0)])
        assert _contour_centroid(contour) is None


class TestSelfIntersection:
    def test_no_intersection(self) -> None:
        from echo_personal_tool.domain.calculations.lvef_simpson import _contour_self_intersects

        points = [(0, 0), (10, 30), (20, 0)]
        assert not _contour_self_intersects(points)

    def test_self_intersection(self) -> None:
        from echo_personal_tool.domain.calculations.lvef_simpson import _contour_self_intersects

        # Bow-tie shape: segments cross
        points = [(0, 0), (20, 20), (20, 0), (0, 20)]
        assert _contour_self_intersects(points)

    def test_rejects_self_intersecting_contour(self) -> None:
        # Bow-tie; MA at high y so A4C inversion does not fire first.
        points = [(0, 40), (40, 0), (40, 40), (0, 0)]
        contour = _make_contour(
            points=points,
            mitral_annulus=((0, 40), (40, 40)),
            apex_landmark=(20, 0),
        )
        reason = explain_lv_auto_reject_reason(contour, None)
        assert reason is not None
        assert "самопересекается" in reason
