"""Unit tests for open-arc Laplacian smoothing."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.contour_geometry import smooth_open_arc


def test_smooth_open_arc_preserves_endpoints_and_apex() -> None:
    annulus = ((0.0, 0.0), (100.0, 0.0))
    points = [(0.0, 0.0)]
    for index in range(1, 31):
        t = index / 30.0
        x = 100.0 * t
        y = 40.0 * (1.0 - (2.0 * t - 1.0) ** 2)
        if index % 3 == 0:
            y += 8.0
        points.append((x, y))
    points[-1] = (100.0, 0.0)

    smoothed = smooth_open_arc(points, annulus, iterations=10, blend=0.5)

    assert smoothed[0] == pytest.approx(annulus[0], abs=1e-6)
    assert smoothed[-1] == pytest.approx(annulus[1], abs=1e-6)
    roughness_before = sum(
        abs(points[i - 1][0] - 2.0 * points[i][0] + points[i + 1][0])
        + abs(points[i - 1][1] - 2.0 * points[i][1] + points[i + 1][1])
        for i in range(1, len(points) - 1)
    )
    roughness_after = sum(
        abs(smoothed[i - 1][0] - 2.0 * smoothed[i][0] + smoothed[i + 1][0])
        + abs(smoothed[i - 1][1] - 2.0 * smoothed[i][1] + smoothed[i + 1][1])
        for i in range(1, len(smoothed) - 1)
    )
    assert roughness_after < roughness_before


def test_smooth_open_arc_reduces_laplacian_energy() -> None:
    annulus = ((10.0, 80.0), (90.0, 80.0))
    points = [
        (10.0, 80.0),
        (30.0, 50.0),
        (40.0, 20.0),
        (55.0, 5.0),
        (70.0, 25.0),
        (80.0, 55.0),
        (90.0, 80.0),
    ]
    points[3] = (55.0, -5.0)

    def energy(curve: list[tuple[float, float]]) -> float:
        total = 0.0
        for index in range(1, len(curve) - 1):
            x0, y0 = curve[index - 1]
            x1, y1 = curve[index]
            x2, y2 = curve[index + 1]
            total += abs(x0 - 2.0 * x1 + x2) + abs(y0 - 2.0 * y1 + y2)
        return total

    smoothed = smooth_open_arc(points, annulus)
    assert energy(smoothed) < energy(points)
