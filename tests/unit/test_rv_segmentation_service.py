"""Pure-core RV failure reasons, physical units and directed prior refinement."""

from dataclasses import replace

import numpy as np
import pytest
from scipy import ndimage

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.cardiac_atlas import build_cardiac_atlas
from echo_personal_tool.domain.services.cardiac_atlas_geometry import polygon_interior
from echo_personal_tool.domain.services.rv_segmentation_service import (
    build_rv_auto_contour,
    explain_rv_auto_reject_reason,
)


def seed():
    model = build_cardiac_atlas()
    mesh = model.mean_ed + [110, 70]
    contours = []
    for name in ("LV", "RV"):
        points = mesh[list(model.structures[name])]
        contours.append(
            Contour(
                "ED",
                chamber=name,
                points=[tuple(p) for p in points],
                mitral_annulus=(tuple(points[0]), tuple(points[-1])),
                apex_landmark=tuple(mesh[model.landmarks[f"{name}_apex"]]),
                frame_index=0,
            )
        )
    return contours[1], contours[0]


def qc(rv=None, lv=None, **kwargs):
    default_rv, default_lv = seed()
    context = dict(
        pixel_spacing=(0.5, 0.5),
        frame_shape=(200, 200),
        sector_mask=np.ones((200, 200), bool),
        lv_contour=default_lv if lv is None else lv,
    )
    context.update(kwargs)
    return explain_rv_auto_reject_reason(rv or default_rv, **context)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"phase": "UNKNOWN"}, "unsupported_context"),
        ({"chamber": "RA"}, "unsupported_context"),
        ({"points": [(np.nan, 0)] * 5}, "invalid_contour"),
        ({"mitral_annulus": None}, "missing_landmarks"),
        ({"apex_landmark": (1.0, 1.0)}, "apex_mismatch"),
    ],
)
def test_reject_context_and_inconsistent_anchors(change, reason):
    rv, _ = seed()
    assert qc(replace(rv, **change)) == reason


@pytest.mark.parametrize(
    "context,reason",
    [
        ({"confidence": 0.1}, "low_confidence"),
        ({"confidence": np.nan}, "low_confidence"),
        ({"pixel_spacing": None}, "missing_calibration"),
        ({"pixel_spacing": (0.0, 1.0)}, "invalid_calibration"),
        ({"pixel_spacing": (0.01, 0.01)}, "annulus_span"),
        ({"sector_mask": None}, "missing_sector"),
        ({"sector_mask": np.ones((3, 3))}, "invalid_sector"),
        ({"lv_contour": None}, "missing_lv_context"),
    ],
)
def test_fail_closed_without_required_context(context, reason):
    assert qc(**context) == reason


def test_physical_annulus_span_uses_column_spacing_not_mean():
    assert qc(pixel_spacing=(10.0, 0.02)) == "annulus_span"
    assert qc(pixel_spacing=(0.02, 1.0)) is None


def test_empty_small_crossed_and_truncated_cavities_are_not_proposals():
    rv, _ = seed()
    assert qc() is None
    points = np.asarray(rv.points)
    small = points * 0.1 + 70
    scaled = replace(
        rv,
        points=[tuple(p) for p in small],
        mitral_annulus=(tuple(small[0]), tuple(small[-1])),
        apex_landmark=tuple(np.asarray(rv.apex_landmark) * 0.1 + 70),
    )
    assert qc(scaled, pixel_spacing=(2.0, 2.0)) == "cavity_area"
    crossed = list(rv.points)
    crossed[15], crossed[20] = crossed[20], crossed[15]
    assert qc(replace(rv, points=crossed)) == "self_intersection"
    sector = np.ones((200, 200), bool)
    midpoint = ((points[-2] + points[-3]) / 2).round().astype(int)
    # Vertices all stay visible; only the connecting free-wall segment is cut.
    sector[midpoint[1] - 1 : midpoint[1] + 2, midpoint[0] - 1 : midpoint[0] + 2] = False
    assert sector[np.rint(points[:, 1]).astype(int), np.rint(points[:, 0]).astype(int)].all()
    assert qc(sector_mask=sector) == "sector_clipped"
    assert qc(lv=replace(rv, chamber="LV")) == "lv_overlap"
    _, lv = seed()
    left = replace(lv, points=[(x - 100, y) for x, y in lv.points])
    assert qc(lv=left) == "septal_orientation"
    assert qc(lv=replace(lv, frame_index=1)) == "invalid_lv_context"


def build(frame):
    rv, lv = seed()
    return build_rv_auto_contour(
        frame,
        np.asarray(rv.points),
        annulus=rv.mitral_annulus,
        apex=rv.apex_landmark,
        phase="ED",
        view="A4C",
        frame_index=0,
        pixel_spacing=(0.5, 0.5),
        sector_mask=np.ones(frame.shape[:2], bool),
        lv_contour=lv,
    )


def test_dropout_keeps_template_and_reliable_edges_never_move_shared_septum():
    rv, _ = seed()
    untouched, reason = build(np.zeros((200, 200)))
    assert reason is None and untouched is not None and untouched.review_pending
    np.testing.assert_array_equal(untouched.points, rv.points)
    yy, xx = np.mgrid[:200, :200]
    inside = polygon_interior(np.column_stack([xx.ravel(), yy.ravel()]), np.asarray(rv.points)).reshape(200, 200)
    image = ndimage.gaussian_filter((~inside).astype(float), 0.6)
    refined, reason = build(image)
    assert reason is None and refined is not None and refined.review_pending and refined.source == "ai"
    points = np.asarray(rv.points)
    split = np.argmin(np.linalg.norm(points - rv.apex_landmark, axis=1))
    np.testing.assert_array_equal(np.asarray(refined.points)[: split + 1], points[: split + 1])
    np.testing.assert_array_equal(np.asarray(refined.points)[[0, -1]], points[[0, -1]])
    assert np.linalg.norm(np.asarray(refined.points) - points, axis=1).max() <= 2.000001
