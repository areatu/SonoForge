"""Synthetic three-anchor reconstruction and real local-store harvest contracts."""

import json
from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from scripts.harvest_weak_labels import accepted_anchors, harvest, main

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.view_recognition import ViewDecision, ViewDecisionSource
from echo_personal_tool.domain.services.cardiac_atlas import build_cardiac_atlas, fit_chamber_landmarks
from echo_personal_tool.domain.services.cardiac_atlas_geometry import CanonicalFrame
from echo_personal_tool.domain.services.echo_weak_labels import reconstruct_weak_shape
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository
from echo_personal_tool.infrastructure.view_decision_store import JsonViewDecisionStore

ANCHORS = np.array([[35.0, 100.0], [90.0, 100.0], [62.0, 30.0]])


@pytest.mark.parametrize("view,chamber", [("A4C", "LV"), ("A4C", "LA"), ("A4C", "RV"), ("A2C", "LA"), ("RV_A4C", "RV")])
def test_three_real_anchors_are_exact_but_interpolated_nodes_remain_weak(view, chamber):
    target = reconstruct_weak_shape(build_cardiac_atlas(view), chamber, ANCHORS, phase="ES")
    frame = CanonicalFrame.from_landmarks(*[tuple(p) for p in ANCHORS])
    np.testing.assert_allclose(target.points[list(target.anchor_indices)], frame.image_to_atlas(ANCHORS), atol=1e-12)
    assert target.points.shape == (81, 2) and np.count_nonzero(target.node_weights == 1) == 3
    assert np.count_nonzero(target.node_weights == 0.15) == 78
    assert target.source == "weak_three_point_atlas" and target.units == "annulus_span"
    assert not target.gradient_refined
    transformed = ANCHORS @ np.array([[0.0, 1.0], [-1.0, 0.0]]) * 1.5 + [200, 100]
    other = reconstruct_weak_shape(build_cardiac_atlas(view), chamber, transformed, phase="ES")
    np.testing.assert_allclose(target.points, other.points, atol=1e-12)


