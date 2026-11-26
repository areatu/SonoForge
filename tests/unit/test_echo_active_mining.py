"""Deterministic ML.5 top-K on synthetic prototype/flow evidence; no clinical data."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scripts import mine_uncertain_clips as cli

from echo_personal_tool.domain.services.echo_active_mining import (
    ClipUncertainty,
    normalized_warp_disagreement,
    prototype_distance,
    rank_uncertain_clips,
)


def test_top_k_prefers_ood_a3c_and_disagreeing_rv_over_many_trivial_a4c():
    easy = [ClipUncertainty(i, prototype_distance(np.array([0.95, 0.1, 0.1])), 0.0002, 40) for i in range(100)]
    ood_a3c = ClipUncertainty(101, prototype_distance(np.array([0.1, 0.05, 0.0])), 0.04, 30)
    unstable_rv = ClipUncertainty(102, prototype_distance(np.array([0.9, 0.1, 0.1])), 0.02, 30)
    examples = [*easy, ood_a3c, unstable_rv]
    ranked = rank_uncertain_clips(examples, top_k=2)
    assert [r.clip_index for r in ranked] == [101, 102]
    assert ranked[0].score > ranked[1].score > rank_uncertain_clips(easy, top_k=1)[0].score
    assert rank_uncertain_clips(examples[::-1], top_k=2) == ranked
    assert (
        rank_uncertain_clips([replace(easy[0], clip_index=5), replace(easy[0], clip_index=2)], top_k=2)[0].clip_index
        == 2
    )


def test_flow_disagreement_has_resolution_invariance_and_missing_support_is_not_zero():
    old = np.array([[10.0, 20.0], [20.0, 30.0], [30.0, 40.0], [np.nan, np.nan]])
    new = old + np.array([3.0, 4.0])
    weights = np.array([0.8, 0.9, 1.0, 0.0])
    assert normalized_warp_disagreement(new, old, weights, image_diagonal=100.0) == pytest.approx(0.05)
    assert normalized_warp_disagreement(new * 2, old * 2, weights, image_diagonal=200.0) == pytest.approx(0.05)
    assert normalized_warp_disagreement(new, old, np.zeros(4), image_diagonal=100.0) is None
    row = rank_uncertain_clips([ClipUncertainty(0, 0.9, None, 0)], top_k=1)[0]
    assert row.warp_disagreement is None and row.score == 0.45 and row.valid_warp_nodes == 0
    with pytest.raises(ValueError):
        normalized_warp_disagreement(new, old, weights, image_diagonal=0.0)


@pytest.mark.parametrize(
    "item",
    [
        ClipUncertainty(-1, 0.2, 0.1, 3),
        ClipUncertainty(0, np.nan, 0.1, 3),
        ClipUncertainty(0, 0.2, np.inf, 3),
        ClipUncertainty(0, 0.2, 0.1, 0),
    ],
)
def test_invalid_or_fake_flow_evidence_is_rejected(item):
    with pytest.raises(ValueError):
        rank_uncertain_clips([item])


def test_mining_cli_numeric_input_is_an_anonymous_review_queue_not_new_gold(tmp_path):
    evidence = tmp_path / "numeric.json"
    rows = [
        {"clip_index": i, "cosines": [c, 0.0, 0.0], "warp_disagreement": d, "valid_warp_nodes": 30}
        for i, c, d in [(0, 0.95, 0.0001), (1, 0.1, 0.04), (2, 0.9, 0.02)]
    ]
    evidence.write_text(json.dumps({"schema_version": 1, "clips": rows}))
    args = cli.parse_args(["--evidence", str(evidence), "--output", str(tmp_path / "queue"), "--top-k", "2"])
    path = cli.mine(args)
    data = json.loads(path.read_text())
    assert [r["clip_index"] for r in data["queue"]] == [1, 2]
    assert data["purpose"] == "expert_review_only" and not data["clinical_validated"]
    assert {p.name for p in path.parent.iterdir()} == {"review_queue.json"}
    assert str(tmp_path) not in path.read_text() and "path" not in data["queue"][0]
    with pytest.raises(ValueError, match="already exists"):
        cli.mine(args)
    rows[0]["PatientName"] = "PRIVATE^PATIENT"
    evidence.write_text(json.dumps({"schema_version": 1, "clips": rows}))
    with pytest.raises(ValueError, match="only numeric"):
        cli.load_evidence(evidence)


def test_raw_mining_never_decodes_held_out_splits_or_downloads_weights(tmp_path, monkeypatch):
    from echo_personal_tool.infrastructure import echo_template_engine
    from tests.unit.test_echo_ssl_data import cine, manifest

    paths = []
    for i in range(3):
        path = tmp_path / f"synthetic-{i}.dcm"
        cine(path, patient=f"synthetic-{i}")
        paths.append(path)
    source = manifest(
        tmp_path / "raw.json", [{"path": p.name, "split": split} for p, split in zip(paths, ("train", "val", "test"))]
    )
    monkeypatch.setattr(echo_template_engine, "EchoTemplateEngine", lambda *a, **kw: object())
    decoded = []

    def evidence(engine, clip, index, **kw):
        assert clip.split == "train"
        decoded.append(index)
        return ClipUncertainty(index, 0.5, None, 0)

    monkeypatch.setattr(cli, "clip_evidence", evidence)
    args = cli.parse_args(
        ["--manifest", str(source), "--bundle", str(tmp_path / "local-only"), "--output", str(tmp_path / "queue")]
    )
    path = cli.mine(args)
    assert decoded == [0] and json.loads(path.read_text())["scored_clips"] == 1


def test_script_help_imports_neither_qt_nor_ml_runtime_on_an_uninstalled_checkout():
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    code = """
import builtins
real=builtins.__import__
def guarded(name,*a,**kw):
    if name.split('.')[0] in {'torch','torchvision','onnxruntime','PySide6'}:
        raise AssertionError('eager runtime dependency '+name)
    return real(name,*a,**kw)
builtins.__import__=guarded
import scripts.harvest_weak_labels as harvest
import scripts.mine_uncertain_clips as mine
for cli in (harvest,mine):
    try: cli.parse_args(['--help'])
    except SystemExit as error: assert error.code==0
"""
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "--require-gradient" in result.stdout and "--top-k" in result.stdout
