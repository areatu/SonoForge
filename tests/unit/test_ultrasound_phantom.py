"""ML.2 geometry/acoustics invariants without Qt, torch or clinical media."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from echo_personal_tool.domain.services.cardiac_atlas import build_cardiac_atlas
from echo_personal_tool.domain.services.ultrasound_phantom import (
    PHANTOM_VIEWS,
    PhantomConfig,
    cine_phases,
    generate_cine,
)
from echo_personal_tool.domain.services.ultrasound_phantom_acoustics import (
    AcousticSettings,
    advected_rayleigh,
    depth_gain,
    depth_psf,
    inverse_tissue_map,
    render_reflectivity,
    specular_response,
)
from echo_personal_tool.domain.services.ultrasound_phantom_geometry import (
    SectorGeometry,
    cardiac_mesh,
    mechanical_weight,
    valve_segments,
)


def polygon_area(arc: np.ndarray) -> float:
    return float(abs(np.sum(arc[:, 0] * np.roll(arc[:, 1], -1) - arc[:, 1] * np.roll(arc[:, 0], -1))) / 2)


@pytest.mark.parametrize("view", PHANTOM_VIEWS)
def test_all_views_have_valid_cine_and_pre_dropout_ground_truth(view: str) -> None:
    cine = generate_cine(PhantomConfig(view=view, size=48, frames_per_cycle=12, seed=31))
    assert cine.frames.shape == (12, 48, 48) and cine.frames.dtype == np.uint8
    assert 0 < int(cine.frames.max()) <= 255
    assert np.all(cine.frames[:, ~cine.sector_mask] == 0)
    assert len(cine.contours["LV"][0]) == 32
    sector = SectorGeometry(48)
    for name, points in cine.contours.items():
        assert np.isfinite(points).all() and sector.contains(points).all()
        if name in cine.masks:
            assert cine.masks[name].any() and not cine.masks[name][:, ~cine.sector_mask].any()
    for points in cine.landmarks.values():
        assert points.shape == (12, 2) and sector.contains(points).all()
    if view != "PSAX":
        assert "MV" in cine.valves
    assert cine.pixel_spacing_mm[0] > 0


def test_seed_determinism_and_acoustic_changes_do_not_change_gt() -> None:
    cfg = PhantomConfig(size=48, frames_per_cycle=12, seed=9)
    one, two = generate_cine(cfg), generate_cine(cfg)
    np.testing.assert_array_equal(one.frames, two.frames)
    np.testing.assert_array_equal(one.contours["RV"], two.contours["RV"])
    shadowed = generate_cine(cfg, acoustics=AcousticSettings(shadow_strength=1, shadow_width=0.4))
    assert not np.array_equal(one.frames, shadowed.frames)
    np.testing.assert_array_equal(one.masks["RV"], shadowed.masks["RV"])
    np.testing.assert_array_equal(one.contours["RV"], shadowed.contours["RV"])
    different = generate_cine(replace(cfg, seed=10))
    assert not np.array_equal(one.frames, different.frames)


def test_mechanics_counterphase_shared_interfaces_and_annular_excursion() -> None:
    atlas = build_cardiac_atlas()
    phases = np.linspace(0, 1, 21)
    meshes = [cardiac_mesh(atlas, float(phi), (0, 0, 0, 0)) for phi in phases]
    areas = {
        name: np.array([polygon_area(mesh[list(ids)]) for mesh in meshes])
        for name, ids in atlas.structures.items()
        if name in {"LV", "RV", "LA", "RA"}
    }
    assert np.corrcoef(areas["LV"], areas["LA"])[0, 1] < -0.95
    assert np.corrcoef(areas["RV"], areas["RA"])[0, 1] < -0.9
    assert np.corrcoef(areas["RV"], areas["LV"])[0, 1] > 0.95
    for mesh in meshes:
        assert atlas.violations(mesh) == ()
        np.testing.assert_array_equal(
            mesh[list(atlas.structures["LV"])][[0, -1]], mesh[list(atlas.structures["LA"])][[0, -1]]
        )
    ed = cardiac_mesh(atlas, 0, (0, 0, 0, 0))
    es = cardiac_mesh(atlas, 0.38, (0, 0, 0, 0))
    assert es[atlas.landmarks["MV_septal"], 1] > ed[atlas.landmarks["MV_septal"], 1] + 3
    assert es[atlas.landmarks["TV_lateral"], 1] > ed[atlas.landmarks["TV_lateral"], 1]
    np.testing.assert_allclose(meshes[0], meshes[-1], atol=1e-12)
    assert mechanical_weight(0.38) == pytest.approx(1)
    assert mechanical_weight(0.7) < 0.2 and mechanical_weight(0.95) < mechanical_weight(0.86)


def test_valve_leaflets_follow_annulus_and_open_in_opposite_phases() -> None:
    model = build_cardiac_atlas("A3C")
    values = {}
    for phase in (0.0, 0.2, 0.7):
        mesh = cardiac_mesh(model, phase, (0, 0, 0, 0))
        valves = valve_segments(model, mesh, phase)
        np.testing.assert_array_equal(valves["MV"][0, 0], mesh[model.landmarks["MV_septal"]])
        assert set(valves) == {"MV", "AV"}
        values[phase] = {
            key: float(np.linalg.norm(segments[0, 1] - segments[1, 1])) for key, segments in valves.items()
        }
    assert values[0.7]["MV"] > values[0.2]["MV"]
    assert values[0.2]["AV"] > values[0.7]["AV"]


def test_sector_polar_geometry_and_uniform_cine_sampling() -> None:
    sector = SectorGeometry(64)
    points = np.array([[31.5, 32], [31.5 + 20 * np.sin(0.3), 20 * np.cos(0.3)], [0, 1], [31.5, 63]])
    r, theta = sector.polar(points)
    np.testing.assert_allclose(r[:2], [32, 20])
    np.testing.assert_allclose(theta[:2], [0, 0.3], atol=1e-12)
    assert sector.contains(points).tolist() == [True, True, False, False]
    phases = cine_phases(50, 2)
    assert phases[19] == pytest.approx(0.38)
    np.testing.assert_array_equal(phases[:50], phases[50:])
    assert np.diff(cine_phases(17, 1)) == pytest.approx(np.full(16, 1 / 17))


def test_specular_dropout_at_grazing_incidence() -> None:
    normals = np.array([[0, 1], [1, 1], [1, 0]])
    response = specular_response(normals, np.array([0, 1]), 4)
    np.testing.assert_allclose(response, [1, 0.25, 0], atol=1e-12)
    assert np.isfinite(specular_response(np.zeros(2), np.zeros(2))).all()
    sector = SectorGeometry(64)
    # Vertical lateral wall: beam is nearly tangent; horizontal wall faces beam.
    settings = AcousticSettings(angular_exponent=6)
    _, masks = render_reflectivity(sector, {"RV": np.array([[26, 25], [26, 45], [36, 45], [36, 25]])}, (), {}, settings)
    assert masks["RV"].sum() > 100  # Anatomy survives its angle-dependent echo response.


def test_attenuation_tgc_and_rib_shadow_are_radial() -> None:
    radius = np.array([10, 30, 50], dtype=float)
    theta = np.zeros(3)
    attenuated = AcousticSettings(tgc=0, tgc_curve=0, attenuation=2, shadow_strength=0)
    gain = depth_gain(radius, theta, 64, attenuated)
    assert gain[0] > gain[1] > gain[2]
    compensated = depth_gain(radius, theta, 64, replace(attenuated, tgc=2))
    np.testing.assert_allclose(compensated, 1)
    shadow = replace(attenuated, shadow_angle=0, shadow_strength=0.9)
    assert depth_gain(radius, theta, 64, shadow)[-1] < gain[-1] * 0.2
    assert depth_gain(radius, np.ones(3) * 0.4, 64, shadow)[-1] == pytest.approx(gain[-1])


def test_depth_psf_broadens_transverse_beam() -> None:
    image = np.zeros((96, 96))
    image[20, 48] = image[76, 48] = 1
    blurred = depth_psf(image, AcousticSettings(psf_width=1))
    x2 = (np.arange(96) - 48) ** 2
    widths = [float(np.sum(blurred[y] * x2) / blurred[y].sum()) for y in (20, 76)]
    assert widths[1] > widths[0] * 1.5
    assert blurred[20, 48] > blurred[20, 50]


def test_rayleigh_statistics_and_material_translation() -> None:
    rng = np.random.default_rng(12)
    real, imag = rng.normal(size=(2, 128, 128))
    yy, xx = np.mgrid[:128, :128]
    identity = np.stack([xx, yy], axis=-1)
    field = advected_rayleigh(real, imag, identity)
    assert field.mean() == pytest.approx(1.0, abs=0.02)
    assert field.std() / field.mean() == pytest.approx(np.sqrt((4 - np.pi) / np.pi), abs=0.02)
    reference = np.array([[20, 20], [80, 20], [50, 90]], dtype=float)
    mapping = inverse_tissue_map(reference, reference + [3, 2], 128)
    np.testing.assert_allclose(mapping - identity, np.broadcast_to([-3, -2], identity.shape), atol=1e-10)
    advected = advected_rayleigh(real, imag, mapping)
    np.testing.assert_allclose(advected[4:, 4:], field[2:-2, 1:-3], atol=1e-12)


@pytest.mark.parametrize("kind", ["off_axis", "foreshortened", "rib_occluded"])
def test_unknown_surrogates_retain_label_and_geometry(kind: str) -> None:
    cine = generate_cine(PhantomConfig(view="UNKNOWN", unknown_kind=kind, size=48, frames_per_cycle=12))
    assert cine.config.view == "UNKNOWN" and cine.masks["LV"].any()
    if kind == "rib_occluded":
        assert cine.acoustics.shadow_strength > 0.9


@pytest.mark.parametrize(
    "kwargs",
    [
        {"view": "TEE"},
        {"seed": -1},
        {"seed": 2**63},
        {"fps": 20},
        {"size": 47},
        {"cycles": 4},
        {"frames_per_cycle": 3},
        {"half_angle": float("nan")},
        {"coefficients": (float("inf"),)},
        {"unknown_kind": "fake"},
        {"size": 512, "cycles": 3, "frames_per_cycle": 120},
    ],
)
def test_invalid_configuration_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        PhantomConfig(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [{"speckle_correlation": 1.1}, {"attenuation": -1}, {"psf_width": 0}, {"tgc": float("nan")}, {"shadow_width": 0}],
)
def test_invalid_acoustics_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        AcousticSettings(**kwargs)


def test_temporal_speckle_is_correlated_not_independent_frame_noise() -> None:
    cfg = PhantomConfig(size=48, frames_per_cycle=12, seed=5)
    # Compare equal geometry one cycle apart; only the texture temporal model differs.
    cfg = replace(cfg, cycles=2)
    correlated = generate_cine(cfg, acoustics=AcousticSettings(speckle_correlation=1))
    independent = generate_cine(cfg, acoustics=AcousticSettings(speckle_correlation=0))
    np.testing.assert_array_equal(correlated.frames[0], correlated.frames[12])
    assert not np.array_equal(independent.frames[0], independent.frames[12])
    mask = correlated.sector_mask
    stable_corr = np.corrcoef(correlated.frames[0][mask], correlated.frames[12][mask])[0, 1]
    noise_corr = np.corrcoef(independent.frames[0][mask], independent.frames[12][mask])[0, 1]
    assert stable_corr > noise_corr + 0.05


def test_local_statistical_atlas_can_be_injected_without_changing_view_semantics() -> None:
    atlas = build_cardiac_atlas("A2C")
    local = replace(atlas, mean_ed=atlas.synthesize([2.0]), provenance="local_test_pca")
    config = PhantomConfig(view="A2C", size=48, frames_per_cycle=12, coefficients=(0, 0, 0, 0))
    cine = generate_cine(config, atlas_model=local)
    baseline = generate_cine(config)
    assert cine.atlas_provenance == "local_test_pca"
    assert cine.coefficients == (0, 0, 0, 0)
    assert not np.array_equal(cine.contours["LA"], baseline.contours["LA"])
    with pytest.raises(ValueError, match="does not match"):
        generate_cine(config, atlas_model=build_cardiac_atlas("PSAX"))
