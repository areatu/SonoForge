"""Caliper label layout: position and angle for inline text on linear measurements."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CaliperLabelLayout:
    anchor_x: float
    anchor_y: float
    angle_deg: float
    offset_x: float
    offset_y: float


def readable_text_angle(angle_deg: float) -> float:
    a = angle_deg % 360.0
    if a > 180.0:
        a -= 360.0
    if a > 90.0:
        a -= 180.0
    elif a < -90.0:
        a += 180.0
    return a


def compute_caliper_label_layout(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    vertical_labels: frozenset[str],
    label: str,
    offset_px: float = 10.0,
) -> CaliperLabelLayout:
    sx, sy = start
    ex, ey = end
    mx = (sx + ex) / 2.0
    my = (sy + ey) / 2.0
    dx = ex - sx
    dy = ey - sy

    is_vertical = abs(dx) < abs(dy) * 0.5 or label in vertical_labels

    if is_vertical:
        return CaliperLabelLayout(
            anchor_x=mx,
            anchor_y=my,
            angle_deg=0.0,
            offset_x=-offset_px,
            offset_y=0.0,
        )

    angle = math.degrees(math.atan2(dy, dx))
    readable = readable_text_angle(angle)
    if abs(readable) > 90.0:
        readable += 180.0 if readable < 0 else -180.0
    angle_rad = math.radians(angle)
    nx = -math.sin(angle_rad)
    ny = -math.cos(angle_rad)
    return CaliperLabelLayout(
        anchor_x=mx,
        anchor_y=my,
        angle_deg=readable,
        offset_x=nx * offset_px,
        offset_y=ny * offset_px,
    )
