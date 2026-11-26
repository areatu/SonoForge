"""Bounded raw-DICOM SSL integration, with no downloads or clinical claims.

The positive-control model has one deliberately injected scanner-jitter weight;
this tests the training/gold gate end to end, not MobileNet clinical accuracy.
"""

import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from tests.unit.test_echo_ssl_training import torch_runtime


@pytest.fixture(autouse=True)
def optional_torch():
    torch_runtime()


def jitter_model():
    torch = torch_runtime()
    from echo_personal_tool.domain.services.echo_template_contract import TEMPLATE_OUTPUTS
    from tests.unit.test_echo_template_core import numerical_heads

    class InjectedJitter(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.amplitude = torch.nn.Parameter(torch.tensor(0.025))

        def forward(self, image):
            heads = numerical_heads()
            outputs = [
                torch.tensor(heads[k], dtype=image.dtype).repeat(len(image), *([1] * (heads[k].ndim - 1)))
                for k in TEMPLATE_OUTPUTS
            ]
            # Inject a nuisance sensitivity, not a desired displacement label.
            signal = image[:, 0, :8, :8].mean((-1, -2))
            outputs[4][:, :, 0] = outputs[4][:, :, 0] + self.amplitude * signal[:, None]
            outputs[7][:, 0], outputs[7][:, 1] = 12.0, -12.0
            return tuple(outputs)

    return InjectedJitter()


def prepare_inputs(tmp_path):
    from scripts.echo_ssl_data import RawClip, read_raw_clip
    from scripts.echo_template_data import TemplateSample

    from echo_personal_tool.domain.services.echo_template_contract import default_atlases
    from tests.unit.test_echo_ssl_data import cine, manifest

    paths = []
    gold = []
    atlas = default_atlases()["A4C"]
    for index, split in enumerate(("train", "val", "val")):
        path = tmp_path / f"synthetic-{index}.dcm"
        ds = cine(path, patient=f"SYNTHETIC-{index}")
        ds.Rows, ds.Columns, ds.NumberOfFrames = 128, 128, 12
        texture = np.random.default_rng(692 + index).integers(30, 220, (128, 128), dtype=np.uint8)
        pixels = np.repeat(texture[None], 12, axis=0)
        pixels[:, :8, :] = pixels[:, -8:, :] = 0
        pixels[:, :, :8] = pixels[:, :, -8:] = 0
        for t in range(12):
            pixels[t, 8:24, 8:24] = 40 if t % 2 else 210
        ds.PixelData = pixels.tobytes()
        ds.save_as(path, enforce_file_format=True)
        paths.append(path)
        if index == 2:
            _, _, transforms, _ = read_raw_clip(RawClip(path, "gold", split), input_size=64, max_frames=12)
            for t in (0, 1):
                transform = transforms[t]
                mesh = (atlas.mean_ed / 200 + [0.55, 0.4]) * [transform.crop_width, transform.crop_height] + [
                    transform.crop_x0,
                    transform.crop_y0,
                ]
                gold.append(
                    TemplateSample(
                        path,
                        t,
                        "A4C",
                        "ED",
                        "gold",
                        "gold",
                        split="val",
                        contours={c: mesh[list(atlas.structures[c])] for c in ("LV", "LA", "RV")},
                    )
                )
    raw = manifest(
        tmp_path / "raw.json",
        [{"path": p.name, "split": split, "view": "A4C"} for p, split in zip(paths, ("train", "val", "val"))][:2],
    )
    return raw, gold


def checkpoint(path, model):
    torch = torch_runtime()
    from echo_personal_tool.domain.services.echo_template_contract import TEMPLATE_VIEWS, default_atlases

    torch.save(
        {
            "schema_version": 1,
            "architecture": "mobilenet_v3_small_fpn_template_v1",
            "input_size": 64,
            "class_names": list(TEMPLATE_VIEWS),
            "state_dict": model.state_dict(),
            "atlases": {k: v.to_dict() for k, v in default_atlases().items()},
        },
        path,
    )
    return path


def test_positive_control_raw_ssl_reduces_la_rv_jitter_without_gold_degradation(tmp_path, monkeypatch):
    from scripts import train_self_supervised_echo as cli

    raw, gold = prepare_inputs(tmp_path)
    model = jitter_model()
    monkeypatch.setattr(cli, "build_template_network", lambda: copy.deepcopy(model))
    monkeypatch.setattr(cli, "load_gold_samples", lambda _: gold)
    args = cli.parse_args(
        [
            "--manifest",
            str(raw),
            "--checkpoint",
            str(checkpoint(tmp_path / "source.pt", model)),
            "--output",
            str(tmp_path / "ssl"),
            "--epochs",
            "4",
            "--input-size",
            "64",
            "--max-frames",
            "12",
            "--lr",
            ".005",
            "--smoke",
        ]
    )
    target = cli.train(args)
    report = json.loads((target.parent / "ssl_report.json").read_text())
    assert report["accepted"] is True and target.name == "checkpoint.pt"
    assert all(e["training"][0]["trained"] for e in report["history"])
    passed = [e for e in report["history"] if e["accepted"]]
    for evidence in passed:
        assert evidence["jitter_after_px"]["LA"] < evidence["jitter_before_px"]["LA"] * 0.99
        assert evidence["jitter_after_px"]["RV"] < evidence["jitter_before_px"]["RV"] * 0.99
        for key in ("LA_iou", "RV_iou", "LV_iou"):
            assert evidence["gold_after"][key] >= evidence["gold_before"][key] - 1e-9
        assert evidence["gold_after"]["node_error_px"] <= evidence["gold_before"]["node_error_px"] + 1e-9
    # No decoded arrays, paths, IDs, optimizer or per-frame pseudo-labels in output.
    assert {p.name for p in target.parent.iterdir()} == {"checkpoint.pt", "ssl_report.json"}
    text = (target.parent / "ssl_report.json").read_text()
    assert "SYNTHETIC-" not in text and str(tmp_path) not in text
    print(json.dumps(passed[-1], sort_keys=True))


def test_actual_architecture_smoke_without_evidence_stays_rejected_and_cannot_export(tmp_path):
    from scripts import train_self_supervised_echo as cli
    from scripts.echo_template_network import build_template_network
    from scripts.export_echo_template_onnx import export_bundle

    raw, _ = prepare_inputs(tmp_path)
    model = build_template_network()
    args = cli.parse_args(
        [
            "--manifest",
            str(raw),
            "--checkpoint",
            str(checkpoint(tmp_path / "source.pt", model)),
            "--output",
            str(tmp_path / "ssl"),
            "--epochs",
            "1",
            "--input-size",
            "64",
            "--max-frames",
            "12",
            "--smoke",
        ]
    )
    target = cli.train(args)
    report = json.loads((target.parent / "ssl_report.json").read_text())
    assert not report["accepted"] and target.name == "candidate_rejected.pt"
    assert "incomplete_gold" in report["history"][0]["reject_reasons"]
    for package in ("onnx", "onnxruntime"):
        pytest.importorskip(package)
    with pytest.raises(ValueError, match="held-out acceptance"):
        export_bundle(SimpleNamespace(checkpoint=target, output=tmp_path / "export", runs=5, max_p95_ms=200))
    assert not (tmp_path / "export").exists()
