#!/usr/bin/env python3
"""Test the full annotation chain: write → serialize → read."""

import io
import sys

sys.path.insert(0, "src")

import pydicom

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
    annotate_dicom,
    read_annotations_from_dicom,
)


def test_annotation_roundtrip():
    """Test that annotations survive write → read cycle."""
    ds = pydicom.Dataset()
    ds.PatientName = "TestPatient"
    ds.Rows = 512
    ds.Columns = 512
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 1
    ds.file_meta = pydicom.Dataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.5"
    ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"

    calipers = [
        LinearMeasurement(
            label="LVEDD", pixel_length=200.0, millimeter_length=52.3, start=(100.0, 200.0), end=(300.0, 200.0)
        ),
        LinearMeasurement(
            label="IVSd", pixel_length=100.0, millimeter_length=8.5, start=(150.0, 150.0), end=(250.0, 150.0)
        ),
    ]
    contours = [
        Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(100, 100), (200, 150), (300, 200), (250, 300), (150, 250)],
            source="manual",
            measurement_label="LV Contour",
        ),
    ]

    ds = annotate_dicom(ds, calipers=calipers, contours=contours)
    buf = io.BytesIO()
    ds.save_as(buf, write_like_original=False)
    data = buf.getvalue()

    ds2 = pydicom.dcmread(io.BytesIO(data), force=True)
    read_calipers, read_contours = read_annotations_from_dicom(ds2)

    print(f"Calipers: {len(read_calipers)}, Contours: {len(read_contours)}")
    for c in read_calipers:
        print(f"  {c.label}: {c.start} → {c.end}")
    for c in read_contours:
        print(f"  {c.chamber}: {len(c.points)} points, label={c.measurement_label}")

    assert len(read_calipers) == 2
    assert len(read_contours) == 1
    assert read_calipers[0].start == (100.0, 200.0)
    assert read_calipers[0].end == (300.0, 200.0)
    assert read_contours[0].chamber == "LV"
    assert len(read_contours[0].points) == 5

    print("\n=== SUCCESS: Annotation roundtrip works! ===")
    return True


if __name__ == "__main__":
    try:
        success = test_annotation_roundtrip()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n=== FAILED: {e} ===")
        import traceback

        traceback.print_exc()
        sys.exit(1)
