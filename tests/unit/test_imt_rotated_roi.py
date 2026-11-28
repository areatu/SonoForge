"""Synthetic rotated ROI search: source geometry, physical normals and persistence."""

from dataclasses import replace
from math import ceil, floor

import numpy as np
import pytest

from echo_personal_tool.application.imt import correct_imt, propose_imt
from echo_personal_tool.domain.models.calibration import CalibrationContext
from echo_personal_tool.domain.models.imt import ImtPolicy, ImtRefusal, ImtSource
from echo_personal_tool.domain.models.imt_region import contains_points
from echo_personal_tool.domain.services.imt_validation import validate_imt


def phantom(angle, spacing=(0.1, 0.2)):
    radians = np.deg2rad(angle)
    u = np.array([np.cos(radians), np.sin(radians)])
    v = np.array([-np.sin(radians), np.cos(radians)])
    origin = np.array([45.0, 100.0])
    polygon = np.array([origin, origin + 160 * u, origin + 160 * u + 40 * v, origin + 40 * v])
    bbox = (
        floor(polygon[:, 0].min()),
        floor(polygon[:, 1].min()),
        ceil(polygon[:, 0].max()),
        ceil(polygon[:, 1].max()),
    )
    source = ImtSource(
        "1.2.3",
        "sop",
        1,
        2,
        10,
        "R",
        "operator_selected",
        CalibrationContext(spacing, source="phantom"),
        bbox,
        roi_polygon=tuple(tuple(map(float, p)) for p in polygon),
    )
    yy, xx = np.indices((260, 260), dtype=float)
    points = np.stack((xx - origin[0], yy - origin[1]), axis=-1)
    along, depth = points @ u, points @ v
    row, col = spacing
    normal_spacing = row * col / np.linalg.norm(u * [col, row])
    gap = 0.8 / normal_spacing
    image = np.full(yy.shape, 10.0)
    image[depth >= 12] = 140
    image[depth >= 13.5] = 40
    image[depth >= 12 + gap] = 220
    inside = (along >= 0) & (along < 160) & (depth >= 0) & (depth < 40)
    return source, image, inside


@pytest.mark.parametrize("angle", [-30, -15, 15, 30])
@pytest.mark.parametrize("spacing", [(0.1, 0.2), (0.2, 0.1), (0.1, 0.1)])
def test_rotated_search_follows_wall_and_keeps_physical_normal_thickness(angle, spacing):
    source, image, _ = phantom(angle, spacing)
    policy = ImtPolicy(0.3, 1.5, 0.65, 0.02)
    draft = propose_imt(image, source, policy)
    # Rasterised edges and denoising permit sub-pixel error, not clinical accuracy.
    assert draft.mean_mm == pytest.approx(0.8, abs=0.12)
    assert contains_points(source.roi_polygon, np.array(draft.lumen_intima))
    assert contains_points(source.roi_polygon, np.array(draft.media_adventitia))
    xs, ys = np.array(draft.lumen_intima).T
    assert (ys[-1] - ys[0]) / (xs[-1] - xs[0]) == pytest.approx(np.tan(np.deg2rad(angle)), abs=0.03)
    assert not draft.confirmed
    validate_imt(draft.confirm(source))


def test_rotated_search_ignores_stronger_edges_outside_rectangle():
    source, image, inside = phantom(20)
    policy = ImtPolicy(0.3, 1.5, 0.65, 0.02)
    baseline = propose_imt(image, source, policy)
    yy, _ = np.indices(image.shape)
    image[~inside] = np.where(yy[~inside] % 10 < 5, 10000.0, 0.0)
    draft = propose_imt(image, source, policy)
    assert draft.mean_mm == pytest.approx(baseline.mean_mm, abs=0.03)
    assert draft.source.roi_polygon == source.roi_polygon


def test_manual_correction_cannot_escape_rotated_rectangle_even_within_bbox():
    source, image, _ = phantom(20)
    draft = propose_imt(image, source, ImtPolicy(0.3, 1.5, 0.65, 0.02))
    li = list(draft.lumen_intima)
    li[0] = (li[0][0], source.roi[1] + 0.1)
    with pytest.raises(ImtRefusal, match="boundary_outside_roi"):
        correct_imt(draft, source, image, lumen_intima=tuple(li), media_adventitia=draft.media_adventitia)


def test_rotated_geometry_survives_storage_and_revalidation():
    from echo_personal_tool.application.imt_review import ImtReview
    from echo_personal_tool.infrastructure.measurement_codec import dumps, loads
    from tests.unit.test_imt_document import record

    source, image, _ = phantom(15)
    draft = propose_imt(image, source, ImtPolicy(0.3, 1.5, 0.65, 0.02)).confirm(source)
    import json
    from importlib.resources import files

    import jsonschema

    payload = dumps(record(draft))
    schema = json.loads(
        files("echo_personal_tool.resources").joinpath("measurement-storage-v7.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(schema).validate(json.loads(payload))
    restored = loads(payload)["data"].imt_measurements[0]
    assert restored.source.roi_polygon == source.roi_polygon
    review = ImtReview(restored)
    assert not review.live
    review.revalidate(replace(source, generation=2), image)
    assert review.live and not review.draft.confirmed
    assert review.draft.mean_mm == pytest.approx(draft.mean_mm)


@pytest.mark.parametrize("change", ["angle", "skew", "outside", "nonfinite"])
def test_invalid_oriented_geometry_is_rejected(change):
    source, _image, _inside = phantom(15)
    points = np.array(source.roi_polygon)
    if change == "angle":
        points[[1, 3]] = points[[3, 1]]
    elif change == "skew":
        points[2] += 3
    elif change == "outside":
        points += 1000
    else:
        points[0, 0] = np.nan
    with pytest.raises(ImtRefusal):
        replace(source, roi_polygon=tuple(tuple(map(float, p)) for p in points))


def test_rectification_samples_only_selected_coordinate_grid():
    from echo_personal_tool.domain.services.imt_rectification import isolate_rectangle, rectify_crop, sampling_grid

    source, image, inside = phantom(20)
    x0, y0, x1, y1 = source.roi
    crop = image[y0:y1, x0:x1].copy()
    selected = inside[y0:y1, x0:x1]
    crop[~selected] = 10000
    isolated = isolate_rectangle(crop, source)
    assert np.array_equal(isolated[selected], crop[selected])
    assert isolated.max() <= 220
    origin, du, dv, shape = sampling_grid(source)
    yy, xx = np.indices(crop.shape, dtype=float)
    # A coordinate ramp has an exact bilinear interpolation in the interior.
    ramp = 2 * (xx + x0) + 3 * (yy + y0)
    local = rectify_crop(ramp, source)
    v, u = np.indices(shape, dtype=float)
    expected = 2 * (origin[0] + u * du[0] + v * dv[0]) + 3 * (origin[1] + u * du[1] + v * dv[1])
    assert np.allclose(local[2:-2, 2:-2], expected[2:-2, 2:-2])
