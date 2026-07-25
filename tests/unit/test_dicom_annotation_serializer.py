"""Tests for dicom_annotation_serializer calipers and contours."""

from __future__ import annotations

from pydicom.dataset import Dataset

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
    annotate_dicom,
    annotate_dicom_with_calipers,
    annotate_dicom_with_contours,
    read_annotations_from_dicom,
)


def _make_ds(rows: int = 512, cols: int = 512) -> Dataset:
    ds = Dataset()
    ds.Rows = rows
    ds.Columns = cols
    return ds


class TestNormalizePoints:
    def test_basic_normalization(self) -> None:
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            _normalize_points,
        )

        result = _normalize_points([(256, 256)], 512, 512)
        assert result == [0.5, 0.5]

    def test_clamps_to_zero_one(self) -> None:
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            _normalize_points,
        )

        result = _normalize_points([(-10, 1000), (600, -50)], 512, 512)
        assert result[0] == 0.0  # clamped from negative
        assert result[1] == 1.0  # clamped > 1
        assert result[2] == 1.0
        assert result[3] == 0.0

    def test_zero_dimensions(self) -> None:
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            _normalize_points,
        )

        result = _normalize_points([(10, 20)], 0, 0)
        assert result == [0.0, 0.0]

    def test_multiple_points(self) -> None:
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            _normalize_points,
        )

        result = _normalize_points([(0, 0), (100, 200)], 400, 100)
        assert result == [0.0, 0.0, 1.0, 0.5]


class TestMakeGraphicObject:
    def test_creates_dataset(self) -> None:
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            _make_graphic_object,
        )

        obj = _make_graphic_object("POLYLINE", [0.1, 0.2, 0.3, 0.4])
        assert obj.GraphicType == "POLYLINE"
        assert list(obj.GraphicData) == [0.1, 0.2, 0.3, 0.4]


class TestAnnotateDicomWithCalipers:
    def test_empty_calipers_returns_dataset_unchanged(self) -> None:
        ds = _make_ds()
        result = annotate_dicom_with_calipers(ds, [])
        assert "GraphicAnnotationSequence" not in result

    def test_single_caliper(self) -> None:
        ds = _make_ds(512, 512)
        caliper = LinearMeasurement(
            label="IVSd",
            pixel_length=100.0,
            millimeter_length=10.0,
            start=(100.0, 100.0),
            end=(200.0, 200.0),
        )
        result = annotate_dicom_with_calipers(ds, [caliper])
        seq = result.GraphicAnnotationSequence
        assert len(seq) == 1
        layer = seq[0]
        assert layer.GraphicLayer == "Caliper IVSd"
        assert layer.GraphicAnnotationUnits == "NORMALIZED"
        layer_seq = layer.GraphicLayerSequence
        assert len(layer_seq) == 1
        assert layer_seq[0].GraphicType == "POLYLINE"

    def test_caliper_with_none_start_end_skipped(self) -> None:
        ds = _make_ds()
        caliper_no_start = LinearMeasurement(
            label="bad",
            pixel_length=10.0,
            millimeter_length=None,
            start=None,
            end=(10.0, 10.0),
        )
        caliper_no_end = LinearMeasurement(
            label="bad2",
            pixel_length=10.0,
            millimeter_length=None,
            start=(10.0, 10.0),
            end=None,
        )
        result = annotate_dicom_with_calipers(ds, [caliper_no_start, caliper_no_end])
        assert "GraphicAnnotationSequence" not in result

    def test_multiple_calipers(self) -> None:
        ds = _make_ds()
        calipers = [
            LinearMeasurement("A", 10.0, 1.0, start=(0, 0), end=(10, 10)),
            LinearMeasurement("B", 20.0, 2.0, start=(20, 20), end=(30, 30)),
        ]
        result = annotate_dicom_with_calipers(ds, calipers)
        assert len(result.GraphicAnnotationSequence) == 2

    def test_default_rows_columns(self) -> None:
        """If ds has no Rows/Columns, defaults to 512."""
        ds = Dataset()
        caliper = LinearMeasurement(
            "test", 100.0, 5.0, start=(256, 256), end=(256, 256)
        )
        result = annotate_dicom_with_calipers(ds, [caliper])
        assert "GraphicAnnotationSequence" in result


