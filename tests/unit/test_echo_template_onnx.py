"""Optional ML toolchain E2E: tiny synthetic -> gold -> verified ONNX candidate.

This test asserts numerical/IO safety, never clinical quality or timing on CI.
"""

import json

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("torchvision")
pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")

from scripts.echo_template_data import load_synthetic_samples
from scripts.echo_template_losses import atlas_bank_arrays, crossing_penalty, decode_torch_mesh
from scripts.export_echo_template_onnx import export_bundle
from scripts.generate_synthetic_echo_corpus import main as generate_main
from scripts.run_rv_auto_bench import evaluate_rv_gold
from scripts.train_echo_template_multitask import parse_args, train

from echo_personal_tool.domain.services.echo_template_contract import default_atlases
from echo_personal_tool.infrastructure.echo_template_engine import EchoTemplateEngine
from tests.unit.test_echo_template_core import numerical_heads


def test_differentiable_geometry_matches_numpy_before_safety_backtracking():
    import torch

    from echo_personal_tool.domain.services.echo_template_contract import TEMPLATE_OUTPUTS, TEMPLATE_VIEWS
    from echo_personal_tool.domain.services.echo_template_service import decode_template_prediction
    from echo_personal_tool.domain.services.segmentation_service import EchoNetCropTransform

    bank = {k: torch.from_numpy(v) for k, v in atlas_bank_arrays(default_atlases()).items()}
    heads = numerical_heads()
    outputs = [torch.tensor(heads[k], dtype=torch.float32) for k in TEMPLATE_OUTPUTS]
    index = TEMPLATE_VIEWS.index("A4C")
    points = decode_torch_mesh(outputs, torch.tensor([index]), torch.tensor([0]), bank).numpy()[0]
    prediction = decode_template_prediction(
        heads,
        default_atlases(),
        EchoNetCropTransform(200, 200, 0, 0, 200, 200),
        np.zeros((200, 200)),
        phase="ED",
        frame_index=0,
        pixel_spacing=(0.5, 0.5),
        sector_mask=np.ones((200, 200), bool),
        refine_rv=False,
    )
    ids = list(default_atlases()["A4C"].structures["LV"])
    np.testing.assert_allclose(points[ids] * 200, prediction.contours[0].points, atol=2e-5)
    crossed = torch.tensor([[[0.0, 0.0], [1.0, 1.0], [0.0, 1.0], [1.3, 0.2]]], requires_grad=True)
    penalty = crossing_penalty(crossed, torch.tensor([[[0, 1, 2, 3]]]), torch.ones(1, 1))
    assert penalty.item() > 0
    penalty.backward()
    assert torch.isfinite(crossed.grad).all() and crossed.grad.abs().sum() > 0


def test_two_stage_local_pipeline_exports_candidate_without_changing_review_policy(tmp_path):
    from types import SimpleNamespace

    corpus, output, bundle = tmp_path / "corpus", tmp_path / "train", tmp_path / "bundle"
    assert (
        generate_main(
            [
                "--output",
                str(corpus),
                "--views",
                "A4C",
                "UNKNOWN",
                "--size",
                "48",
                "--frames-per-cycle",
                "12",
                "--subjects",
                "1",
                "--seed",
                "691",
            ]
        )
        == 0
    )
    samples = load_synthetic_samples(corpus / "manifest.json")
    assert len(samples) == 4
    gold_path = next((corpus / "gold").glob("rv_*.json"))
    gold = json.loads(gold_path.read_text())
    gold["patient_group_id"] = samples[0].group_id
    gold["split"] = "train"
    gold_path.write_text(json.dumps(gold))
    checkpoint = train(
        parse_args(
            [
                "--output",
                str(output),
                "--synthetic-manifest",
                str(corpus / "manifest.json"),
                "--gold",
                str(gold_path),
                "--input-size",
                "64",
                "--epochs",
                "1",
                "--batch-size",
                "2",
                "--allow-random-init",
                "--allow-no-val-for-smoke",
            ]
        )
    )
    report = json.loads((output / "training_report.json").read_text())
    assert {item["stage"] for item in report["history"]} == {"synthetic", "gold"}
    assert report["clinical_validated"] is False
    manifest = export_bundle(SimpleNamespace(checkpoint=checkpoint, output=bundle, runs=5, max_p95_ms=200))
    assert manifest.is_file()
    with pytest.raises(ValueError, match="opt-in"):
        EchoTemplateEngine(bundle)
    engine = EchoTemplateEngine(bundle, allow_unvalidated=True)
    frame = np.zeros((64, 64), np.uint8)
    outputs, transform = engine.raw(frame)
    assert len(outputs) == 8 and transform.frame_width == 64
    bench = evaluate_rv_gold([gold_path], engine)
    assert bench["frames"] == 2 and bench["clinical_validated"] is False
    assert bench["fac_pairs_evaluable"] <= bench["fac_pairs_total"]
    verification = json.loads((bundle / "export_verification.json").read_text())
    assert max(verification["head_max_abs_errors"].values()) < 1e-4
    assert verification["onnx_bytes"] < 12 * 1024 * 1024
    # Tampering never loads into a new session.
    model_path = bundle / "echo_template.onnx"
    model_path.write_bytes(model_path.read_bytes() + b"modified")
    with pytest.raises(ValueError, match="SHA-256"):
        EchoTemplateEngine(bundle, allow_unvalidated=True)

    synthetic_manifest = json.loads((corpus / "manifest.json").read_text())
    synthetic_manifest["samples"][0]["split"] = "test"
    (corpus / "manifest.json").write_text(json.dumps(synthetic_manifest))
    with pytest.raises(ValueError, match="split mismatch"):
        load_synthetic_samples(corpus / "manifest.json")
