"""Serialize calipers and contours to DICOM Graphic Annotation.

Uses DICOM tags:
- (0070,0001) GraphicAnnotationSequence
- (0070,0002) GraphicLayer
- (0070,0005) GraphicAnnotationUnits (PIXEL or NORMALIZED)
- (0070,0022) GraphicData
- (0070,0023) GraphicType
- (0070,0060) GraphicLayerSequence
"""

from __future__ import annotations

import logging

import pydicom
from pydicom.dataset import Dataset

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

logger = logging.getLogger(__name__)

# DICOM Graphic Annotation tags (verified from pydicom datadict)
TAG_GRAPHIC_ANNOTATION_SEQ = pydicom.tag.Tag(0x0070, 0x0001)  # GraphicAnnotationSequence
TAG_GRAPHIC_LAYER = pydicom.tag.Tag(0x0070, 0x0002)  # GraphicLayer
TAG_GRAPHIC_ANNOTATION_UNITS = pydicom.tag.Tag(0x0070, 0x0005)  # GraphicAnnotationUnits
TAG_GRAPHIC_LAYER_SEQ = pydicom.tag.Tag(0x0070, 0x0060)  # GraphicLayerSequence
TAG_GRAPHIC_DATA = pydicom.tag.Tag(0x0070, 0x0022)  # GraphicData
TAG_GRAPHIC_TYPE = pydicom.tag.Tag(0x0070, 0x0023)  # GraphicType


def _normalize_points(
    points: list[tuple[float, float]],
    rows: int,
    cols: int,
) -> list[float]:
    """Convert pixel coordinates to normalized [0,1] DICOM coordinates."""
    normalized: list[float] = []
    for x, y in points:
        norm_x = max(0.0, min(1.0, x / cols)) if cols > 0 else 0.0
        norm_y = max(0.0, min(1.0, y / rows)) if rows > 0 else 0.0
        normalized.extend([norm_x, norm_y])
    return normalized


def _make_graphic_object(
    graphic_type: str,
    graphic_data: list[float],
    layer_description: str = "",
) -> Dataset:
    """Create a single graphic object for GraphicLayerSequence."""
    obj = Dataset()
    obj.add_new(TAG_GRAPHIC_TYPE, "CS", graphic_type)
    obj.add_new(TAG_GRAPHIC_DATA, "FL", graphic_data)
    return obj


def annotate_dicom_with_calipers(
    ds: Dataset,
    calipers: list[LinearMeasurement],
) -> Dataset:
    """Add caliper annotations to DICOM dataset.

    Structure:
      (0070,0001) GraphicAnnotationSequence
        └─ (0070,0005) GraphicAnnotationUnits = NORMALIZED
        └─ (0070,0060) GraphicLayerSequence
           └─ (0070,0023) GraphicType = POLYLINE
              (0070,0022) GraphicData = [x1,y1,x2,y2]
    """
    if not calipers:
        return ds

    rows = int(getattr(ds, "Rows", 512))
    cols = int(getattr(ds, "Columns", 512))

    annotation_items: list[Dataset] = []

    for i, caliper in enumerate(calipers):
        if caliper.start is None or caliper.end is None:
            continue

        # Build graphic layer with one graphic object
        layer = Dataset()
        layer.add_new(TAG_GRAPHIC_LAYER, "LO", f"Caliper {caliper.label}")
        layer.add_new(TAG_GRAPHIC_ANNOTATION_UNITS, "CS", "NORMALIZED")

        graphic_obj = Dataset()
        graphic_obj.add_new(TAG_GRAPHIC_TYPE, "CS", "POLYLINE")
        points = [caliper.start, caliper.end]
        graphic_obj.add_new(TAG_GRAPHIC_DATA, "FL", _normalize_points(points, rows, cols))

        layer.add_new(TAG_GRAPHIC_LAYER_SEQ, "SQ", [graphic_obj])
        annotation_items.append(layer)

    if annotation_items:
        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", annotation_items)
        logger.debug("Added %d caliper annotations to DICOM", len(annotation_items))

    return ds