class TestAnnotateDicomWithContours:
    def test_empty_contours(self) -> None:
        ds = _make_ds()
        result = annotate_dicom_with_contours(ds, [])
        assert "GraphicAnnotationSequence" not in result

    def test_single_contour(self) -> None:
        ds = _make_ds(512, 512)
        contour = Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(100, 100), (200, 100), (200, 200)],
            source="manual",
            measurement_label="LV cavity",
        )
        result = annotate_dicom_with_contours(ds, [contour])
        seq = result.GraphicAnnotationSequence
        assert len(seq) == 1
        assert seq[0].GraphicLayer == "LV cavity"
        assert seq[0].GraphicAnnotationUnits == "NORMALIZED"

    def test_contour_uses_chamber_as_fallback_label(self) -> None:
        ds = _make_ds()
        contour = Contour(
            phase="ED",
            view="A4C",
            chamber="RV",
            points=[(10, 10), (20, 20), (30, 10)],
        )
        result = annotate_dicom_with_contours(ds, [contour])
        assert result.GraphicAnnotationSequence[0].GraphicLayer == "RV"

    def test_contour_uses_index_fallback_label(self) -> None:
        ds = _make_ds()
        contour = Contour(
            phase="ED",
            view="A4C",
            chamber="",
            points=[(10, 10), (20, 20), (30, 10)],
        )
        result = annotate_dicom_with_contours(ds, [contour])
        assert result.GraphicAnnotationSequence[0].GraphicLayer == "Contour 1"

    def test_contour_empty_points_skipped(self) -> None:
        ds = _make_ds()
        contour = Contour(phase="ED", view="A4C", chamber="LV", points=[])
        result = annotate_dicom_with_contours(ds, [contour])
        assert "GraphicAnnotationSequence" not in result

    def test_appends_to_existing_annotations(self) -> None:
        ds = _make_ds()
        # Pre-add an annotation
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            TAG_GRAPHIC_ANNOTATION_SEQ,
            TAG_GRAPHIC_LAYER,
        )

        existing = Dataset()
        existing.add_new(TAG_GRAPHIC_LAYER, "LO", "Existing")
        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", [existing])

        contour = Contour(
            phase="ED", points=[(10, 10), (20, 20), (30, 10)]
        )
        result = annotate_dicom_with_contours(ds, [contour])
        assert len(result.GraphicAnnotationSequence) == 2

    def test_contour_with_measurement_label(self) -> None:
        ds = _make_ds()
        contour = Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(10, 10), (20, 20), (30, 10)],
            measurement_label="My Label",
        )
        result = annotate_dicom_with_contours(ds, [contour])
        assert result.GraphicAnnotationSequence[0].GraphicLayer == "My Label"


class TestAnnotateDicom:
    def test_both_calipers_and_contours(self) -> None:
        ds = _make_ds()
        caliper = LinearMeasurement(
            "test", 10.0, 1.0, start=(0, 0), end=(10, 10)
        )
        contour = Contour(
            phase="ED", points=[(10, 10), (20, 20), (30, 10)]
        )
        result = annotate_dicom(ds, calipers=[caliper], contours=[contour])
        assert "GraphicAnnotationSequence" in result

    def test_no_calipers_no_contours(self) -> None:
        ds = _make_ds()
        result = annotate_dicom(ds)
        assert "GraphicAnnotationSequence" not in result

    def test_only_calipers(self) -> None:
        ds = _make_ds()
        caliper = LinearMeasurement(
            "test", 10.0, 1.0, start=(0, 0), end=(10, 10)
        )
        result = annotate_dicom(ds, calipers=[caliper])
        assert "GraphicAnnotationSequence" in result

    def test_only_contours(self) -> None:
        ds = _make_ds()
        contour = Contour(
            phase="ED", points=[(10, 10), (20, 20), (30, 10)]
        )
        result = annotate_dicom(ds, contours=[contour])
        assert "GraphicAnnotationSequence" in result