@pytest.mark.parametrize("mixed_batch_kernel", [False, True], ids=["native", "mixed-batch-kernel"])
def test_bounded_gradient_refinement_keeps_all_three_user_anchors(monkeypatch, mixed_batch_kernel):
    if mixed_batch_kernel:
        original_transform = CanonicalFrame.image_to_atlas

        def transform(frame, points):
            values = np.asarray(points)
            if len(values) > 3:
                # Accelerate/BLAS may use a different reduction for the full
                # contour than for its three anchors. Reproduce that rounding
                # distinction on every platform, including Linux CI.
                return np.einsum("ij,kj->ik", values - frame.origin, np.asarray(frame.matrix))
            return original_transform(frame, points)

        monkeypatch.setattr(CanonicalFrame, "image_to_atlas", transform)
    atlas = build_cardiac_atlas("A4C")
    points = np.asarray(fit_chamber_landmarks(atlas, "LV", *[tuple(p) for p in ANCHORS], phase="ED"))
    image = np.zeros((160, 128), np.float32)
    cv2.polylines(image, [np.rint(points).astype(np.int32)], False, 1.0, 2)
    target = reconstruct_weak_shape(atlas, "LV", ANCHORS, phase="ED", image=image)
    canonical = CanonicalFrame.from_landmarks(*[tuple(p) for p in ANCHORS])
    # An absolute bound is essential at the apex's near-zero canonical X;
    # rtol alone rejects ordinary cross-kernel roundoff (~1e-18).
    np.testing.assert_allclose(
        target.points[list(target.anchor_indices)], canonical.image_to_atlas(ANCHORS), rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(
        canonical.atlas_to_image(target.points[list(target.anchor_indices)]), ANCHORS, rtol=0, atol=1e-10
    )
    assert target.gradient_refined
    np.testing.assert_array_equal(target.node_weights[list(target.anchor_indices)], np.ones(3))
    flat = reconstruct_weak_shape(atlas, "LV", ANCHORS, phase="ED", image=np.zeros_like(image))
    assert not flat.gradient_refined


@pytest.mark.parametrize(
    "anchors",
    [np.full((3, 2), np.nan), np.zeros((3, 2)), np.array([[0.0, 0.0], [10.0, 0.0], [5.0, 0.0]]), np.ones((2, 2))],
)
def test_weak_geometry_rejects_missing_or_degenerate_anchors(anchors):
    with pytest.raises(ValueError):
        reconstruct_weak_shape(build_cardiac_atlas("A4C"), "LV", anchors, phase="ED")


def local_stores(tmp_path):
    study, sop, series = "1.2.693", "1.2.693.1", "1.2.693.2"
    contour = Contour(
        "ED",
        chamber="LV",
        points=[tuple(p) for p in ANCHORS[[0, 2, 1]]],
        num_nodes=3,
        mitral_annulus=tuple(tuple(p) for p in ANCHORS[:2]),
        apex_landmark=tuple(ANCHORS[2]),
        frame_index=0,
        sop_instance_uid=sop,
    )
    repository = MeasurementRepository(tmp_path / "measurements")
    repository.save(
        study,
        StudyMeasurementData(contours=(contour,)),
        {sop: {"fingerprint": "a" * 64, "frames": 2, "spacing": None}},
        expected_revision=0,
    )
    store = JsonViewDecisionStore(tmp_path / "decisions")
    choice = ViewDecision(study, series, "A4C", ViewDecisionSource.MANUAL, 1.0, None)
    store.save(choice)
    path = tmp_path / "index.json"
    path.write_text(
        json.dumps({"schema_version": 1, "studies": [{"study_uid": study, "instance_to_series": {sop: series}}]})
    )
    return repository, store, choice, contour, path


def test_harvest_uses_actual_accepted_stores_without_dicom_reads_pixels_or_identifiers(tmp_path, monkeypatch):
    import pydicom

    repository, store, choice, contour, index = local_stores(tmp_path)

    def no_dicom(*args, **kwargs):
        raise AssertionError("PHI DICOM reads forbidden in harvest")

    monkeypatch.setattr(pydicom, "dcmread", no_dicom)
    args = SimpleNamespace(
        index=index,
        measurements_dir=repository.root,
        view_decisions_dir=store.directory,
        output=tmp_path / "output",
        require_gradient=False,
    )
    path = harvest(args)
    data = json.loads(path.read_text())
    assert data["kind"] == "weak_shape_targets_not_image_gold" and len(data["examples"]) == 1
    assert data["counts"]["accepted_anchor_sets"] == 1
    assert {p.name for p in path.parent.iterdir()} == {"weak_shapes.json"}
    assert not data["examples"][0]["gradient_refined"] and data["examples"][0]["source"].startswith("weak_")
    assert choice.study_uid not in path.read_text() and str(tmp_path) not in path.read_text()
    assert repository.load(choice.study_uid)["data"].contours[0] == contour
    assert store.load(choice.study_uid, choice.series_uid) == choice
    with pytest.raises(ValueError, match="already exists"):
        harvest(args)
    args.output = tmp_path / "gradient-required"
    args.require_gradient = True
    rejected = json.loads(harvest(args).read_text())
    assert rejected["examples"] == [] and rejected["counts"]["missing_sector"] == 1


def test_pending_automatic_mismatched_and_conflicting_anchor_sets_are_not_harvested(tmp_path):
    _, _, choice, contour, _ = local_stores(tmp_path)
    mapping = {contour.sop_instance_uid: choice.series_uid}
    for item in (
        replace(contour, review_pending=True),
        replace(contour, apex_landmark=None),
        replace(contour, view="A2C"),
    ):
        assert not accepted_anchors(StudyMeasurementData(contours=(item,)), mapping, {choice.series_uid: choice})
    for source in (ViewDecisionSource.AUTO, ViewDecisionSource.AUTO_STUDY_CONTEXT):
        assert not accepted_anchors(
            StudyMeasurementData(contours=(contour,)), mapping, {choice.series_uid: replace(choice, source=source)}
        )
    conflicting = replace(contour, apex_landmark=(60.0, 40.0))
    assert not accepted_anchors(
        StudyMeasurementData(contours=(contour, conflicting)), mapping, {choice.series_uid: choice}
    )
    assert (
        len(accepted_anchors(StudyMeasurementData(contours=(contour, contour)), mapping, {choice.series_uid: choice}))
        == 1
    )

    other = replace(contour, chamber="LA", mitral_annulus=((30.0, 100.0), (95.0, 100.0)), apex_landmark=(60.0, 150.0))
    assert not accepted_anchors(StudyMeasurementData(contours=(contour, other)), mapping, {choice.series_uid: choice})


def test_harvest_failure_does_not_print_private_paths_or_store_payload(tmp_path, capsys):
    private = tmp_path / "PRIVATE-PATIENT"
    status = main(
        [
            "--index",
            str(private),
            "--measurements-dir",
            str(private),
            "--view-decisions-dir",
            str(private),
            "--output",
            str(tmp_path / "not-created"),
        ]
    )
    captured = capsys.readouterr()
    assert status == 2 and "PRIVATE" not in captured.err and "failed" in captured.err
    assert not (tmp_path / "not-created").exists()
