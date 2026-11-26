"""Regression tests for evidence, cleaning and privacy boundaries."""

import logging
import warnings

import numpy as np
from scripts.echo_ssl_data import clean_raw_sector
from scripts.echo_ssl_training import motion_evidence, motion_landmark_ids

from echo_personal_tool.domain.services.echo_ssl_objectives import candidate_reject_reasons
from echo_personal_tool.domain.services.echo_template_contract import default_atlases
from tests.unit.test_echo_ssl_training import torch_runtime


def test_cleaning_suppresses_detached_burned_text_without_saving_pixels():
    image = np.zeros((96, 96), np.float32)
    image[20:85, 25:80] = 0.5
    image[5:10, 3:18] = 1.0
    cleaned = clean_raw_sector([image, image])
    assert np.count_nonzero(cleaned[0][:15]) == 0
    assert cleaned[0][50, 50] == 0.5 and image[6, 4] == 1.0
    assert not any(f.any() for f in clean_raw_sector([np.zeros_like(image)]))


def test_jitter_support_cannot_change_when_candidate_hides_nodes():
    atlas = default_atlases()["A4C"]
    baseline = np.repeat(atlas.mean_ed[None], 5, axis=0)
    warped = baseline[1:].copy()
    weights = np.ones(warped.shape[:2])
    support = np.zeros(baseline.shape[:2], bool)
    for chamber in ("LV", "LA", "RV"):
        support[:, list(atlas.structures[chamber])] = True
    landmarks = motion_landmark_ids(atlas, support)
    assert atlas.landmarks["LV_apex"] in landmarks and atlas.landmarks["RV_apex"] in landmarks
    assert atlas.landmarks["RA_apex"] not in landmarks
    support[:, atlas.landmarks["LV_apex"]] = False
    assert atlas.landmarks["LV_apex"] not in motion_landmark_ids(atlas, support)
    original = motion_evidence(baseline, baseline, warped, weights, atlas)
    assert original == {"LV": 0.0, "LA": 0.0, "RV": 0.0}
    candidate = baseline.copy()
    candidate[1:] += np.arange(1, 5)[:, None, None]
    evidence = motion_evidence(candidate, baseline, warped, weights, atlas)
    assert all(x > 1 for x in evidence.values())
    candidate[1:, list(atlas.structures["RV"])] = np.nan
    assert np.isinf(motion_evidence(candidate, baseline, warped, weights, atlas)["RV"])
    assert all(x is None for x in motion_evidence(baseline, baseline, warped, np.zeros_like(weights), atlas).values())


def test_even_small_gold_degradation_cannot_be_bought_by_jitter_improvement():
    motion = {"LA": 1.0, "RV": 1.0}
    better = {"LA": 0.1, "RV": 0.1}
    gold = {"LV_iou": 0.9, "LA_iou": 0.9, "RV_iou": 0.9, "frames": 2.0, "node_error_px": 1.0}
    assert "rv_iou_degraded" in candidate_reject_reasons(motion, better, gold, {**gold, "RV_iou": 0.8999})
    assert "gold_nodes_degraded" in candidate_reject_reasons(motion, better, gold, {**gold, "node_error_px": 1.0001})


def test_cycle_contrastive_pairs_train_student_not_teacher_and_skip_untrusted_phase():
    torch = torch_runtime()
    from scripts.echo_ssl_losses import cycle_prototype_loss

    from tests.unit.test_echo_ssl_objectives import field

    torch.manual_seed(692)
    student = torch.randn((24, 7), requires_grad=True)
    teacher = torch.randn((24, 7), requires_grad=True)
    loss = cycle_prototype_loss(student, teacher, field())
    assert loss.item() > 0
    loss.backward()
    assert student.grad.abs().sum() > 0 and teacher.grad is None
    student.grad.zero_()
    zero = cycle_prototype_loss(student, teacher, field(0.5))
    assert zero.item() == 0
    zero.backward()
    assert torch.count_nonzero(student.grad) == 0


def test_cli_diagnostics_never_print_dicom_exception_paths_or_tag_values(monkeypatch, capsys):
    from scripts import train_self_supervised_echo as cli

    previous = logging.root.manager.disable

    def invalid(_):
        warnings.warn("PRIVATE^IDENTITY", UserWarning, stacklevel=1)
        logging.getLogger("pydicom").critical("PatientID=private-id")
        raise ValueError("private-id: /patient/name/cine.dcm")

    monkeypatch.setattr(cli, "train", invalid)
    status = cli.main(["--manifest", "not-read.json", "--checkpoint", "not-read.pt", "--output", "not-created"])
    captured = capsys.readouterr()
    assert status == 2 and captured.out == ""
    assert captured.err == "Local SSL adaptation failed; check local inputs and configuration.\n"
    assert logging.root.manager.disable == previous
