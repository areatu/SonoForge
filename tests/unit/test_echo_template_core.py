"""ML.3 pure train/serve contract, connected topology and review safety."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.application.segmentation_jobs import SegmentationBasis, SegmentationJobs
from echo_personal_tool.application.template_segmentation_delivery import template_review_contours
from echo_personal_tool.domain.calculations.rv_fac import from_rv_contours
from echo_personal_tool.domain.services.echo_template_contract import (
    MAX_TEMPLATE_MODES,
    MAX_TEMPLATE_NODES,
    TEMPLATE_VIEWS,
    TemplatePrediction,
    default_atlases,
    node_normals,
    points_from_crop,
    points_to_crop,
    prepare_template_input,
    validate_atlases,
)
from echo_personal_tool.domain.services.echo_template_service import (
    decode_template_prediction,
    validate_template_outputs,
)
from echo_personal_tool.domain.services.rv_strain import select_rv_free_wall_contour
from echo_personal_tool.domain.services.segmentation_service import EchoNetCropTransform
from echo_personal_tool.infrastructure.echo_template_engine import EchoTemplateEngine, verified_bundle_file


def numerical_heads(view="A4C"):
    count = len(TEMPLATE_VIEWS)
    outputs = {
        "heatmaps": np.zeros((1, 9, 16, 16)),
        "visibility": np.ones((1, 9)) * 10,
        "view_logits": np.zeros((1, count)),
        "view_cosines": np.zeros((1, count)),
        "pose": np.tile([0.55, 0.4, 1, 0, np.log(1 / 200)], (1, count, 1)),
        "coefficients": np.zeros((1, count, MAX_TEMPLATE_MODES)),
        "offsets": np.zeros((1, count, MAX_TEMPLATE_NODES)),
        "phase_logits": np.zeros((1, 2)),
    }
    index = TEMPLATE_VIEWS.index(view)
    outputs["view_logits"][0, index], outputs["view_cosines"][0, index] = 12, 0.9
    return outputs


def decode(outputs=None, **kwargs):
    transform = EchoNetCropTransform(200, 200, 0, 0, 200, 200)
    return decode_template_prediction(
        outputs or numerical_heads(),
        default_atlases(),
        transform,
        np.zeros((200, 200)),
        phase="ED",
        frame_index=0,
        pixel_spacing=(0.5, 0.5),
        sector_mask=np.ones((200, 200), bool),
        refine_rv=False,
        **kwargs,
    )


def test_decoder_uses_one_mesh_for_shared_valves_and_septum():
    result = decode()
    assert result.view == "A4C" and result.reject_reason is None
    chambers = {c.chamber: c for c in result.contours}
    assert set(chambers) == {"LV", "LA", "RV"}
    assert all(c.review_pending and c.source == "ai" for c in result.contours)
    np.testing.assert_array_equal(np.array(chambers["LV"].points)[[0, -1]], np.array(chambers["LA"].points)[[0, -1]])
    model = default_atlases()["A4C"]
    lv_map = dict(zip(model.structures["LV"], chambers["LV"].points))
    for idx, point in zip(model.structures["RV"], chambers["RV"].points):
        if idx in lv_map:
            np.testing.assert_array_equal(point, lv_map[idx])
    changed = numerical_heads()
    changed["coefficients"][:] = 3
    changed["offsets"][:] = 5
    assert all(c.review_pending for c in decode(changed).contours)


def test_ood_and_manual_view_contract():
    outputs = numerical_heads()
    outputs["view_logits"][:] = 0
    assert decode(outputs).view == "UNKNOWN" and not decode(outputs).contours
    outputs = numerical_heads()
    outputs["view_cosines"][:] = 0
    assert decode(outputs).reject_reason == "view_unknown"
    result = decode(numerical_heads("A4C"), requested_view="A2C")
    assert result.view == "A2C" and {c.chamber for c in result.contours} == {"LV", "LA"}
    with pytest.raises(ValueError, match="requested view"):
        decode(requested_view="TEE")


@pytest.mark.parametrize("mutation", ["nan", "shape", "cosine", "heatmaps", "names"])
def test_numerical_output_schema_is_fail_closed(mutation):
    outputs = numerical_heads()
    if mutation == "nan":
        outputs["pose"][0, 0, 0] = np.nan
    if mutation == "shape":
        outputs["coefficients"] = np.zeros((1, 7, 4))
    if mutation == "cosine":
        outputs["view_cosines"][:] = 2
    if mutation == "heatmaps":
        outputs["heatmaps"] = np.zeros((1, 8, 16, 16))
    if mutation == "names":
        outputs.pop("phase_logits")
    with pytest.raises(ValueError):
        validate_template_outputs(outputs)


def test_invalid_pose_and_off_image_are_rejections_not_clipped_shapes():
    outputs = numerical_heads()
    outputs["pose"][0, :, 2:4] = 0
    assert decode(outputs).reject_reason == "degenerate_pose"
    outputs = numerical_heads()
    outputs["pose"][0, :, :2] = 5
    result = decode(outputs)
    assert result.reject_reason == "outside_image" and not result.contours


def test_preprocess_round_trip_and_coordinate_channels_are_shared():
    frame = np.zeros((96, 160, 3), np.uint8)
    frame[12:90, 30:130] = 80
    one, transform = prepare_template_input(frame, input_size=64)
    two, second = prepare_template_input(frame.copy(), input_size=64)
    np.testing.assert_array_equal(one, two)
    assert transform == second and one.shape == (1, 3, 64, 64)
    np.testing.assert_allclose(one[0, 1, :, 0], np.linspace(-1, 1, 64), atol=1e-7)
    np.testing.assert_allclose(one[0, 2, 0, :], np.linspace(-1, 1, 64), atol=1e-7)
    points = np.array([[40, 30], [110, 75]], float)
    np.testing.assert_allclose(points_from_crop(points_to_crop(points, transform), transform), points, atol=1e-10)
    with pytest.raises(ValueError):
        prepare_template_input(frame, input_size=63)
    with pytest.raises(ValueError):
        prepare_template_input(np.full((64, 64), np.nan))
    bank = default_atlases()
    validate_atlases(bank)
    assert np.isfinite(node_normals(bank["PSAX"])).all()
    with pytest.raises(ValueError):
        validate_atlases({"A4C": bank["A4C"]})


def test_review_proposals_do_not_change_fac_strain_or_report_inputs():
    prediction = decode()
    proposals = template_review_contours(prediction, frame_index=0, sop_instance_uid="synthetic")
    es = tuple(replace(c, phase="ES", points=[(x, y * 0.8) for x, y in c.points]) for c in proposals)
    assert from_rv_contours(proposals + es, (0.5, 0.5)) is None
    assert select_rv_free_wall_contour(proposals, sop_instance_uid="synthetic", view="A4C") is None
    accepted = tuple(replace(c, review_pending=False) for c in proposals + es)
    assert from_rv_contours(accepted, (0.5, 0.5)) is not None
    assert select_rv_free_wall_contour(accepted, sop_instance_uid="synthetic", view="A4C") is not None
    # Existing confirmed inputs remain identical when a pending proposal is appended.
    baseline = from_rv_contours(accepted, (0.5, 0.5))
    assert from_rv_contours(accepted + proposals, (0.5, 0.5)) == baseline
    with pytest.raises(ValueError):
        template_review_contours(prediction, frame_index=1, sop_instance_uid="synthetic")
    with pytest.raises(ValueError):
        template_review_contours(
            replace(prediction, contours=(replace(proposals[0], review_pending=False),)),
            frame_index=0,
            sop_instance_uid="synthetic",
        )
    assert (
        template_review_contours(TemplatePrediction("UNKNOWN", 0.1), frame_index=0, sop_instance_uid="synthetic") == ()
    )


def test_template_delivery_reuses_segmentation_owner_for_stale_and_aba():
    jobs = SegmentationJobs()
    basis = SegmentationBasis("study", 1, "sop", "/cine.dcm", ((0.5, 0.5), 1), 30.0, (), 0, 0, False, ())
    ticket = jobs.begin(basis)
    jobs.invalidate()
    assert jobs.finish(ticket, basis) is False
    old = jobs.begin(basis)
    current = jobs.begin(basis)
    assert jobs.finish(old, basis) is None
    assert jobs.finish(current, basis) is True
    assert template_review_contours(decode(), frame_index=0, sop_instance_uid="sop")
    assert jobs.finish(current, basis) is None


def test_model_artifact_hash_and_path_are_checked_before_runtime(tmp_path: Path):
    source = tmp_path / "model.onnx"
    source.write_bytes(b"not a clinical model")
    record = {"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    assert verified_bundle_file(tmp_path, record, max_bytes=1024) == source
    with pytest.raises(ValueError, match="escapes"):
        verified_bundle_file(tmp_path, {**record, "path": "../model.onnx"}, max_bytes=1024)
    with pytest.raises(ValueError, match="SHA-256"):
        verified_bundle_file(tmp_path, {**record, "sha256": "0" * 64}, max_bytes=1024)
    with pytest.raises(ValueError, match="oversized"):
        verified_bundle_file(tmp_path, record, max_bytes=1)
    (tmp_path / "model_manifest.json").write_text(json.dumps({"echo_template": {"schema_version": 0}}))
    with pytest.raises(ValueError, match="schema"):
        EchoTemplateEngine(tmp_path)
