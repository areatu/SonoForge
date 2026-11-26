"""Numerical eight-head + real NCC mining smoke without optional ONNX/torch."""

from types import SimpleNamespace

import numpy as np
from scripts import mine_uncertain_clips as cli

from echo_personal_tool.domain.services.echo_template_contract import default_atlases
from echo_personal_tool.domain.services.segmentation_service import EchoNetCropTransform
from tests.unit.test_echo_template_core import numerical_heads


def test_actual_ncc_mining_measures_injected_template_disagreement(monkeypatch):
    rng = np.random.default_rng(693)
    texture = rng.uniform(0.1, 1.0, (128, 128)).astype(np.float32)
    frames = np.repeat(texture[None], 4, axis=0)
    monkeypatch.setattr(cli, "read_raw_clip", lambda *a, **kw: (frames, None, None, None))

    class Engine:
        input_size = 128
        atlases = default_atlases()
        ood = {"min_cosine": 0.25, "min_confidence": 0.35, "max_entropy": 0.88}
        calls = 0

        def raw(self, frame):
            heads = numerical_heads()
            heads["pose"][:, :, 0] += 0.015 * (self.calls % 2)
            self.calls += 1
            return heads, EchoNetCropTransform(128, 128, 0, 0, 128, 128)

    result = cli.clip_evidence(Engine(), SimpleNamespace(view=None), 7, max_frames=4)
    assert result.clip_index == 7 and result.valid_warp_nodes >= 3
    assert result.prototype_distance == 0.04999999999999999
    assert result.warp_disagreement is not None and result.warp_disagreement > 0.005
    # Texture dropout produces missing flow evidence, not synthetic perfect flow.
    frames.fill(0.0)
    dropped = cli.clip_evidence(Engine(), SimpleNamespace(view=None), 8, max_frames=4)
    assert dropped.valid_warp_nodes == 0 and dropped.warp_disagreement is None
