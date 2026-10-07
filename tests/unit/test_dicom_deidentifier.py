"""Tests for infrastructure/dicom_deidentifier.py (design doc §3, §4, §8).

The fixtures are synthetic Samsung-shaped cines: a dark calibration bar over a
brighter "sector", a sequence of ultrasound regions whose top panel starts at
row 100, and the identifier set the corpus actually carries.  Nothing here needs
Qt or a network — the export must work on a file, not on a running dialog.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from echo_personal_tool.domain.services.phi_verification import verify_bytes
from echo_personal_tool.infrastructure.dicom_deidentifier import (
    DeidentificationOptions,
    clean_tags,
    deidentify_file,
    is_already_clean,
    mask_pixel_data,
    mask_plan_for_dataset,
    pseudonym_id,
)
from echo_personal_tool.infrastructure.phi_mask_profiles import (
    PhiMaskContext,
    clear_phi_mask_context_cache,
)
from echo_personal_tool.infrastructure.vendor_profiles.base import Vendor

HEIGHT = 884
WIDTH = 1180
FRAMES = 3
PANEL_TOP = 100
BAR_LEVEL = 25
SECTOR_LEVEL = 95
GLYPH_LEVEL = 245

#: The profile table is keyed by the enum, so hand-built contexts must use it;
#: ``phi_mask_context`` returns this same type for a real file.
SAMSUNG = PhiMaskContext(vendor=Vendor.SAMSUNG, panel_top=PANEL_TOP, burned_in="YES", has_regions=True)

pytestmark = pytest.mark.usefixtures("_clear_profile_cache")


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    """The profile cache is keyed by path: a fresh tmp_path must not see an old one."""
    clear_phi_mask_context_cache()
    yield
    clear_phi_mask_context_cache()


def _frames(count: int = FRAMES) -> np.ndarray:
    """A cine with a dark top bar, bright glyphs on it and a brighter sector."""
    frames = np.full((count, HEIGHT, WIDTH), BAR_LEVEL, dtype=np.uint8)
    frames[:, PANEL_TOP:, :] = SECTOR_LEVEL
    for index in range(count):
        for column in range(60, 600, 24):
            frames[index, 5:20, column : column + 14] = GLYPH_LEVEL
    return frames


def _dataset(
    path: Path | None = None,
    *,
    frames: np.ndarray | None = None,
    region_top: int | None = PANEL_TOP,
    manufacturer: str = "SAMSUNG",
    burned_in: str = "YES",
) -> FileDataset:
    """Build an uncompressed Samsung-like instance, optionally saved to ``path``."""
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    meta.MediaStorageSOPInstanceUID = "1.2.826.0.1.3680043.8.498.1"
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path) if path is not None else None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.Manufacturer = manufacturer
    ds.BurnedInAnnotation = burned_in
    ds.PatientName = "ZHELNOVA^OLGA"
    ds.PatientID = "27-11-2025-0003"
    ds.OtherPatientIDs = "27-11-2025-0003"
    ds.AccessionNumber = "ACC-99-77"
    ds.StudyID = "27112025"
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = "1.2.826.0.1.3680043.8.498.2"
    ds.SeriesInstanceUID = "1.2.826.0.1.3680043.8.498.3"
    ds.Modality = "US"
    ds.PatientSize = "1.68"
    ds.PatientWeight = "72"
    ds.Rows, ds.Columns, ds.SamplesPerPixel = HEIGHT, WIDTH, 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    array = _frames() if frames is None else frames
    ds.NumberOfFrames = int(array.shape[0])
    ds.PixelData = array.tobytes()
    if region_top is not None:
        region = Dataset()
        region.RegionLocationMinX0 = 0
        region.RegionLocationMinY0 = region_top
        region.RegionLocationMaxX1 = WIDTH
        region.RegionLocationMaxY1 = HEIGHT
        region.RegionSpatialFormat = 1
        region.RegionDataType = 1
        ds.SequenceOfUltrasoundRegions = [region]
    if path is not None:
        ds.save_as(str(path), enforce_file_format=False)
    return ds


# ── pure helpers ──────────────────────────────────────────────────────


def test_already_cleaned_markers_are_recognised():
    assert is_already_clean("?????")
    assert is_already_clean("****")
    assert is_already_clean("")
    assert is_already_clean(None)
    assert not is_already_clean("ZHELNOVA^OLGA")


def test_pseudonym_is_stable_and_carries_no_identifier():
    first = pseudonym_id("27-11-2025-0003", "ANON")
    assert first == pseudonym_id("27-11-2025-0003", "ANON")
    assert first != pseudonym_id("27-11-2025-0004", "ANON")
    assert first.startswith("ANON-") and "27-11" not in first


# ── tags ──────────────────────────────────────────────────────────────


def test_clean_tags_replaces_patient_identity():
    ds = _dataset()
    cleanup = clean_tags(ds, DeidentificationOptions())

    assert str(ds.PatientName) == "ANON"
    assert str(ds.PatientID) == pseudonym_id("27-11-2025-0003", "ANON")
    assert "OtherPatientIDs" not in ds
    assert set(cleanup.changed) >= {"PatientName", "PatientID", "OtherPatientIDs"}


def test_quasi_identifiers_stay_unless_asked_for():
    ds = _dataset()
    clean_tags(ds, DeidentificationOptions())
    assert str(ds.AccessionNumber) == "ACC-99-77"
    assert str(ds.StudyID) == "27112025"

    ds = _dataset()
    clean_tags(ds, DeidentificationOptions(clean_quasi_identifiers=True))
    assert str(ds.AccessionNumber) == ""
    assert str(ds.StudyID) == ""


def test_an_already_clean_name_is_left_alone():
    ds = _dataset(manufacturer="GE MEDICAL SYSTEMS")
    ds.PatientName = "?????"
    cleanup = clean_tags(ds, DeidentificationOptions())
    assert str(ds.PatientName) == "?????"
    assert "PatientName" in cleanup.skipped_already_clean


def test_measured_geometry_and_uids_survive():
    ds = _dataset()
    clean_tags(ds, DeidentificationOptions())
    assert ds.SequenceOfUltrasoundRegions[0].RegionLocationMinY0 == PANEL_TOP
    assert str(ds.SOPInstanceUID) == "1.2.826.0.1.3680043.8.498.1"
    assert str(ds.PatientWeight) == "72" and str(ds.PatientSize) == "1.68"


# ── pixels ────────────────────────────────────────────────────────────


def test_mask_plan_is_clamped_to_the_first_panel_row():
    ds = _dataset()
    plan = mask_plan_for_dataset(ds, SAMSUNG)
    tops = [rect for rect in plan.rects if rect.y0 == 0 and not rect.is_empty]
    assert tops, "a Samsung header has a top band"
    assert max(rect.y1 for rect in tops) == PANEL_TOP  # never the sector


def test_variant_a_leaves_the_burned_in_pixels_in_place():
    ds = _dataset()
    outcome = mask_pixel_data(
        ds,
        DeidentificationOptions(mask_pixels=False),
        context=SAMSUNG,
    )
    assert not outcome.applied and outcome.reason == "disabled"
    assert int(np.frombuffer(ds.PixelData, dtype=np.uint8).reshape(-1)[1000]) == BAR_LEVEL


def test_variant_b_fills_the_header_band_on_every_frame():
    ds = _dataset()
    outcome = mask_pixel_data(
        ds,
        DeidentificationOptions(mask_pixels=True),
        context=SAMSUNG,
    )
    assert outcome.applied and outcome.band == (0, PANEL_TOP)

    pixels = ds.pixel_array
    assert pixels.shape == (FRAMES, HEIGHT, WIDTH)
    band = pixels[:, :PANEL_TOP, :]
    assert band.min() == band.max() == BAR_LEVEL  # the glyphs are gone, the bar is kept
    assert pixels[:, PANEL_TOP:, :].max() == SECTOR_LEVEL  # the panel is untouched
    for index in range(1, FRAMES):
        assert np.array_equal(pixels[index], pixels[0])


def test_burned_in_annotation_no_disables_masking():
    ds = _dataset(burned_in="NO")
    outcome = mask_pixel_data(
        ds,
        DeidentificationOptions(mask_pixels=True),
        context=PhiMaskContext(vendor="SAMSUNG", panel_top=PANEL_TOP, burned_in="NO"),
    )
    assert not outcome.applied and outcome.reason == "burned-in-annotation-no"


def test_pixel_verification_catches_a_surviving_glyph_and_passes_on_a_clean_band():
    ds = _dataset()
    outcome = mask_pixel_data(
        ds,
        DeidentificationOptions(mask_pixels=True, verify_pixels=True),
        context=SAMSUNG,
    )
    assert outcome.verification is not None and outcome.verification.ok


# ── whole file ────────────────────────────────────────────────────────


def test_deidentify_file_exports_a_clean_instance(tmp_path: Path):
    source = tmp_path / "ZHELNOVA_OLGA_27112025.dcm"
    destination = tmp_path / "Instance" / "1" / "abcd1.dcm"
    _dataset(source)

    result = deidentify_file(source, destination, DeidentificationOptions(mask_pixels=True, verify_pixels=True))

    assert destination.is_file()
    assert result.verified, result.report_lines()
    assert result.pixels.band == (0, PANEL_TOP)

    exported = pydicom.dcmread(str(destination))
    assert str(exported.PatientName) == "ANON"
    assert str(exported.PatientID) == pseudonym_id("27-11-2025-0003", "ANON")
    assert "OtherPatientIDs" not in exported
    assert str(exported.AccessionNumber) == "ACC-99-77"  # quasi-identifiers off by default
    assert str(exported.SOPInstanceUID) == "1.2.826.0.1.3680043.8.498.1"
    assert exported.NumberOfFrames == FRAMES

    pixels = exported.pixel_array
    assert pixels[:, :PANEL_TOP, :].min() == pixels[:, :PANEL_TOP, :].max() == BAR_LEVEL
    assert pixels[:, PANEL_TOP:, :].max() == SECTOR_LEVEL


def test_exported_bytes_carry_no_identifier(tmp_path: Path):
    source = tmp_path / "ZHELNOVA_OLGA_27112025.dcm"
    destination = tmp_path / "out" / "abcd1.dcm"
    _dataset(source)
    deidentify_file(source, destination, DeidentificationOptions(mask_pixels=True))

    payload = destination.read_bytes()
    for leaked in (b"ZHELNOVA", b"27-11-2025-0003", b"ZHELNOVA_OLGA"):
        assert leaked not in payload


def test_bytes_check_can_be_run_standalone(tmp_path: Path):
    """The verifier is usable on its own bytes, not only through the export."""
    destination = tmp_path / "out" / "abcd1.dcm"
    _dataset(tmp_path / "raw.dcm")
    result = deidentify_file(tmp_path / "raw.dcm", destination, DeidentificationOptions())
    assert result.bytes_check is not None and result.bytes_check.ok

    payload = destination.read_bytes()
    assert "PatientName" in result.bytes_check.checked_fields
    assert verify_bytes({"PatientName": "ZHELNOVA^OLGA"}, payload).ok
    assert not verify_bytes({"PatientName": "ANON"}, payload).ok  # sanity: the search works


def test_a_missing_file_raises_so_the_worker_can_report_it(tmp_path: Path):
    """Per-file failures are raised, not swallowed: the worker counts them and
    the rest of the study still exports (``DicomDeidentifyWorker``)."""
    with pytest.raises(FileNotFoundError):
        deidentify_file(tmp_path / "gone.dcm", tmp_path / "out" / "x.dcm", DeidentificationOptions())