def annotate_dicom_with_contours(
    ds: Dataset,
    contours: list[Contour],
) -> Dataset:
    """Add contour annotations to DICOM dataset.

    Structure:
      (0070,0001) GraphicAnnotationSequence
        └─ (0070,0005) GraphicAnnotationUnits = NORMALIZED
        └─ (0070,0060) GraphicLayerSequence
           └─ (0070,0023) GraphicType = POLYLINE
              (0070,0022) GraphicData = [x1,y1,...,xn,yn]
    """
    if not contours:
        return ds

    rows = int(getattr(ds, "Rows", 512))
    cols = int(getattr(ds, "Columns", 512))

    annotation_items: list[Dataset] = []
    existing = list(getattr(ds, "GraphicAnnotationSequence", []))

    for i, contour in enumerate(contours):
        if not contour.points:
            continue

        layer = Dataset()
        label = contour.measurement_label or contour.chamber or f"Contour {i + 1}"
        layer.add_new(TAG_GRAPHIC_LAYER, "LO", label)
        layer.add_new(TAG_GRAPHIC_ANNOTATION_UNITS, "CS", "NORMALIZED")

        graphic_obj = Dataset()
        graphic_obj.add_new(TAG_GRAPHIC_TYPE, "CS", "POLYLINE")
        points = contour.closed_polygon_points()
        graphic_obj.add_new(TAG_GRAPHIC_DATA, "FL", _normalize_points(points, rows, cols))

        layer.add_new(TAG_GRAPHIC_LAYER_SEQ, "SQ", [graphic_obj])
        annotation_items.append(layer)

    if annotation_items:
        existing.extend(annotation_items)
        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", existing)
        logger.debug("Added %d contour annotations to DICOM", len(annotation_items))

    return ds


def annotate_dicom(
    ds: Dataset,
    calipers: list[LinearMeasurement] | None = None,
    contours: list[Contour] | None = None,
) -> Dataset:
    """Add all annotations to DICOM dataset."""
    if calipers:
        ds = annotate_dicom_with_calipers(ds, calipers)
    if contours:
        ds = annotate_dicom_with_contours(ds, contours)
    return ds


def read_annotations_from_dicom(ds: Dataset) -> tuple[list[LinearMeasurement], list[Contour]]:
    """Read calipers and contours from DICOM Graphic Annotation.

    Returns:
        Tuple of (calipers, contours) extracted from the dataset.
    """
    calipers: list[LinearMeasurement] = []
    contours: list[Contour] = []

    annotation_seq = getattr(ds, "GraphicAnnotationSequence", None)
    if not annotation_seq:
        return calipers, contours

    rows = int(getattr(ds, "Rows", 512))
    cols = int(getattr(ds, "Columns", 512))

    for item in annotation_seq:
        layer_name = str(getattr(item, "GraphicLayer", ""))
        layer_seq = getattr(item, "GraphicLayerSequence", None)
        if not layer_seq:
            continue

        for graphic_obj in layer_seq:
            graphic_type = str(getattr(graphic_obj, "GraphicType", ""))
            graphic_data = getattr(graphic_obj, "GraphicData", None)
            if graphic_type != "POLYLINE" or not graphic_data:
                continue

            # Denormalize coordinates from [0,1] back to pixels
            points: list[tuple[float, float]] = []
            data = list(graphic_data)
            for i in range(0, len(data) - 1, 2):
                x = data[i] * cols
                y = data[i + 1] * rows
                points.append((x, y))

            if len(points) == 2:
                # Caliper (line between two points)
                start, end = points
                pixel_length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
                calipers.append(
                    LinearMeasurement(
                        label=layer_name or "Measurement",
                        pixel_length=pixel_length,
                        millimeter_length=None,
                        start=start,
                        end=end,
                    )
                )
            elif len(points) > 2:
                # Contour (polygon)
                contours.append(
                    Contour(
                        phase="ED",
                        view="A4C",
                        chamber="LV",
                        points=points,
                        source="dicom",
                        measurement_label=layer_name,
                    )
                )

    return calipers, contours
