"""Offline RV metrics retain failures and never fabricate FAC from missing phases."""

import json

import numpy as np
from scripts.generate_synthetic_echo_corpus import main as generate_main
from scripts.run_rv_auto_bench import estimated_sector_mask, evaluate_rv_gold

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.echo_template_contract import TemplatePrediction


def test_rv_bench_perfect_proposals_and_rejections_have_explicit_denominators(tmp_path):
    corpus = tmp_path / "corpus"
    assert (
        generate_main(
            [
                "--output",
                str(corpus),
                "--views",
                "A4C",
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
    gold_path = next((corpus / "gold").glob("rv_*.json"))
    original = gold_path.read_text()
    gold = json.loads(original)
    frames = {f["phase"]: f for f in gold["frames"]}

    class Engine:
        def __init__(self, reject=()):
            self.reject = reject

        def predict(self, frame, *, phase, **kwargs):
            if phase in self.reject:
                return TemplatePrediction("UNKNOWN", 0.0, reject_reason="view_unknown")
            record = frames[phase]
            contour = Contour(
                phase,
                chamber="RV",
                points=[tuple(p) for p in record["points"]],
                source="ai",
                review_pending=True,
                mitral_annulus=tuple(tuple(p) for p in record["tricuspid_annulus"]),
                frame_index=record["frame_index"],
            )
            return TemplatePrediction("A4C", 1.0, (contour,))

    perfect = evaluate_rv_gold([gold_path], Engine())
    assert perfect["frames"] == 2 and perfect["rejected"] == 0
    assert perfect["median_iou_all_frames"] == 1.0
    assert perfect["median_tv_error_mm_accepted"] == 0.0
    assert perfect["median_area_error_pct_accepted"] == 0.0
    assert perfect["fac_pairs_evaluable"] == perfect["fac_pairs_total"] == 1
    assert perfect["median_fac_error_pp"] == 0.0
    partial = evaluate_rv_gold([gold_path], Engine(reject=("ES",)))
    assert partial["rejected"] == 1 and partial["median_iou_all_frames"] == 0.5
    assert partial["fac_pairs_evaluable"] == 0 and partial["median_fac_error_pp"] is None
    assert gold_path.read_text() == original
    # Local filesystem identifiers are not copied into the output report.
    assert str(corpus) not in json.dumps(perfect)


def test_image_only_sector_estimator_is_not_ground_truth_or_dropout_clipping():
    frame = np.zeros((96, 96))
    yy, xx = np.mgrid[:96, :96]
    disk = ((yy - 48) ** 2 + (xx - 48) ** 2) < 32**2
    frame[disk] = 100
    frame[42:52, 45:80] = 0
    support = estimated_sector_mask(frame)
    assert support is not None and support[48, 60]
    assert not support[2, 2]
    assert estimated_sector_mask(np.zeros((32, 32))) is None
