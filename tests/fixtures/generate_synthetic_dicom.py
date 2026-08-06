"""Generate minimal synthetic DICOM files for unit/integration tests (Tier 3)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate, encapsulate_extended
from pydicom.uid import (
    ExplicitVRLittleEndian,
    JPEG2000Lossless,
    JPEGBaseline8Bit,
    generate_uid,
)


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


def write_synthetic_rgb_dicom(
    path: Path,
    *,
    frame_count: int = 1,
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    series_description: str = "Synthetic RGB A4C",
    rows: int = 64,
    cols: int = 64,
) -> Path:
    """Write a color US DICOM file with interleaved RGB pixels."""
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

    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0
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
        frame = np.zeros((rows, cols, 3), dtype=np.uint8)
        frame[..., 0] = np.uint8(10 + frame_index)
        frame[..., 1] = np.uint8(20 + frame_index)
        frame[..., 2] = np.uint8(30 + frame_index)
        frame[0, 0] = np.array([255, 0, 0], dtype=np.uint8)
        if cols > 1:
            frame[0, 1] = np.array([0, 255, 0], dtype=np.uint8)
        if rows > 1:
            frame[1, 0] = np.array([0, 0, 255], dtype=np.uint8)
        frames.append(frame)

    stacked = np.stack(frames, axis=0)
    ds.PixelData = stacked.tobytes()
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


def write_synthetic_jpeg_multiframe_dicom(
    path: Path,
    *,
    frame_count: int = 10,
    rows: int = 32,
    cols: int = 32,
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    series_description: str = "Synthetic JPEG multiframe",
) -> Path:
    """Write a multiframe JPEG Baseline encapsulated DICOM with BOT."""
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = sop_uid or generate_uid()

    jpeg_frames: list[bytes] = []
    for frame_index in range(frame_count):
        frame = np.full((rows, cols), frame_index * 5 + 20, dtype=np.uint8)
        frame[0, 0] = frame_index * 5 + 20
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise RuntimeError(f"Failed to encode JPEG frame {frame_index}")
        jpeg_frames.append(encoded.tobytes())

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = JPEGBaseline8Bit

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
    ds.PixelData = encapsulate(jpeg_frames)
    ds["PixelData"].VR = "OB"
    ds.save_as(path, write_like_original=False)
    return path


def write_synthetic_jpeg2000_multiframe_dicom(
    path: Path,
    *,
    frame_count: int = 10,
    rows: int = 32,
    cols: int = 32,
    use_extended_offsets: bool = False,
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    series_description: str = "Synthetic JPEG2000 multiframe",
) -> Path:
    """Write a multiframe JPEG-2000 encapsulated DICOM with BOT or EOT."""
    import openjpeg

    path.parent.mkdir(parents=True, exist_ok=True)
    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = sop_uid or generate_uid()

    j2k_frames: list[bytes] = []
    for frame_index in range(frame_count):
        frame = np.full((rows, cols), min(frame_index * 5 + 20, 255), dtype=np.uint8)
        encoded = openjpeg.encode(frame)
        j2k_frames.append(encoded)

    if use_extended_offsets:
        pixel_data, eot, eot_lengths = encapsulate_extended(j2k_frames)
    else:
        pixel_data = encapsulate(j2k_frames)
        eot = eot_lengths = None

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = JPEG2000Lossless

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
    ds.PixelData = pixel_data
    if use_extended_offsets and eot is not None and eot_lengths is not None:
        ds.ExtendedOffsetTable = eot
        ds.ExtendedOffsetTableLengths = eot_lengths
    ds["PixelData"].VR = "OB"
    ds.save_as(path, write_like_original=False)
    return path


if __name__ == "__main__":
    out = Path(__file__).parent / "synthetic_sample.dcm"
    write_synthetic_dicom(out)
    print(f"Wrote {out}")
