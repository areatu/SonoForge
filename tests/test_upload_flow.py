#!/usr/bin/env python3
"""Test the full upload flow with a real DICOM file."""

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


def test_with_real_dicom():
    """Test annotation injection into a real DICOM file."""
    # Use a test DICOM file
    dcm_path = ".venv/lib/python3.11/site-packages/pydicom/data/test_files/CT_small.dcm"

    print(f"=== Loading DICOM: {dcm_path} ===")
    ds = pydicom.dcmread(dcm_path, force=True)
    print(f"  PatientName: {getattr(ds, 'PatientName', 'N/A')}")
    print(f"  Rows: {getattr(ds, 'Rows', 'N/A')}")
    print(f"  Columns: {getattr(ds, 'Columns', 'N/A')}")
    print(f"  Has GraphicAnnotationSequence: {hasattr(ds, 'GraphicAnnotationSequence')}")

    # Add calipers
    calipers = [
        LinearMeasurement(
            label="LVEDD", pixel_length=150.0, millimeter_length=45.0, start=(50.0, 100.0), end=(200.0, 100.0)
        ),
    ]
    contours = [
        Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(50, 50), (100, 75), (150, 100), (125, 150), (75, 125)],
            source="manual",
            measurement_label="LV",
        ),
    ]

    print("\n=== Injecting annotations ===")
    ds = annotate_dicom(ds, calipers=calipers, contours=contours)
    print(f"  GraphicAnnotationSequence: {hasattr(ds, 'GraphicAnnotationSequence')}")

    # Save to bytes
    print("\n=== Saving to bytes ===")
    buf = io.BytesIO()
    ds.save_as(buf, write_like_original=False)
    data = buf.getvalue()
    print(f"  Size: {len(data)} bytes")

    # Read back
    print("\n=== Reading back ===")
    ds2 = pydicom.dcmread(io.BytesIO(data), force=True)
    print(f"  GraphicAnnotationSequence: {hasattr(ds2, 'GraphicAnnotationSequence')}")

    calipers_out, contours_out = read_annotations_from_dicom(ds2)
    print(f"  Calipers: {len(calipers_out)}")
    print(f"  Contours: {len(contours_out)}")

    for c in calipers_out:
        print(f"    {c.label}: {c.start} → {c.end}")
    for c in contours_out:
        print(f"    {c.chamber}: {len(c.points)} points")

    assert len(calipers_out) == 1
    assert len(contours_out) == 1
    print("\n=== SUCCESS: Full DICOM annotation flow works! ===")
    return True


if __name__ == "__main__":
    try:
        success = test_with_real_dicom()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n=== FAILED: {e} ===")
        import traceback

        traceback.print_exc()
        sys.exit(1)
