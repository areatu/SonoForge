"""Unit tests for presentation/thumbnail_gallery.py."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _fake_instance(
    sop_instance_uid: str = "uid-001",
    media_format: str = "dicom",
    number_of_frames: int = 1,
    pixel_spacing: tuple | None = None,
    frame_time_ms: float | None = None,
    path: Path | None = None,
    created_at: datetime | None = None,
):
    return InstanceMetadata(
        sop_instance_uid=sop_instance_uid,
        series_uid="series-001",
        modality="US",
        number_of_frames=number_of_frames,
        pixel_spacing=pixel_spacing,
        frame_time_ms=frame_time_ms,
        series_description="",
        path=path,
        media_format=media_format,
        created_at=created_at,
    )


def _fake_series(instances=None):
    return SeriesMetadata(
        series_uid="series-001",
        study_uid="study-001",
        modality="US",
        description="",
        instances=tuple(instances or []),
    )


def _fake_study(series=None):
    return StudyMetadata(
        study_uid="study-001",
        study_datetime=datetime(2026, 1, 1, 12, 0, 0),
        series=tuple(series or []),
    )


def _grouped_study(study_uid: str, study_date: datetime, instance_count: int) -> StudyMetadata:
    instances = [
        _fake_instance(sop_instance_uid=f"{study_uid}-sop-{index}", path=Path(f"{index:03}.dcm"))
        for index in range(instance_count)
    ]
    series = SeriesMetadata(
        series_uid=f"{study_uid}-series",
        study_uid=study_uid,
        modality="US",
        description="",
        instances=tuple(instances),
    )
    return StudyMetadata(study_uid=study_uid, study_datetime=study_date, series=(series,))


class TestHasDicomTags:
    def test_non_dicom_returns_false(self):
        from echo_personal_tool.presentation.thumbnail_gallery import _has_dicom_tags

        inst = _fake_instance(media_format="mp4")
        assert _has_dicom_tags(inst) is False

    def test_dicom_with_spacing(self):
        from echo_personal_tool.presentation.thumbnail_gallery import _has_dicom_tags

        inst = _fake_instance(media_format="dicom", pixel_spacing=(0.5, 0.5))
        assert _has_dicom_tags(inst) is True

    def test_dicom_with_frame_time(self):
        from echo_personal_tool.presentation.thumbnail_gallery import _has_dicom_tags

        inst = _fake_instance(media_format="dicom", frame_time_ms=33.0)
        assert _has_dicom_tags(inst) is True

    def test_dicom_no_tags(self):
        from echo_personal_tool.presentation.thumbnail_gallery import _has_dicom_tags

        inst = _fake_instance(media_format="dicom", pixel_spacing=None, frame_time_ms=None)
        assert _has_dicom_tags(inst) is False


class TestGalleryWidth:
    def test_formula(self):
        from echo_personal_tool.presentation.thumbnail_gallery import _COLUMN_COUNT, _SCROLLBAR_GUTTER, _gallery_width

        cell_w = 108
        expected = _COLUMN_COUNT * cell_w + (_COLUMN_COUNT - 1) * 2 + _SCROLLBAR_GUTTER
        assert _gallery_width(cell_w) == expected


class TestThumbnailGalleryWidget:
    def test_initial_state(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        assert w.objectName() == "thumbnailGallery"
        assert not w._collapsed
        assert w._horizontal_mode is False
        w.close()

    def test_cell_dimensions(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        assert w.cell_width() > 0
        assert w.cell_height() > 0
        w.close()

    def test_apply_scale_small(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        old_w = w.cell_width()
        w.apply_scale("small")
        assert w.cell_width() < old_w or w.cell_width() == 84
        w.close()

    def test_apply_scale_large(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        w.apply_scale("large")
        assert w.cell_width() == 192
        w.close()

    def test_apply_scale_unknown_falls_back(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        w.apply_scale("nonexistent")
        # Falls back to medium
        assert w.cell_width() == 108
        w.close()

    def test_set_horizontal_mode(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        w.set_horizontal_mode(True)
        assert w._horizontal_mode is True
        w.set_horizontal_mode(False)
        assert w._horizontal_mode is False
        w.close()

    def test_set_thumbnail_loader(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        loader = MagicMock()
        w.set_thumbnail_loader(loader)
        assert w._thumbnail_loader is loader
        w.close()

    def test_set_thumbnail_loader_accepts_priority(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()

        def loader_with_priority(instance, priority):
            pass

        w.set_thumbnail_loader(loader_with_priority)
        assert w._loader_accepts_priority is True
        w.close()

    def test_populate(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        inst = _fake_instance(sop_instance_uid="test-uid")
        series = _fake_series(instances=[inst])
        study = _fake_study(series=[series])
        w = ThumbnailGalleryWidget()
        w.populate([study])
        assert w.count() == 1
        assert w._instances[0].sop_instance_uid == "test-uid"
        w.close()

    def test_populate_multiple_instances(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        insts = [_fake_instance(sop_instance_uid=f"uid-{i}") for i in range(5)]
        series = _fake_series(instances=insts)
        study = _fake_study(series=[series])
        w = ThumbnailGalleryWidget()
        w.populate([study])
        assert w.count() == 5
        w.close()

    def test_multiple_studies_are_grouped_with_markers_colors_and_legend(self):
        from echo_personal_tool.presentation.thumbnail_gallery import (
            _GROUP_COLOR_ROLE,
            _GROUP_MARKER_ROLE,
            ThumbnailGalleryWidget,
        )

        older = _grouped_study("study-old", datetime(2026, 1, 1), 1)
        newer = _grouped_study("study-new", datetime(2026, 1, 2), 2)
        gallery = ThumbnailGalleryWidget()
        gallery.populate([older, newer])

        assert gallery.count() == 3
        assert gallery._gallery_groups[0].marker == "A"
        assert gallery._gallery_groups[1].marker == "B"
        assert gallery.item(0).data(_GROUP_MARKER_ROLE) == "A"
        assert gallery.item(1).data(_GROUP_MARKER_ROLE) == "A"
        assert gallery.item(2).data(_GROUP_MARKER_ROLE) == "B"
        assert gallery.item(0).data(_GROUP_COLOR_ROLE) != gallery.item(2).data(_GROUP_COLOR_ROLE)
        assert not gallery._group_legend.isHidden()
        assert gallery._group_legend_height > 0

        from echo_personal_tool.infrastructure.i18n import tr_plural

        first_group_chip = gallery._group_legend_layout.itemAt(0).widget()
        assert "A" in first_group_chip.text()
        assert gallery._gallery_groups[0].study_date in first_group_chip.text()
        assert tr_plural("gallery.group.clips", 2) in first_group_chip.text()
        assert "study-new" not in first_group_chip.text()
        assert "000.dcm" not in first_group_chip.text()

        second_group_chip = gallery._group_legend_layout.itemAt(1).widget()
        assert tr_plural("gallery.group.clips", 1) in second_group_chip.text()
        second_group_chip.click()
        assert gallery.currentItem() is gallery._gallery_groups[1].first_item
        gallery.close()

    def test_single_study_remains_unmarked(self):
        from echo_personal_tool.presentation.thumbnail_gallery import (
            _GROUP_COLOR_ROLE,
            _GROUP_MARKER_ROLE,
            ThumbnailGalleryWidget,
        )

        gallery = ThumbnailGalleryWidget()
        gallery.populate([_grouped_study("study-one", datetime(2026, 1, 1), 1)])

        assert gallery.item(0).data(_GROUP_MARKER_ROLE) is None
        assert gallery.item(0).data(_GROUP_COLOR_ROLE) is None
        assert gallery._group_legend.isHidden()
        assert gallery._group_legend_height == 0
        gallery.close()

    def test_group_markers_continue_after_z(self):
        from echo_personal_tool.presentation.thumbnail_gallery import _group_marker

        assert [_group_marker(index) for index in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]

    def test_marker_text_uses_high_contrast_color(self):
        from PySide6.QtGui import QColor

        from echo_personal_tool.presentation.thumbnail_gallery import _contrast_text_color

        assert _contrast_text_color(QColor("#F0E442")) == "#000000"
        assert _contrast_text_color(QColor("#0072B2")) == "#ffffff"

    def test_populate_empty(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        w.populate([])
        assert w.count() == 0
        w.close()

    def test_populate_orders_by_creation_date(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        insts = [
            _fake_instance(sop_instance_uid="late", created_at=datetime(2026, 1, 3)),
            _fake_instance(sop_instance_uid="early", created_at=datetime(2026, 1, 1)),
            _fake_instance(sop_instance_uid="mid", created_at=datetime(2026, 1, 2)),
        ]
        study = _fake_study(series=[_fake_series(instances=insts)])
        w = ThumbnailGalleryWidget()
        w.populate([study])
        assert [i.sop_instance_uid for i in w._instances] == ["early", "mid", "late"]
        w.close()

    def test_set_sort_mode_repopulates(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        insts = [
            _fake_instance(sop_instance_uid="a", path=Path("002.dcm"), created_at=datetime(2026, 1, 1)),
            _fake_instance(sop_instance_uid="b", path=Path("001.dcm"), created_at=datetime(2026, 1, 2)),
        ]
        study = _fake_study(series=[_fake_series(instances=insts)])
        w = ThumbnailGalleryWidget()
        w.populate([study])
        assert [i.sop_instance_uid for i in w._instances] == ["a", "b"]
        w.set_sort_mode("filename")
        assert w._sort_mode == "filename"
        assert [i.sop_instance_uid for i in w._instances] == ["b", "a"]
        w.close()

    def test_set_thumbnail(self):
        from PySide6.QtGui import QImage

        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        img = QImage(10, 10, QImage.Format.Format_RGB888)
        w.set_thumbnail("test-uid", img)
        assert "test-uid" in w._thumbnail_pixmaps
        w.close()

    def test_set_thumbnail_null_image(self):
        from PySide6.QtGui import QImage

        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        img = QImage()
        w.set_thumbnail("test-uid", img)
        assert "test-uid" not in w._thumbnail_pixmaps
        w.close()

    def test_thumbnail_pixmap(self):
        from PySide6.QtGui import QImage

        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        assert w.thumbnail_pixmap("missing") is None
        img = QImage(10, 10, QImage.Format.Format_RGB888)
        w.set_thumbnail("test-uid", img)
        assert w.thumbnail_pixmap("test-uid") is not None
        w.close()

    def test_select_next_instance(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        insts = [_fake_instance(sop_instance_uid=f"uid-{i}") for i in range(3)]
        series = _fake_series(instances=insts)
        study = _fake_study(series=[series])
        w = ThumbnailGalleryWidget()
        w.populate([study])
        w.setCurrentRow(0)
        w.select_next_instance()
        assert w.currentRow() == 1
        w.close()

    def test_select_next_at_end(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        inst = _fake_instance()
        series = _fake_series(instances=[inst])
        study = _fake_study(series=[series])
        w = ThumbnailGalleryWidget()
        w.populate([study])
        w.setCurrentRow(0)
        w.select_next_instance()
        assert w.currentRow() == 0
        w.close()

    def test_select_previous_instance(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        insts = [_fake_instance(sop_instance_uid=f"uid-{i}") for i in range(3)]
        series = _fake_series(instances=insts)
        study = _fake_study(series=[series])
        w = ThumbnailGalleryWidget()
        w.populate([study])
        w.setCurrentRow(2)
        w.select_previous_instance()
        assert w.currentRow() == 1
        w.close()

    def test_select_previous_at_start(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        inst = _fake_instance()
        series = _fake_series(instances=[inst])
        study = _fake_study(series=[series])
        w = ThumbnailGalleryWidget()
        w.populate([study])
        w.setCurrentRow(0)
        w.select_previous_instance()
        assert w.currentRow() == 0
        w.close()

    def test_toggle_collapse(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        assert not w.is_collapsed
        w.toggle_collapse()
        # After animation finishes, should be collapsed
        w.close()

    def test_is_collapsed_property(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        assert w.is_collapsed is False
        w.close()

    def test_visible_instance_uids_empty(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        result = w._visible_instance_uids()
        assert isinstance(result, set)
        w.close()

    def test_context_menu_does_not_crash(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        w._on_context_menu(w.viewport().mapToGlobal(w.rect().center()))
        w.close()

    def test_item_clicked_with_non_instance(self):
        from PySide6.QtWidgets import QListWidgetItem

        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        item = QListWidgetItem()
        item.setData(0, "not an instance")  # _ITEM_ROLE = 0
        w._on_item_clicked(item)
        w.close()


class TestThumbnailPreviewSize:
    """Э4: decode box = logical thumbnail × device pixel ratio."""

    def test_medium_scale_at_100_percent(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        gallery = ThumbnailGalleryWidget()
        gallery.apply_scale("medium")
        assert gallery.thumbnail_preview_size() == 96

    def test_large_scale_is_bigger(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        gallery = ThumbnailGalleryWidget()
        gallery.apply_scale("large")
        assert gallery.thumbnail_preview_size() == 176

    def test_device_pixel_ratio_multiplies_the_box(self, monkeypatch):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        gallery = ThumbnailGalleryWidget()
        gallery.apply_scale("medium")
        monkeypatch.setattr(gallery, "devicePixelRatioF", lambda: 2.0, raising=False)
        assert gallery.thumbnail_preview_size() == 192
