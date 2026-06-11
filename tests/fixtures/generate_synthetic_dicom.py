"""Generate minimal synthetic DICOM files for unit/integration tests (Tier 3)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid


def write_synthetic_dicom(
    path: Path,
    *,
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    series_description: str = "Synthetic A4C",
    rows: int = 64,
    cols: int = 64,
) -> Path:
    """Write a single-frame grayscale US DICOM file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = sop_uid or generate_uid()

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds: FileDataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SOPClassUID = pydicom.uid.UltrasoundImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "US"
    ds.SeriesDescription = series_description
    ds.StudyDate = "20240601"
    ds.StudyTime = "120000"
    ds.PatientName = "Synthetic^Patient"
    ds.PatientID = "SYN001"

    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelSpacing = [0.3, 0.3]
    ds.NumberOfFrames = 1

    gradient = np.linspace(0, 255, cols, dtype=np.uint8)
    pixels = np.tile(gradient, (rows, 1))
    ds.PixelData = pixels.tobytes()

    ds.save_as(path, write_like_original=False)
    return path


def write_synthetic_multiframe_dicom(
    path: Path,
    *,
    frame_count: int = 10,
    rows: int = 64,
    cols: int = 64,
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    series_description: str = "Synthetic multiframe A4C",
) -> Path:
    """Write a multiframe grayscale US DICOM file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = sop_uid or generate_uid()

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds: FileDataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = pydicom.uid.UltrasoundImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "US"
    ds.SeriesDescription = series_description
    ds.StudyDate = "20240601"
    ds.StudyTime = "120000"
    ds.PatientName = "Synthetic^Patient"
    ds.PatientID = "SYN001"
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelSpacing = [0.3, 0.3]
    ds.NumberOfFrames = frame_count

    frames = []
    for frame_index in range(frame_count):
        gradient = np.linspace(0, 255, cols, dtype=np.uint8)
        frame = np.tile(gradient, (rows, 1))
        frame[0, 0] = frame_index  # unique marker per frame
        frames.append(frame)
    stacked = np.stack(frames, axis=0)
    ds.PixelData = stacked.tobytes()
    ds.save_as(path, write_like_original=False)
    return path


if __name__ == "__main__":
    out = Path(__file__).parent / "synthetic_sample.dcm"
    write_synthetic_dicom(out)
    print(f"Wrote {out}")
