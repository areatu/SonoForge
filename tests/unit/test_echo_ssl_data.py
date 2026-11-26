"""Local raw DICOM isolation, split leakage and bounded memory contracts."""

import json
from dataclasses import replace

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, UltrasoundMultiFrameImageStorage, generate_uid
from scripts.echo_ssl_data import check_gold_separation, load_raw_inventory, read_raw_clip
from scripts.echo_template_data import TemplateSample


def cine(path, *, patient="synthetic-patient", uid=None):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = UltrasoundMultiFrameImageStorage
    meta.MediaStorageSOPInstanceUID = uid or generate_uid()
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.PatientID, ds.PatientName = patient, "PRIVATE^IDENTITY"
    ds.Rows, ds.Columns, ds.NumberOfFrames, ds.FrameTime = 64, 64, 24, 40.0
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 8, 8, 7, 0
    data = np.random.default_rng(692).integers(20, 230, (24, 64, 64), dtype=np.uint8)
    ds.PixelData = data.tobytes()
    ds.save_as(path, enforce_file_format=True)
    return ds


def manifest(path, records):
    path.write_text(json.dumps({"schema_version": 1, "clips": records}))
    return path


def test_raw_cines_are_ram_only_and_test_split_pixels_never_needed_for_inventory(tmp_path, monkeypatch):
    path = tmp_path / "private-name.dcm"
    cine(path)
    source = manifest(
        tmp_path / "raw.json", [{"path": path.name, "patient_group_id": "curated", "split": "test", "view": "A4C"}]
    )
    clips = load_raw_inventory(manifest=source, dicom_dir=None)
    assert clips[0].split == "test" and "private" not in repr(clips[0]) and "curated" not in repr(clips[0])
    before = {p.name for p in tmp_path.iterdir()}
    gray, tensors, transforms, phase = read_raw_clip(clips[0], input_size=64, max_frames=12)
    assert gray.shape == (12, 64, 64) and tensors.shape == (12, 3, 64, 64)
    assert len(transforms) == phase.n_frames == 12
    assert phase.frame_time_ms == 40.0
    assert {p.name for p in tmp_path.iterdir()} == before
    np.testing.assert_allclose(tensors[0, 1, :, 0], np.linspace(-1, 1, 64), atol=1e-7)
    # Header inventory does not decode test pixels at all.
    monkeypatch.setattr(
        pydicom.dataset.Dataset,
        "pixel_array",
        property(lambda _: (_ for _ in ()).throw(AssertionError("decoded test pixels"))),
    )
    assert load_raw_inventory(manifest=source, dicom_dir=None)[0].split == "test"


def test_raw_identity_copies_and_patient_aliases_cannot_cross_splits(tmp_path):
    first, second = tmp_path / "first.dcm", tmp_path / "second.dcm"
    a = cine(first)
    cine(second)
    source = manifest(
        tmp_path / "raw.json",
        [
            {"path": first.name, "patient_group_id": "alias-one", "split": "train"},
            {"path": second.name, "patient_group_id": "alias-two", "split": "val"},
        ],
    )
    with pytest.raises(ValueError, match="identity leakage"):
        load_raw_inventory(manifest=source, dicom_dir=None)
    cine(second, patient="other-patient", uid=a.SOPInstanceUID)
    with pytest.raises(ValueError, match="duplicate raw"):
        load_raw_inventory(manifest=source, dicom_dir=None)


def test_raw_gold_separation_checks_actual_header_and_curated_groups(tmp_path):
    first, second = tmp_path / "first.dcm", tmp_path / "second.dcm"
    original = cine(first)
    source = manifest(tmp_path / "raw.json", [{"path": first.name, "patient_group_id": "curated", "split": "train"}])
    clips = load_raw_inventory(manifest=source, dicom_dir=None)
    cine(second, patient="other", uid=original.SOPInstanceUID)
    gold = TemplateSample(second, 0, "A4C", "ED", "alias", "gold", split="val")
    with pytest.raises(ValueError, match="instance leakage"):
        check_gold_separation(clips, [gold])
    cine(second)
    with pytest.raises(ValueError, match="patient identity"):
        check_gold_separation(clips, [replace(gold, group_id="alias")])
    check_gold_separation(clips, [replace(gold, split="train")])


def test_decoder_limits_and_no_silent_truncation_of_clip_inventory(tmp_path):
    source = tmp_path / "cine.dcm"
    ds = cine(source)
    raw = manifest(tmp_path / "raw.json", [{"path": source.name, "split": "train"}])
    clips = load_raw_inventory(manifest=raw, dicom_dir=None)
    with pytest.raises(ValueError, match="memory/format"):
        read_raw_clip(clips[0], input_size=64, max_decoded_mb=0.001)
    with pytest.raises(ValueError, match="configuration"):
        read_raw_clip(clips[0], input_size=64, max_frames=10000)
    ds.PhotometricInterpretation = "MONOCHROME1"
    ds.save_as(source, enforce_file_format=True)
    with pytest.raises(ValueError, match="format"):
        read_raw_clip(clips[0], input_size=64)
    cine(tmp_path / "other.dcm", patient="other")
    with pytest.raises(ValueError, match="too many"):
        load_raw_inventory(manifest=None, dicom_dir=tmp_path, max_clips=1)
