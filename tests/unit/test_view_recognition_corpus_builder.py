"""Integration tests for the view-recognition corpus builder (issue #639, step 1).

Drives :func:`scripts.build_view_recognition_corpus.collect_samples` and the
full builder ``main`` path over synthetic DICOM files with real ``ProtocolName``
headers, covering: canonicalisation of vendor spellings, metadata capture, the
UNKNOWN fallback for undetermined views, annotations-JSON overrides, and the
end-to-end manifest write.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pydicom
import pytest

from echo_personal_tool.domain.models.view_recognition import KNOWN_VIEWS
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.build_view_recognition_corpus import (  # noqa: E402
    collect_samples,
)
from scripts.build_view_recognition_corpus import (
    main as build_main,
)
from scripts.validate_view_recognition_corpus import main as validate_main  # noqa: E402


def _make_dicom(path: Path, protocol_name: str, vendor: str = "TestVendor") -> Path:
    """Write a synthetic multiframe DICOM with a ProtocolName header."""
    write_synthetic_multiframe_dicom(path, frame_count=6, rows=16, cols=16)
    ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    ds.ProtocolName = protocol_name
    ds.Manufacturer = vendor
    ds.save_as(path, write_like_original=False)
    return path


@pytest.fixture()
def dicom_dir(tmp_path: Path) -> Path:
    root = tmp_path / "dicoms"
    root.mkdir()
    _make_dicom(root / "a4c.dcm", "A4C")
    _make_dicom(root / "ap4.dcm", "ap4")  # vendor alias for A4C
    _make_dicom(root / "plax.dcm", "PLAX")
    _make_dicom(root / "weird.dcm", "NOT_A_VIEW")
    return root


def test_collect_samples_canonicalizes_protocol_names(dicom_dir: Path) -> None:
    samples, diagnostics = collect_samples(dicom_dir)
    by_stem = {Path(s.source_path).stem: s for s in samples}
    assert by_stem["a4c"].view == "A4C"
    assert by_stem["ap4"].view == "A4C"  # alias canonicalisation
    assert by_stem["plax"].view == "PLAX"
    assert by_stem["weird"].view == "UNKNOWN"
    assert any("weird.dcm" in d for d in diagnostics)


def test_collect_samples_captures_metadata(dicom_dir: Path) -> None:
    samples, _ = collect_samples(dicom_dir)
    plax = next(s for s in samples if Path(s.source_path).stem == "plax")
    assert plax.metadata is not None
    assert plax.metadata.protocol_name == "PLAX"
    assert plax.metadata.vendor == "TestVendor"


def test_collect_samples_uses_sop_uid_as_sample_id(dicom_dir: Path) -> None:
    samples, _ = collect_samples(dicom_dir)
    a4c = next(s for s in samples if Path(s.source_path).stem == "a4c")
    assert a4c.sample_id  # SOP Instance UID is long and unique
    assert len({s.sample_id for s in samples}) == len(samples)


def test_collect_samples_skips_unreadable_files(tmp_path: Path) -> None:
    root = tmp_path / "dicoms"
    root.mkdir()
    (root / "broken.dcm").write_bytes(b"not a dicom file")
    samples, diagnostics = collect_samples(root)
    assert samples == []
    assert any("broken.dcm" in d for d in diagnostics)


def test_annotations_override_protocol_name(tmp_path: Path) -> None:
    root = tmp_path / "dicoms"
    root.mkdir()
    target = _make_dicom(root / "target.dcm", "WEIRD")
    ds = pydicom.dcmread(target, stop_before_pixels=True, force=True)
    annotations = tmp_path / "annotations.json"
    annotations.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "sop_instance_uid": str(ds.SOPInstanceUID),
                        "instance_path": str(target),
                        "frames": [{"view": "SAX"}, {"view": "SAX"}, {"view": "A4C"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    samples, diagnostics = collect_samples(root, annotations_path=annotations)
    assert len(samples) == 1
    # Dominant view from annotations wins over the unusable ProtocolName.
    assert samples[0].view == "SAX"
    assert diagnostics == []


def test_annotations_record_level_view_fallback(tmp_path: Path) -> None:
    root = tmp_path / "dicoms"
    root.mkdir()
    target = _make_dicom(root / "target.dcm", "WEIRD")
    ds = pydicom.dcmread(target, stop_before_pixels=True, force=True)
    annotations = tmp_path / "annotations.json"
    annotations.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "sop_instance_uid": str(ds.SOPInstanceUID),
                        "instance_path": str(target),
                        "view": "a4c",
                        "frames": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    samples, diagnostics = collect_samples(root, annotations_path=annotations)
    assert len(samples) == 1
    # Clip-level view is canonicalised when the record has no frame labels.
    assert samples[0].view == "A4C"
    assert diagnostics == []


def test_builder_main_writes_valid_manifest(dicom_dir: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "manifest.json"
    exit_code = build_main(["--dicom-dir", str(dicom_dir), "--output", str(out), "--val-ratio", "0.25", "--seed", "1"])
    assert exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["class_names"] == list(KNOWN_VIEWS)
    samples = data["samples"]
    assert len(samples) == 4
    assert all(s["split"] in ("train", "val") for s in samples)
    assert {s["view"] for s in samples} == {"A4C", "PLAX", "UNKNOWN"}
    assert "manifest written" in capsys.readouterr().out


def test_builder_main_deterministic(dicom_dir: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    build_main(["--dicom-dir", str(dicom_dir), "--output", str(out_a), "--seed", "5"])
    build_main(["--dicom-dir", str(dicom_dir), "--output", str(out_b), "--seed", "5"])
    assert json.loads(out_a.read_text(encoding="utf-8")) == json.loads(out_b.read_text(encoding="utf-8"))


def test_builder_main_rejects_missing_dir(tmp_path: Path) -> None:
    exit_code = build_main(["--dicom-dir", str(tmp_path / "nope"), "--output", str(tmp_path / "m.json")])
    assert exit_code == 2


def test_builder_main_rejects_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    exit_code = build_main(["--dicom-dir", str(empty), "--output", str(tmp_path / "m.json")])
    assert exit_code == 2


# ── validator script ────────────────────────────────────────────────


def test_validator_accepts_valid_manifest(dicom_dir: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "manifest.json"
    build_main(["--dicom-dir", str(dicom_dir), "--output", str(out), "--seed", "3"])
    exit_code = validate_main([str(out), "--check-dicom"])
    assert exit_code == 0
    assert "corpus valid" in capsys.readouterr().out


def test_validator_reports_missing_source(tmp_path: Path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "class_names": list(KNOWN_VIEWS),
                "samples": [
                    {"sample_id": "s1", "source_path": str(tmp_path / "gone.dcm"), "view": "A4C", "split": "train"}
                ],
            }
        ),
        encoding="utf-8",
    )
    exit_code = validate_main([str(manifest), "--check-dicom"])
    assert exit_code == 1
    assert "source file missing" in capsys.readouterr().err


def test_validator_rejects_empty_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "empty.json"
    manifest.write_text(
        json.dumps({"schema_version": 2, "class_names": list(KNOWN_VIEWS), "samples": []}),
        encoding="utf-8",
    )
    # Loads fine but has no training samples — a corpus-level failure, not a load error.
    assert validate_main([str(manifest)]) == 1


def test_builder_auto_promotes_extended_classes(tmp_path: Path) -> None:
    from echo_personal_tool.domain.models.view_recognition import EXTENDED_KNOWN_VIEWS

    root = tmp_path / "dicoms"
    root.mkdir()
    _make_dicom(root / "rv.dcm", "RV-A4C")
    _make_dicom(root / "sc.dcm", "Subxiphoid")
    output = tmp_path / "manifest.json"
    assert build_main(["--dicom-dir", str(root), "--output", str(output)]) == 0
    manifest = json.loads(output.read_text())
    assert manifest["class_names"] == list(EXTENDED_KNOWN_VIEWS)
    assert {s["view"] for s in manifest["samples"]} == {"RV_A4C", "SUBCOSTAL"}
