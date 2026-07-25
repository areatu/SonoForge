"""Unit tests for presentation/thumbnail_gallery.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
):
    return MagicMock(
        sop_instance_uid=sop_instance_uid,
        media_format=media_format,
        number_of_frames=number_of_frames,
        pixel_spacing=pixel_spacing,
        frame_time_ms=frame_time_ms,
        path=path,
    )


def _fake_series(instances=None):
    return MagicMock(instances=instances or [])


def _fake_study(series=None):
    return MagicMock(series=series or [])


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

    def test_populate_empty(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        w = ThumbnailGalleryWidget()
        w.populate([])
        assert w.count() == 0
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
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget
        from PySide6.QtWidgets import QListWidgetItem

        w = ThumbnailGalleryWidget()
        item = QListWidgetItem()
        item.setData(0, "not an instance")  # _ITEM_ROLE = 0
        w._on_item_clicked(item)
        w.close()
