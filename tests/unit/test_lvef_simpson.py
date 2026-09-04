"""Unit tests for Simpson LVEF calculations."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.models import Contour


def rectangle_contour(
    *,
    phase: str,
    view: str,
    width_px: float,
    height_px: float,
) -> Contour:
    return Contour(
        phase=phase,
        view=view,
        points=[
            (0.0, 0.0),
            (width_px, 0.0),
            (width_px, height_px),
            (0.0, height_px),
        ],
    )


def open_arc_contour(*, phase: str, view: str, width_px: float, height_px: float) -> Contour:
    import math

    n = 9
    annulus = ((0.0, 0.0), (width_px, 0.0))
    angles = [math.pi - i * math.pi / (n - 1) for i in range(n)]
    points = [(width_px / 2.0 + (width_px / 2.0) * math.cos(a), height_px * math.sin(a)) for a in angles]
    return Contour(phase=phase, view=view, mitral_annulus=annulus, points=points)


def test_calculate_monoplan_rectangle_volume() -> None:
    contours = (
        rectangle_contour(phase="ed", view="a4c", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="Es", view="A4C", width_px=80.0, height_px=40.0),
    )

    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml == pytest.approx(49.087385, rel=1e-6)
    assert result.a4c.esv_ml == pytest.approx(25.132741, rel=1e-6)
    assert result.lvef_percent == pytest.approx(48.8, rel=1e-6)
    assert result.method == "simpson_monoplan"


def test_calculate_ed_larger_than_es_yields_positive_lvef() -> None:
    contours = (
        rectangle_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A4C", width_px=70.0, height_px=35.0),
    )

    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.lvef_percent is not None
    assert result.lvef_percent > 0.0


def test_calculate_missing_spacing_returns_none() -> None:
    contours = (
        rectangle_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A4C", width_px=80.0, height_px=40.0),
    )

    assert calculate(contours, None) is None  # type: ignore[arg-type]


def test_calculate_biplan_falls_back_to_monoplane_without_annulus() -> None:
    contours = (
        rectangle_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A4C", width_px=80.0, height_px=40.0),
        rectangle_contour(phase="ED", view="A2C", width_px=120.0, height_px=50.0),
        rectangle_contour(phase="ES", view="A2C", width_px=100.0, height_px=40.0),
    )

    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.method == "simpson_monoplan"
    assert result.lvef_percent == pytest.approx(46.22950819672132, rel=1e-6)


def test_calculate_single_ed_returns_partial_a4c_metrics() -> None:
    contours = (open_arc_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),)
    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml is not None
    assert result.a4c.edv_ml > 0.0
    assert result.a4c.length_ed_mm is not None
    assert result.a4c.length_ed_mm > 0.0
    assert result.a4c.esv_ml is None
    assert result.lvef_percent is None
    assert result.method is None


def test_calculate_biplan_populates_both_views() -> None:
    contours = (
        open_arc_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        open_arc_contour(phase="ES", view="A4C", width_px=80.0, height_px=40.0),
        open_arc_contour(phase="ED", view="A2C", width_px=120.0, height_px=50.0),
        open_arc_contour(phase="ES", view="A2C", width_px=100.0, height_px=40.0),
    )
    result = calculate(contours, (0.5, 0.5))
    assert result is not None
    assert result.a4c is not None
    assert result.a2c is not None
    assert result.method == "simpson_biplan"


def test_calculate_biplan_populates_biplane_volumes() -> None:
    contours = (
        open_arc_contour(phase="ED", view="A4C", width_px=100.0, height_px=50.0),
        open_arc_contour(phase="ES", view="A4C", width_px=80.0, height_px=40.0),
        open_arc_contour(phase="ED", view="A2C", width_px=120.0, height_px=50.0),
        open_arc_contour(phase="ES", view="A2C", width_px=100.0, height_px=40.0),
    )
    result = calculate(contours, (0.5, 0.5))
    assert result is not None
    assert result.method == "simpson_biplan"
    assert result.edv_bi_ml is not None
    assert result.esv_bi_ml is not None
    assert result.edv_bi_ml > 0.0
    assert 0.0 < result.esv_bi_ml <= result.edv_bi_ml


def test_calculate_monoplan_leaves_biplane_volumes_unset() -> None:
    contours = (
        open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0),
        open_arc_contour(phase="es", view="A4C", width_px=80.0, height_px=40.0),
    )
    result = calculate(contours, (0.5, 0.5))
    assert result is not None
    assert result.method == "simpson_monoplan"
    assert result.edv_bi_ml is None
    assert result.esv_bi_ml is None


def test_calculate_open_arc_monoplan() -> None:
    contours = (
        open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0),
        open_arc_contour(phase="es", view="A4C", width_px=80.0, height_px=40.0),
    )
    result = calculate(contours, (0.5, 0.5))

    assert result is not None
    assert result.a4c is not None
    assert result.method == "simpson_monoplan"
    assert result.a4c.edv_ml == pytest.approx(31.498208, rel=1e-4)
    assert result.a4c.esv_ml == pytest.approx(16.127083, rel=1e-4)


from dataclasses import replace


def test_calculate_ignores_review_pending_contours() -> None:
    pending = open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0)
    pending = replace(pending, review_pending=True)
    accepted = open_arc_contour(phase="es", view="A4C", width_px=80.0, height_px=40.0)
    result = calculate((pending, accepted), (0.5, 0.5))
    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml is None
    assert result.a4c.esv_ml is not None


def test_format_contour_overlay_shows_review_prompt_when_pending() -> None:
    from echo_personal_tool.domain.calculations.lvef_simpson import format_contour_overlay

    contour = open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0)
    contour = replace(contour, review_pending=True)

    text = format_contour_overlay(contour, (0.5, 0.5))

    assert "проверьте контур" in text
    assert "Enter" in text
    assert "0.1" not in text


def test_contour_meets_lv_auto_quality_rejects_tiny_contour() -> None:
    from echo_personal_tool.domain.calculations.lvef_simpson import explain_lv_auto_reject_reason

    tiny = Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        mitral_annulus=((0.0, 0.0), (5.0, 0.0)),
        points=[(0.0, 0.0), (2.5, 2.0), (5.0, 0.0)],
        apex_landmark=(2.5, 2.0),
    )

    assert explain_lv_auto_reject_reason(tiny, (0.5, 0.5)) is not None
    assert (
        explain_lv_auto_reject_reason(
            open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0),
            (0.5, 0.5),
        )
        is None
    )


def test_lv_auto_quality_rejects_small_annulus_mm_with_spacing() -> None:
    """v2: with very small spacing, MA mm check triggers."""
    from echo_personal_tool.domain.calculations.lvef_simpson import explain_lv_auto_reject_reason

    contour = open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0)
    # spacing 0.001 mm/px → MA = 100 * 0.001 = 0.1mm < 3mm → reject
    reason = explain_lv_auto_reject_reason(contour, (0.001, 0.001))
    assert reason is not None
    assert "мм" in reason


def test_lv_auto_quality_passes_with_normal_spacing() -> None:
    """v2: with normal spacing, MA mm check passes."""
    from echo_personal_tool.domain.calculations.lvef_simpson import explain_lv_auto_reject_reason

    contour = open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0)
    # spacing 0.15 mm/px → MA = 100 * 0.15 = 15mm >= 3mm → passes
    reason = explain_lv_auto_reject_reason(contour, (0.15, 0.15))
    assert reason is None


# ── Simpson visualization lines ────────────────────────────────────


def test_compute_simpson_lines_returns_lines_for_valid_contour() -> None:
    from echo_personal_tool.domain.calculations.lvef_simpson import compute_simpson_lines

    # Tall narrow contour where lines are NOT parallel to MV chord
    contour = open_arc_contour(phase="ed", view="A4C", width_px=60.0, height_px=200.0)
    result = compute_simpson_lines(contour)

    assert result is not None
    base, tip = result.central_line
    assert base[0] == pytest.approx(30.0, rel=1e-6)
    assert tip[1] > base[1]
    # 20 mid-height disks perpendicular to the long axis (same as volume calc)
    assert len(result.disk_lines) == 20


def test_compute_simpson_lines_returns_none_for_no_annulus() -> None:
    from echo_personal_tool.domain.calculations.lvef_simpson import compute_simpson_lines

    contour = Contour(phase="ed", view="A4C", points=[(0, 0), (10, 0), (5, 10)])
    result = compute_simpson_lines(contour)
    assert result is None


def test_compute_simpson_lines_returns_none_for_too_few_points() -> None:
    from echo_personal_tool.domain.calculations.lvef_simpson import compute_simpson_lines

    contour = Contour(
        phase="ed",
        view="A4C",
        mitral_annulus=((0, 0), (10, 0)),
        points=[(0, 0), (10, 0)],
    )
    result = compute_simpson_lines(contour)
    assert result is None


def test_compute_simpson_lines_matches_disk_count_and_axis() -> None:
    from echo_personal_tool.domain.calculations.lvef_simpson import (
        _SIMPSON_N_DISKS,
        compute_simpson_lines,
    )

    contour = open_arc_contour(phase="ed", view="A4C", width_px=80.0, height_px=160.0)
    result = compute_simpson_lines(contour, pixel_spacing=(0.5, 0.5))
    assert result is not None
    assert len(result.disk_lines) == _SIMPSON_N_DISKS
    base, tip = result.central_line
    axis_dx = tip[0] - base[0]
    axis_dy = tip[1] - base[1]
    axis_len = (axis_dx**2 + axis_dy**2) ** 0.5
    assert axis_len > 0.0
    for left, right in result.disk_lines:
        chord_dx = right[0] - left[0]
        chord_dy = right[1] - left[1]
        assert abs(chord_dx * axis_dx + chord_dy * axis_dy) < 1e-4 * axis_len * max(
            1.0, (chord_dx**2 + chord_dy**2) ** 0.5
        )


def test_biplane_volume_uses_max_long_axis_height() -> None:
    import math

    from echo_personal_tool.domain.calculations.lvef_simpson import (
        _SIMPSON_N_DISKS,
        _biplane_volume_ml,
        _contour_to_mm,
        _disk_diameters_mm,
        _long_axis_mm,
    )

    a4c = open_arc_contour(phase="ed", view="A4C", width_px=100.0, height_px=50.0)
    a2c = open_arc_contour(phase="ed", view="A2C", width_px=80.0, height_px=80.0)
    spacing = (0.5, 0.5)
    pts_a, ann_a = _contour_to_mm(a4c, spacing)
    pts_b, ann_b = _contour_to_mm(a2c, spacing)
    volume = _biplane_volume_ml(pts_a, ann_a, pts_b, ann_b)
    diameters_a = _disk_diameters_mm(pts_a, ann_a)
    diameters_b = _disk_diameters_mm(pts_b, ann_b)
    long_a = _long_axis_mm(pts_a, ann_a)
    long_b = _long_axis_mm(pts_b, ann_b)
    assert long_a != pytest.approx(long_b)
    disk_height = max(long_a, long_b) / float(_SIMPSON_N_DISKS)
    expected_mm3 = 0.0
    for d_a, d_b in zip(diameters_a, diameters_b, strict=True):
        if d_a <= 0.0 or d_b <= 0.0:
            continue
        expected_mm3 += (math.pi / 4.0) * d_a * d_b * disk_height
    assert volume == pytest.approx(expected_mm3 / 1000.0)
    avg_height = (long_a + long_b) / (2.0 * _SIMPSON_N_DISKS)
    assert disk_height != pytest.approx(avg_height)
