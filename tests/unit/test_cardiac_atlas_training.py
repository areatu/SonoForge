"""Offline local annotation contracts and explicit opt-in atlas integrations."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from scripts.fit_cardiac_atlas_pca import main

from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel, build_cardiac_atlas
from echo_personal_tool.domain.services.la_segmentation_service import la_mask_to_contour
from echo_personal_tool.domain.services.mbs_lite_service import fit_contour_from_landmarks
from echo_personal_tool.domain.services.rv_shape_template import warp_rv_crescent_open_arc


def test_cli_canonical_samples_are_reproducible_and_numeric_only(tmp_path: Path) -> None:
    seed = build_cardiac_atlas()
    source = tmp_path / "private-study-name.json"
    source.write_text(
        json.dumps(
            {
                "atlas_samples": [
                    {"view": "A4C", "phase": "ED", "canonical_points_mm": seed.synthesize([b]).tolist()}
                    for b in (-0.7, -0.1, 0.2, 0.7)
                ]
            }
        )
    )
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    for output in (first, second):
        assert main(["--input", str(source), "--view", "A4C", "--max-modes", "2", "--output", str(output)]) == 0
    assert first.read_bytes() == second.read_bytes()
    assert "private-study-name" not in first.read_text()
    artifact = json.loads(first.read_text())
    assert artifact["training_summary"]["observations"] == 4
    fitted = CoupledShapeModel.from_dict(artifact)
    assert fitted.violations(fitted.synthesize([0.2])) == ()


def test_cli_gold_open_arcs_with_reviewed_anchors(tmp_path: Path) -> None:
    seed = build_cardiac_atlas("A2C")
    ids = list(seed.structures["LV"])
    mesh = seed.mean_ed + [100, 100]
    source = tmp_path / "lv_private.json"
    frame = {
        "phase": "ED",
        "view": "A2C",
        "chamber": "LV",
        "points": mesh[ids].tolist(),
        "mitral_annulus": mesh[[ids[0], ids[-1]]].tolist(),
        "apex_landmark": mesh[seed.landmarks["LV_apex"]].tolist(),
        "pixel_spacing_mm": [1, 1],
    }
    source.write_text(json.dumps({"study_id": "private", "frames": [frame, frame]}))
    output = tmp_path / "atlas.json"
    assert main(["--input", str(source), "--view", "A2C", "--output", str(output)]) == 0
    artifact = json.loads(output.read_text())
    assert artifact["training_summary"]["calibrated_or_canonical"] == 2
    assert "private" not in output.read_text()
    source.write_text(json.dumps({"frames": [{**frame, "phase": "UNKNOWN"}]}))
    output.unlink()
    assert main(["--input", str(source), "--view", "A2C", "--output", str(output)]) == 2
    assert not output.exists()


def test_teaching_requires_explicit_phase_and_correspondence_opt_in(tmp_path: Path) -> None:
    model = build_cardiac_atlas()
    ids = list(model.structures["LV"])
    mesh = model.mean_ed + [100, 100]
    sidecar = tmp_path / "prepared_anatomy.json"
    payload = {
        "version": 1,
        "width": 256,
        "height": 256,
        "view": "A4C",
        "source_sha256": "a" * 64,
        "position": "left_lateral",
        "frames": {"0": [{"id": "lv", "points": (mesh[ids] / 255).tolist()}]},
    }
    sidecar.write_text(json.dumps(payload))
    original = sidecar.read_bytes()
    output = tmp_path / "atlas.json"
    assert main(["--input", str(sidecar), "--view", "A4C", "--output", str(output)]) == 2
    review = {
        "path": sidecar.name,
        "frame_index": 0,
        "phase": "ED",
        "reference_chamber": "LV",
        "anchors": {
            "septal": mesh[ids[0]].tolist(),
            "lateral": mesh[ids[-1]].tolist(),
            "apex": mesh[model.landmarks["LV_apex"]].tolist(),
        },
        "node_order": {"LV": list(range(32))},
        "pixel_spacing_mm": [1, 1],
    }
    manifest = tmp_path / "reviewed-teaching.json"
    manifest.write_text(json.dumps({"teaching_samples": [review, review]}))
    assert main(["--teaching-manifest", str(manifest), "--view", "A4C", "--output", str(output)]) == 0
    assert json.loads(output.read_text())["training_summary"]["teaching_opt_in"] is True
    assert sidecar.read_bytes() == original


@pytest.mark.parametrize("chamber", ["LV", "LA", "RV", "RA"])
def test_mbs_opt_in_atlas_keeps_contract_and_exact_anchors(chamber: str) -> None:
    kwargs = {
        "septal": (30.0, 100.0),
        "lateral": (100.0, 100.0),
        "apex": (65.0, 30.0),
        "phase": "ES",
        "chamber": chamber,
    }
    legacy = fit_contour_from_landmarks(**kwargs)
    same = fit_contour_from_landmarks(**kwargs, atlas_model=None)
    assert legacy.points == same.points
    fitted = fit_contour_from_landmarks(**kwargs, atlas_model=build_cardiac_atlas())
    assert fitted.points[0] == kwargs["septal"] and fitted.points[-1] == kwargs["lateral"]
    assert fitted.mitral_annulus == legacy.mitral_annulus
    assert fitted.chamber == chamber and fitted.source == "model"
    assert len(fitted.points) == len(legacy.points)
    with pytest.raises(ValueError, match="projection"):
        fit_contour_from_landmarks(**kwargs, atlas_model=build_cardiac_atlas("A2C"))


def test_rv_opt_in_prior_has_stable_arc_under_missing_image_signal() -> None:
    anchors = [(100.0, 20.0), (20.0, 20.0), (60.0, 80.0)]
    points = warp_rv_crescent_open_arc(*anchors, atlas_model=build_cardiac_atlas("RV_A4C"))
    assert len(points) == 81
    np.testing.assert_allclose(np.asarray(points)[[0, -1, 40]], anchors)
    assert np.isfinite(points).all()


def test_la_retains_observed_mask_and_uses_atlas_only_on_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from echo_personal_tool.domain.services import la_segmentation_service as service

    yy, xx = np.indices((224, 224))
    mask = (((xx - 112) / 40) ** 2 + ((yy - 140) / 50) ** 2 <= 1).astype(np.uint8)
    legacy = la_mask_to_contour(mask)
    atlas = build_cardiac_atlas()
    observed = la_mask_to_contour(mask, atlas_model=atlas)
    np.testing.assert_allclose(observed[0], legacy[0])
    monkeypatch.setattr(service, "la_mask_boundary_to_open_arc", lambda *_a, **_kw: None)
    points, annulus, apex = la_mask_to_contour(mask, atlas_model=atlas)
    assert points[0] == annulus[0] and points[-1] == annulus[1]
    assert len(points) == 32 and np.isfinite(points).all()
    assert apex[1] < annulus[0][1]


def test_cli_never_overwrites_source_annotations(tmp_path: Path) -> None:
    source = tmp_path / "annotations.json"
    source.write_text('{"atlas_samples": []}')
    before = source.read_bytes()
    assert main(["--input", str(source), "--view", "A4C", "--output", str(source)]) == 2
    assert source.read_bytes() == before