class TestReadAnnotationsFromDicom:
    def test_no_annotations(self) -> None:
        ds = _make_ds()
        calipers, contours = read_annotations_from_dicom(ds)
        assert calipers == []
        assert contours == []

    def test_read_calipers(self) -> None:
        ds = _make_ds(512, 512)
        # Build annotation with a 2-point polyline (caliper)
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            TAG_GRAPHIC_ANNOTATION_SEQ,
            TAG_GRAPHIC_ANNOTATION_UNITS,
            TAG_GRAPHIC_DATA,
            TAG_GRAPHIC_LAYER,
            TAG_GRAPHIC_LAYER_SEQ,
            TAG_GRAPHIC_TYPE,
        )

        graphic_obj = Dataset()
        graphic_obj.add_new(TAG_GRAPHIC_TYPE, "CS", "POLYLINE")
        # Normalized: (0.5, 0.5) → pixel (256, 256)
        graphic_obj.add_new(TAG_GRAPHIC_DATA, "FL", [0.5, 0.5, 1.0, 1.0])

        layer = Dataset()
        layer.add_new(TAG_GRAPHIC_LAYER, "LO", "TestCaliper")
        layer.add_new(TAG_GRAPHIC_ANNOTATION_UNITS, "CS", "NORMALIZED")
        layer.add_new(TAG_GRAPHIC_LAYER_SEQ, "SQ", [graphic_obj])

        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", [layer])

        calipers, contours = read_annotations_from_dicom(ds)
        assert len(calipers) == 1
        assert calipers[0].label == "TestCaliper"
        assert len(calipers[0].start) == 2
        assert len(contours) == 0

    def test_read_contours(self) -> None:
        ds = _make_ds(512, 512)
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            TAG_GRAPHIC_ANNOTATION_SEQ,
            TAG_GRAPHIC_ANNOTATION_UNITS,
            TAG_GRAPHIC_DATA,
            TAG_GRAPHIC_LAYER,
            TAG_GRAPHIC_LAYER_SEQ,
            TAG_GRAPHIC_TYPE,
        )

        graphic_obj = Dataset()
        graphic_obj.add_new(TAG_GRAPHIC_TYPE, "CS", "POLYLINE")
        # 3 points → contour
        graphic_obj.add_new(
            TAG_GRAPHIC_DATA, "FL", [0.2, 0.2, 0.4, 0.4, 0.6, 0.2]
        )

        layer = Dataset()
        layer.add_new(TAG_GRAPHIC_LAYER, "LO", "ContourLayer")
        layer.add_new(TAG_GRAPHIC_ANNOTATION_UNITS, "CS", "NORMALIZED")
        layer.add_new(TAG_GRAPHIC_LAYER_SEQ, "SQ", [graphic_obj])

        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", [layer])

        calipers, contours = read_annotations_from_dicom(ds)
        assert len(contours) == 1
        assert len(calipers) == 0
        assert contours[0].measurement_label == "ContourLayer"

    def test_skip_non_polyline(self) -> None:
        ds = _make_ds()
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            TAG_GRAPHIC_ANNOTATION_SEQ,
            TAG_GRAPHIC_DATA,
            TAG_GRAPHIC_LAYER,
            TAG_GRAPHIC_LAYER_SEQ,
            TAG_GRAPHIC_TYPE,
        )

        graphic_obj = Dataset()
        graphic_obj.add_new(TAG_GRAPHIC_TYPE, "CS", "CIRCLE")
        graphic_obj.add_new(TAG_GRAPHIC_DATA, "FL", [0.1, 0.2, 0.3, 0.4])

        layer = Dataset()
        layer.add_new(TAG_GRAPHIC_LAYER, "LO", "CircleLayer")
        layer.add_new(TAG_GRAPHIC_LAYER_SEQ, "SQ", [graphic_obj])

        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", [layer])

        calipers, contours = read_annotations_from_dicom(ds)
        assert calipers == []
        assert contours == []

    def test_skip_empty_graphic_data(self) -> None:
        ds = _make_ds()
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            TAG_GRAPHIC_ANNOTATION_SEQ,
            TAG_GRAPHIC_LAYER,
            TAG_GRAPHIC_LAYER_SEQ,
            TAG_GRAPHIC_TYPE,
        )

        graphic_obj = Dataset()
        graphic_obj.add_new(TAG_GRAPHIC_TYPE, "CS", "POLYLINE")
        # No GraphicData attribute

        layer = Dataset()
        layer.add_new(TAG_GRAPHIC_LAYER, "LO", "EmptyLayer")
        layer.add_new(TAG_GRAPHIC_LAYER_SEQ, "SQ", [graphic_obj])

        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", [layer])

        calipers, contours = read_annotations_from_dicom(ds)
        assert calipers == []
        assert contours == []

    def test_skip_layer_without_seq(self) -> None:
        ds = _make_ds()
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            TAG_GRAPHIC_ANNOTATION_SEQ,
            TAG_GRAPHIC_LAYER,
        )

        layer = Dataset()
        layer.add_new(TAG_GRAPHIC_LAYER, "LO", "NoSeq")
        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", [layer])

        calipers, contours = read_annotations_from_dicom(ds)
        assert calipers == []
        assert contours == []

    def test_default_rows_columns_when_missing(self) -> None:
        """read_annotations uses 512 as default when Rows/Columns absent."""
        ds = Dataset()
        from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
            TAG_GRAPHIC_ANNOTATION_SEQ,
            TAG_GRAPHIC_DATA,
            TAG_GRAPHIC_LAYER,
            TAG_GRAPHIC_LAYER_SEQ,
            TAG_GRAPHIC_TYPE,
        )

        graphic_obj = Dataset()
        graphic_obj.add_new(TAG_GRAPHIC_TYPE, "CS", "POLYLINE")
        graphic_obj.add_new(TAG_GRAPHIC_DATA, "FL", [0.5, 0.5, 1.0, 1.0])

        layer = Dataset()
        layer.add_new(TAG_GRAPHIC_LAYER, "LO", "DefaultRows")
        layer.add_new(TAG_GRAPHIC_LAYER_SEQ, "SQ", [graphic_obj])
        ds.add_new(TAG_GRAPHIC_ANNOTATION_SEQ, "SQ", [layer])

        calipers, contours = read_annotations_from_dicom(ds)
        assert len(calipers) == 1
        assert calipers[0].start == (256.0, 256.0)
