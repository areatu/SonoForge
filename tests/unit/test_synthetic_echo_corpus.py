"""Real synthetic DICOM round trip through existing corpus/gold consumers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pydicom
import pytest
from scripts import finetune_la_seg as la
from scripts import finetune_lv_seg as lv
from scripts.generate_synthetic_echo_corpus import main, synthetic_uid, validate_output
from scripts.validate_view_recognition_corpus import main as validate_main

from echo_personal_tool.domain.models.view_recognition import TTE_STANDARD_VIEWS, ViewRecognitionManifest
from echo_personal_tool.domain.services.gold_store import load_gold
from echo_personal_tool.domain.services.segmentation_preprocess import prepare_training_pair
from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("synthetic") / "corpus"
    assert main(["--output", str(root), "--size", "48", "--frames-per-cycle", "12", "--seed", "17"]) == 0
    return root


def test_full_corpus_passes_existing_validator_and_dicom_pixel_reader(corpus: Path) -> None:
    assert validate_main([str(corpus / "manifest.json"), "--check-dicom"]) == 0
    manifest = ViewRecognitionManifest.from_dict(json.loads((corpus / "manifest.json").read_text()))
    assert manifest.class_names == TTE_STANDARD_VIEWS
    assert {s.view for s in manifest.samples} == set(TTE_STANDARD_VIEWS) | {"UNKNOWN"}
    for sample in manifest.samples:
        ds = pydicom.dcmread(sample.source_path)
        assert ds.NumberOfFrames == 12 and ds.PatientName == "SYNTHETIC^PHANTOM"
        truth = np.load(corpus / "truth" / f"{sample.sample_id}.npz", allow_pickle=False)
        assert ds.pixel_array.shape == (12, 48, 48)
        frame = DicomReaderImpl().read_pixels(Path(sample.source_path), 0)
        np.testing.assert_array_equal(frame, ds.pixel_array[0])
        assert np.all(frame[~truth["sector_mask"]] == 0)
        assert truth["mask_LV"].dtype == bool
        assert np.isfinite(truth["contour_LV"]).all()
        assert truth["phases"][0] == 0
        assert "landmark_MV_septal" in truth or sample.view == "PSAX"


def test_la_lv_datasets_really_decode_generated_frames_and_masks(corpus: Path) -> None:
    la_samples = la.extract_la_samples(la.load_la_gold(corpus))
    lv_samples = lv.load_lv_samples(corpus / "no-lv-manifest.json", view="ALL", gold_dir=corpus / "gold")
    assert {s["view"] for s in la_samples} == {"A4C", "A2C"}
    assert len(lv_samples) == 14
    assert len(la.LaGoldDataset(la_samples, input_size=48)) == len(la_samples)
    assert len(lv.LVGoldDataset(lv_samples, input_size=48)) == len(lv_samples)
    for samples, resolver in ((la_samples, la._resolve_dicom_frame), (lv_samples, lv._resolve_frame)):
        for sample in samples:
            frame = resolver(sample["instance_path"], sample["frame_index"])
            assert frame is not None and frame.max() > 0  # No silent blank-frame fallback.
            mask = la.rasterize_polygon(sample["points"], frame.shape[:2])
            tensor, target = prepare_training_pair(frame, mask, target_size=48)
            assert tensor.shape == (3, 48, 48) and target.shape == (1, 48, 48)
            assert target.sum() > 0 and np.isfinite(tensor).all()


def test_rv_ra_gold_and_valve_landmarks_match_full_geometry(corpus: Path) -> None:
    for chamber in ("LV", "LA", "RV", "RA"):
        files = list((corpus / "gold").glob(f"{chamber.lower()}_*.json"))
        assert files
        for path in files:
            gold = load_gold(path)
            assert gold["synthetic"] and gold["phase_reference"] == "ventricular_cycle"
            assert len(gold["frames"]) == 2
            assert gold["view"] != "UNKNOWN"
            key = path.stem.removeprefix(chamber.lower() + "_")
            with np.load(corpus / "truth" / f"{key}.npz", allow_pickle=False) as truth:
                for frame in gold["frames"]:
                    idx = frame["frame_index"]
                    np.testing.assert_array_equal(frame["points"], truth[f"contour_{chamber}"][idx])
                    assert frame["cycle_fraction"] == pytest.approx(truth["phases"][idx])
                    assert frame["contour_closed"] == (gold["view"] == "PSAX")
                    if gold["view"] != "PSAX":
                        field = "mitral_annulus" if chamber in {"LV", "LA"} else "tricuspid_annulus"
                        prefix = "MV" if chamber in {"LV", "LA"} else "TV"
                        np.testing.assert_array_equal(frame[field][0], truth[f"landmark_{prefix}_septal"][idx])
    assert not list((corpus / "gold").glob("*unknown*"))


def test_repeated_generation_has_identical_dicom_and_truth(tmp_path: Path) -> None:
    outputs = [tmp_path / name for name in ("one", "two")]
    for output in outputs:
        assert main(["--output", str(output), "--views", "A2C", "--size", "48", "--frames-per-cycle", "12"]) == 0
    one = next((outputs[0] / "clips").glob("*.dcm"))
    two = next((outputs[1] / "clips").glob("*.dcm"))
    assert one.read_bytes() == two.read_bytes()
    assert (
        next((outputs[0] / "truth").glob("*.npz")).read_bytes()
        == next((outputs[1] / "truth").glob("*.npz")).read_bytes()
    )
    assert synthetic_uid("one") == synthetic_uid("one") != synthetic_uid("two")


@pytest.mark.parametrize("forbidden", ["repository", "git", "tracked", "existing"])
def test_output_must_be_new_and_external_or_ignored(tmp_path: Path, corpus: Path, forbidden: str) -> None:
    root = Path(__file__).resolve().parents[2]
    bad = {
        "repository": root,
        "git": root / ".git" / "phantoms",
        "tracked": root / "tracked-phantom-output",
        "existing": corpus,
    }[forbidden]
    try:
        validate_output(bad)
    except ValueError:
        pass  # Expected safety rejection, checked separately for each path class.
    else:
        import subprocess

        result = subprocess.run(
            ["git", "check-ignore", "--verbose", "--", bad.name + "/"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        pytest.fail(
            f"unsafe output accepted: {forbidden}; root={root}; resolved={bad.resolve()}; "
            f"git_exit={result.returncode}; git_rule={result.stdout!r}; git_error={result.stderr!r}"
        )
    assert validate_output(root / ".cache" / "phantom-output-new") == root / ".cache" / "phantom-output-new"
    assert main(["--output", str(corpus), "--size", "48"]) == 2
    bad_output = tmp_path / "bad"
    assert main(["--output", str(bad_output), "--size", "5"]) == 2
    assert not bad_output.exists()


def test_subject_split_is_grouped_and_disjoint_across_views(tmp_path: Path) -> None:
    output = tmp_path / "split-corpus"
    assert (
        main(
            [
                "--output",
                str(output),
                "--views",
                "A2C",
                "PSAX",
                "--subjects",
                "10",
                "--size",
                "48",
                "--frames-per-cycle",
                "12",
            ]
        )
        == 0
    )
    manifest = ViewRecognitionManifest.from_dict(json.loads((output / "manifest.json").read_text()))
    groups: dict[str, set[str]] = {}
    for sample in manifest.samples:
        study = str(pydicom.dcmread(sample.source_path, stop_before_pixels=True).StudyInstanceUID)
        groups.setdefault(study, set()).add(sample.split)
    assert len(groups) == 10 and all(len(splits) == 1 for splits in groups.values())
    assert {s.split for s in manifest.samples} == {"train", "val", "test"}


def test_cli_uses_bounded_local_atlas_artifact(tmp_path: Path) -> None:
    from dataclasses import replace

    from echo_personal_tool.domain.services.cardiac_atlas import build_cardiac_atlas

    atlas = replace(build_cardiac_atlas("A2C"), provenance="reviewed_local_test")
    artifact = tmp_path / "atlas.json"
    artifact.write_text(json.dumps(atlas.to_dict()))
    output = tmp_path / "local-model-corpus"
    assert (
        main(
            [
                "--output",
                str(output),
                "--atlas",
                str(artifact),
                "--views",
                "A2C",
                "--size",
                "48",
                "--frames-per-cycle",
                "12",
            ]
        )
        == 0
    )
    record = json.loads((output / "generation.json").read_text())["records"][0]
    assert record["atlas_provenance"] == "reviewed_local_test" and len(record["coefficients"]) == 4
    exported_atlas = (output / "atlases" / "A2C.json").read_bytes()
    assert record["atlas_sha256"] == hashlib.sha256(exported_atlas).hexdigest()
    assert json.loads(exported_atlas)["mean_ed"] == atlas.mean_ed.tolist()
    assert str(artifact) not in (output / "generation.json").read_text()
    assert main(["--output", str(tmp_path / "duplicate"), "--atlas", str(artifact), "--atlas", str(artifact)]) == 2
    assert not (tmp_path / "duplicate").exists()
    artifact.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    assert main(["--output", str(tmp_path / "oversize"), "--atlas", str(artifact)]) == 2
    assert not (tmp_path / "oversize").exists()
