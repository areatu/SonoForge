"""Synthetic, exact-ground-truth contracts for the pure cardiac atlas (#689)."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from echo_personal_tool.domain.services.cardiac_atlas import (
    ATLAS_VIEWS,
    CoupledShapeModel,
    build_cardiac_atlas,
    build_mean_appearance,
    fit_chamber_landmarks,
    phase_weight,
)
from echo_personal_tool.domain.services.cardiac_atlas_geometry import (
    CanonicalFrame,
    sector_cartesian,
    sector_polar,
)
from echo_personal_tool.domain.services.cardiac_atlas_pca import AtlasObservation, align_local_contours, fit_atlas_pca


@pytest.mark.parametrize("spacing", [None, (0.2, 0.7), (0.4, 0.4)])
@pytest.mark.parametrize("angle", [0, 0.6, 2.1])
def test_canonical_roundtrip_is_metric_and_reversible(spacing, angle: float) -> None:
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    anchors = np.array([[-20, 0], [20, 0], [3, 90]]) @ rot.T + [130, 210]
    frame = CanonicalFrame.from_landmarks(*[tuple(p) for p in anchors], pixel_spacing_mm=spacing)
    points = np.random.default_rng(42).uniform(-100, 500, (100, 2))
    np.testing.assert_allclose(frame.atlas_to_image(frame.image_to_atlas(points)), points, atol=1e-10)
    canonical = frame.image_to_atlas(anchors)
    np.testing.assert_allclose(canonical[:2].mean(axis=0), 0, atol=1e-10)
    assert abs(canonical[2, 0]) < 1e-10 and canonical[2, 1] > 0
    assert canonical[1, 0] > canonical[0, 0]
    if spacing is not None:
        expected_mm = np.linalg.norm((anchors[1] - anchors[0]) * np.array(spacing[::-1]))
        assert np.linalg.norm(canonical[1] - canonical[0]) == pytest.approx(expected_mm)
        assert frame.units == "mm"
    else:
        assert np.linalg.norm(canonical[1] - canonical[0]) == pytest.approx(1)
        assert frame.units == "annulus_span"


@pytest.mark.parametrize("anchors", [[(0, 0), (0, 0), (0, 30)], [(0, 0), (10, 0), (5, 0)]])
def test_degenerate_alignment_rejected(anchors) -> None:
    with pytest.raises(ValueError):
        CanonicalFrame.from_landmarks(*anchors)


@pytest.mark.parametrize("spacing", [(0, 1), (-1, 1), (np.nan, 1)])
def test_invalid_calibration_is_not_silently_called_mm(spacing) -> None:
    with pytest.raises(ValueError, match="spacing"):
        CanonicalFrame.from_landmarks((0, 0), (10, 0), (5, 30), pixel_spacing_mm=spacing)


def test_polar_roundtrip_and_warp_image_coordinates() -> None:
    pixels = np.array([[20, 50], [60, 80], [-10, 120]])
    np.testing.assert_allclose(sector_cartesian(sector_polar(pixels, (30, 10)), (30, 10)), pixels, atol=1e-10)
    frame = CanonicalFrame.from_landmarks((10, 0), (30, 0), (20, 60), pixel_spacing_mm=(1, 1))
    yy, xx = np.indices((80, 80))
    sampled = frame.warp_image((xx + 2 * yy).astype(float), bounds=(-10, 0, 10, 20), size=21)
    assert sampled[0, 0] == pytest.approx(10)
    assert sampled[-1, -1] == pytest.approx(70)


@pytest.mark.parametrize("view", ATLAS_VIEWS)
def test_topology_and_modes_do_not_cross_chambers(view: str) -> None:
    model = build_cardiac_atlas(view)
    rng = np.random.default_rng(7)
    for phase in ("ED", "ES", 0.17, 0.6):
        for _ in range(8):
            points = model.synthesize(rng.normal(0, 5, 4), phase=phase)
            assert model.violations(points) == ()
    if "LA" in model.structures:
        assert len(model.structures["LV"]) == 32 and len(model.structures["LA"]) == 24
        assert model.structures["LV"][0] == model.structures["LA"][0]
        assert model.structures["LV"][-1] == model.structures["LA"][-1]
    if view in {"A4C", "RV_A4C"}:
        assert len(model.structures["RV"]) == 24
        assert set(model.structures["RV"]) & set(model.structures["LV"])
        assert 3 <= model.mean_ed[model.landmarks["TV_septal"], 1] <= 8


def test_phase_ventricles_contract_and_atria_expand() -> None:
    model = build_cardiac_atlas()
    for chamber, direction in (("LV", -1), ("RV", -1), ("LA", 1), ("RA", 1)):
        indices = list(model.structures[chamber])
        ed = np.ptp(model.mean_ed[indices, 1])
        es = np.ptp(model.mean_es[indices, 1])
        assert (es - ed) * direction > 0
    np.testing.assert_allclose(model.mean(0), model.mean("ED"))
    np.testing.assert_allclose(model.mean(0.38), model.mean("ES"))
    np.testing.assert_allclose(model.mean(1), model.mean("ED"))
    assert phase_weight(0.38) == pytest.approx(1)


def test_dropout_does_not_collapse_rv_free_wall() -> None:
    model = build_cardiac_atlas("RV_A4C")
    observations = model.mean("ED")
    weights = np.ones(len(observations))
    # Corrupt an entire free wall, explicitly marking it unavailable.
    free = sorted(set(model.structures["RV"]) - set(model.structures["LV"]))
    observations[free] = np.nan
    weights[free] = 0
    fit = model.fit(observations, weights=weights)
    np.testing.assert_allclose(fit.points, model.mean_ed, atol=1e-9)
    assert fit.observed_nodes == len(observations) - len(free)
    assert model.violations(fit.points) == ()
    assert np.ptp(fit.points[list(model.structures["RV"]), 0]) > 25


def test_ridge_recovers_a_coupled_mode_and_ignores_zero_weight_outliers() -> None:
    model = build_cardiac_atlas()
    coefficients = [0.5, 0.3, -0.2, 0.1]
    truth = model.synthesize(coefficients)
    fit = model.fit(truth, ridge=1e-8)
    np.testing.assert_allclose(fit.points, truth, atol=1e-6)
    weights = np.ones(len(truth))
    weights[20] = 0
    truth[20] = [999, 999]
    fit = model.fit(truth, weights=weights, ridge=1e-8)
    assert fit.rms < 1e-6
    missing = model.fit(np.full_like(truth, np.nan))
    np.testing.assert_allclose(missing.points, model.mean_ed)


@pytest.mark.parametrize("chamber", ["LV", "LA", "RV", "RA"])
def test_three_landmark_placement_preserves_exact_anchors(chamber: str) -> None:
    anchors = [(30.0, 40.0), (100.0, 55.0), (65.0, 160.0)]
    arc = np.asarray(fit_chamber_landmarks(build_cardiac_atlas(), chamber, *anchors, num_points=81))
    np.testing.assert_allclose(arc[[0, -1, 40]], anchors, atol=1e-10)
    assert np.isfinite(arc).all()


def test_mean_appearance_contains_dark_cavity_bright_walls_and_dropout_weights() -> None:
    atlas = build_mean_appearance(build_cardiac_atlas())
    assert atlas.mean.shape == atlas.variance.shape == atlas.boundary_confidence.shape == (128, 128)
    assert atlas.mean.min() < 0.1 and atlas.mean.max() > 0.7
    assert atlas.boundary_confidence.min() < 0.4 and atlas.boundary_confidence.max() > 0.9
    assert np.all(atlas.variance > 0)
    assert np.isfinite(atlas.mean).all()


def test_model_numeric_serialization_and_validation() -> None:
    model = build_cardiac_atlas()
    restored = CoupledShapeModel.from_dict(json.loads(json.dumps(model.to_dict(), allow_nan=False)))
    np.testing.assert_array_equal(restored.synthesize([0.1]), model.synthesize([0.1]))
    assert not model.mean_ed.flags.writeable
    with pytest.raises(ValueError, match="schema"):
        CoupledShapeModel.from_dict({**model.to_dict(), "units": "pixels"})
    with pytest.raises(ValueError):
        replace(model, eigenvalues=np.array([-1, 1, 1, 1]))
    with pytest.raises(ValueError):
        build_cardiac_atlas("UNKNOWN")


def test_local_pca_is_reproducible_and_preserves_topology() -> None:
    seed = build_cardiac_atlas()
    observations = [AtlasObservation("ED", seed.synthesize([b, b / 3])) for b in (-0.8, -0.2, 0.3, 0.8)]
    first = fit_atlas_pca(seed, observations, max_modes=2)
    second = fit_atlas_pca(seed, observations, max_modes=2)
    assert first.to_dict() == second.to_dict()
    assert first.mode_names == ("local_pc_1", "local_pc_2")
    assert first.eigenvalues[0] > 0
    assert first.violations(first.synthesize([1, -1])) == ()
    np.testing.assert_array_equal(first.mean_es, seed.mean_es)  # no fabricated ES observations


def test_local_alignment_uses_one_metric_frame_for_all_chambers() -> None:
    model = build_cardiac_atlas()
    shift = [120, 150]
    mesh = model.mean_ed + shift
    ids = model.structures["LV"]
    sample = align_local_contours(
        model,
        {name: mesh[list(nodes)] for name, nodes in model.structures.items() if name != "IVS"},
        reference_chamber="LV",
        septal=tuple(mesh[ids[0]]),
        lateral=tuple(mesh[ids[-1]]),
        apex=tuple(mesh[model.landmarks["LV_apex"]]),
        phase="ED",
        pixel_spacing_mm=(1, 1),
    )
    np.testing.assert_allclose(sample.points, model.mean_ed, atol=1e-8)


def test_partial_pca_does_not_learn_unobserved_ra_nodes() -> None:
    seed = build_cardiac_atlas()
    samples = []
    visible = list(seed.structures["LV"])
    for b in (-0.4, 0.4, 0.8):
        points = np.full_like(seed.mean_ed, np.nan)
        points[visible] = seed.synthesize([0, 0, b])[visible]
        samples.append(AtlasObservation("ED", points))
    fitted = fit_atlas_pca(seed, samples, max_modes=1)
    missing = sorted(set(range(len(points))) - set(visible))
    np.testing.assert_array_equal(fitted.mean_ed[missing], seed.mean_ed[missing])
    np.testing.assert_array_equal(fitted.modes[:, missing], 0)
    with pytest.raises(ValueError, match=">=2"):
        fit_atlas_pca(seed, samples[:1])


def test_projection_specific_templates_keep_rv_focus_and_outflow() -> None:
    from echo_personal_tool.domain.services.cardiac_atlas_templates import analytic_atlas_seed

    apical = CoupledShapeModel(*analytic_atlas_seed("A4C"))
    focused = CoupledShapeModel(*analytic_atlas_seed("RV_A4C"))
    assert (
        focused.mean_ed[list(focused.structures["RV"]), 0].min()
        < apical.mean_ed[list(apical.structures["RV"]), 0].min()
    )
    assert {"LVOT", "AO"}.issubset(CoupledShapeModel(*analytic_atlas_seed("PLAX")).structures)
    assert "RV" not in CoupledShapeModel(*analytic_atlas_seed("A2C")).structures
    short = CoupledShapeModel(*analytic_atlas_seed("PSAX"))
    assert set(short.closed_structures) == {"LV", "RV"}
    assert short.violations(short.mean_ed) == ()


def test_rv_dropout_preserves_smooth_open_arc_tangents() -> None:
    model = build_cardiac_atlas()
    fit = model.fit(np.full_like(model.mean_ed, np.nan))
    arc = fit.points[list(model.structures["RV"])]
    directions = np.diff(arc, axis=0)
    adjacent_cosines = np.sum(directions[1:] * directions[:-1], axis=1) / (
        np.linalg.norm(directions[1:], axis=1) * np.linalg.norm(directions[:-1], axis=1)
    )
    assert adjacent_cosines.min() > 0.5  # no folded/spiky dropout reconstruction


@pytest.mark.parametrize("bad", ["empty", "repeated", "disconnected_mv"])
def test_invalid_topology_artifacts_rejected(bad: str) -> None:
    model = build_cardiac_atlas()
    structures = dict(model.structures)
    if bad == "empty":
        structures["LV"] = ()
    elif bad == "repeated":
        structures["LV"] = (0, 0, 16)
    else:
        structures["LA"] = structures["LA"][1:]
    with pytest.raises(ValueError):
        replace(model, structures=structures)


def test_rv_overload_compresses_lv_instead_of_expanding_its_septal_wall() -> None:
    model = build_cardiac_atlas()
    shared = sorted(set(model.structures["RV"]) & set(model.structures["IVS"]))
    free = sorted(set(model.structures["RV"]) - set(model.structures["IVS"]))
    shifted = model.synthesize([0, 1])
    assert np.mean(shifted[shared, 0] - model.mean_ed[shared, 0]) > 0
    assert np.mean(shifted[free, 0] - model.mean_ed[free, 0]) < 0
    assert "IVS" not in build_cardiac_atlas("A2C").structures
