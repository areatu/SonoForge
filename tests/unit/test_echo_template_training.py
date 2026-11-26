"""Local corpus/gold adapters: partial labels and patient-level leakage guards."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from scripts.echo_template_data import (
    RVGoldDataset,
    TemplateDataset,
    TemplateSample,
    assign_group_splits,
    load_gold_samples,
    training_target,
)

from echo_personal_tool.domain.services.echo_template_contract import default_atlases
from echo_personal_tool.domain.services.segmentation_service import EchoNetCropTransform


def test_group_splits_are_deterministic_across_sources_and_fail_on_leakage(tmp_path):
    samples = [TemplateSample(tmp_path / f"{i}.dcm", 0, "A4C", "ED", f"patient-{i // 2}", "gold") for i in range(20)]
    assign_group_splits(samples, seed=69)
    assert {s.split for s in samples} <= {"train", "val", "test"}
    assert all(samples[i].split == samples[i + 1].split for i in range(0, 20, 2))
    shuffled = [replace(s, split="") for s in reversed(samples)]
    assign_group_splits(shuffled, seed=69)
    assert {s.group_id: s.split for s in samples} == {s.group_id: s.split for s in shuffled}
    with pytest.raises(ValueError, match="leakage"):
        assign_group_splits([replace(samples[0], split="train"), replace(samples[1], split="test")])
    with pytest.raises(ValueError, match="same instance"):
        assign_group_splits([replace(samples[0], group_id="one"), replace(samples[0], group_id="two")])


def test_partial_rv_gold_generic_annulus_is_tv_not_missing_or_ra(tmp_path: Path):
    source = tmp_path / "frame.dcm"
    source.touch()
    model = default_atlases()["A4C"]
    mesh = model.mean_ed + [110, 70]
    ids = list(model.structures["RV"])
    arc = mesh[ids]
    gold = {
        "study_id": "patient",
        "patient_group_id": "group",
        "instance_path": source.name,
        "chamber": "RV",
        "view": "A4C",
        "frames": [
            {
                "frame_index": 0,
                "phase": "ED",
                "points": arc.tolist(),
                "mitral_annulus": arc[[0, -1]].tolist(),
                "apex_landmark": mesh[model.landmarks["RV_apex"]].tolist(),
            }
        ],
    }
    path = tmp_path / "rv_local.json"
    path.write_text(json.dumps(gold))
    samples = load_gold_samples([path])
    assert samples[0].group_id == "group" and set(samples[0].landmarks) == {"TV_septal", "TV_lateral", "RV_apex"}
    assert len(RVGoldDataset(samples, default_atlases())) == 1
    target = training_target(samples[0], model, EchoNetCropTransform(200, 200, 0, 0, 200, 200), 64)
    assert target["node_mask"].sum() == len(ids)
    assert target["visibility_mask"].sum() == 3
    assert target["visible"].sum() == 3
    assert not target["visibility_mask"][[0, 1, 4, 5, 7, 8]].any()
    samples[0].source = "synthetic"
    assert (
        training_target(samples[0], model, EchoNetCropTransform(200, 200, 0, 0, 200, 200), 64)["visibility_mask"].sum()
        == 9
    )
    gold["chamber"] = "RA"
    path.write_text(json.dumps(gold))
    assert not load_gold_samples([path])[0].landmarks


def test_shared_gold_contradictions_and_duplicate_revisions_are_not_silent(tmp_path):
    model = default_atlases()["A4C"]
    sample = TemplateSample(
        tmp_path / "cine",
        0,
        "A4C",
        "ED",
        "patient",
        "gold",
        contours={c: model.mean_ed[list(model.structures[c])] + [100, 100] for c in ("LV", "RV")},
    )
    transform = EchoNetCropTransform(200, 200, 0, 0, 200, 200)
    assert training_target(sample, model, transform, 64)["node_mask"].any()
    sample.contours["RV"] += 20
    with pytest.raises(ValueError, match="shared"):
        training_target(sample, model, transform, 64)
    assert len(TemplateDataset([sample], default_atlases())) == 1
