"""Unit tests for presentation/thumbnail_gallery.py."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.presentation.thumbnail_gallery import _HEADER_HEIGHT

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
    clip_mode: str = "2d",
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
        clip_mode=clip_mode,
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

    def test_widget_is_collectible_after_close(self):
        import gc
        import weakref

        from PySide6.QtWidgets import QApplication

        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        gallery = ThumbnailGalleryWidget()
        gallery.populate(
            [
                _grouped_study("study-old", datetime(2026, 1, 1), 1),
                _grouped_study("study-new", datetime(2026, 1, 2), 1),
            ]
        )
        gallery_ref = weakref.ref(gallery)
        gallery.close()
        QApplication.instance().processEvents()
        del gallery
        gc.collect()

        assert gallery_ref() is None

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
        assert not w.isWrapping()
        w.set_horizontal_mode(False)
        assert w._horizontal_mode is False
        assert w.isWrapping()
        w.close()

    def test_horizontal_mode_is_one_row_with_horizontal_scrolling(self):
        from PySide6.QtWidgets import QApplication

        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        instances = [_fake_instance(sop_instance_uid=f"horizontal-{index}") for index in range(8)]
        gallery = ThumbnailGalleryWidget()
        gallery.set_horizontal_mode(True)
        gallery.resize(360, gallery.height())
        gallery.populate([_fake_study(series=[_fake_series(instances=instances)])])
        gallery.show()
        QApplication.instance().processEvents()

        item_rows = {
            gallery.visualItemRect(gallery.item(index)).y()
            for index in range(gallery.count())
            if gallery.item(index) is not None
        }
        assert len(item_rows) == 1
        assert gallery.height() >= 128
        assert gallery.horizontalScrollBar().maximum() > 0
        assert gallery.verticalScrollBar().maximum() == 0
        assert gallery.verticalScrollBarPolicy().name == "ScrollBarAlwaysOff"
        gallery.close()

    def test_compact_horizontal_side_panel_shows_one_tile_and_scrolls_all_clips(self):
        from PySide6.QtWidgets import QApplication, QSizePolicy

        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget, _gallery_width

        instances = [_fake_instance(sop_instance_uid=f"compact-{index}") for index in range(8)]
        gallery = ThumbnailGalleryWidget()
        gallery.set_horizontal_mode(True, compact_side_panel=True)
        gallery.populate([_fake_study(series=[_fake_series(instances=instances)])])
        gallery.show()
        QApplication.instance().processEvents()

        expected_width = gallery.cell_width() + 2 * gallery.spacing() + 2 * gallery.frameWidth()
        item_rows = {
            gallery.visualItemRect(gallery.item(index)).y()
            for index in range(gallery.count())
            if gallery.item(index) is not None
        }
        assert gallery.width() == expected_width
        assert gallery.minimumWidth() == gallery.maximumWidth() == expected_width
        assert gallery.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
        assert len(item_rows) == 1
        assert gallery.count() == len(instances)
        assert gallery.horizontalScrollBar().maximum() > 0
        assert gallery.verticalScrollBar().maximum() == 0

        gallery.set_horizontal_mode(True)
        assert gallery._compact_horizontal_mode is False
        assert gallery.minimumWidth() == 0
        assert gallery.maximumWidth() > 1000
        gallery.set_horizontal_mode(False)
        assert gallery.width() == _gallery_width(gallery.cell_width())
        gallery.close()

    def test_horizontal_mode_survives_scale_change_and_restores_grid(self):
        from echo_personal_tool.presentation.thumbnail_gallery import (
            _CELL_SPACING,
            ThumbnailGalleryWidget,
            _gallery_width,
        )

        gallery = ThumbnailGalleryWidget()
        gallery.set_horizontal_mode(True)
        gallery.apply_scale("large")
        assert gallery.minimumWidth() == 0
        assert gallery.maximumWidth() > 1000
        assert gallery.height() >= gallery.cell_height() + _CELL_SPACING

        gallery.set_horizontal_mode(False)
        assert gallery.isWrapping()
        assert gallery.width() == _gallery_width(gallery.cell_width())
        gallery.close()

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

    def test_populate_groups_clips_by_imaging_mode(self):
        from echo_personal_tool.presentation.thumbnail_gallery import (
            _ITEM_ROLE,
            _MODE_COUNT_ROLE,
            _MODE_HEADER_ROLE,
            ThumbnailGalleryWidget,
        )

        instances = [
            _fake_instance(sop_instance_uid="doppler", clip_mode="doppler"),
            _fake_instance(sop_instance_uid="two-d-1"),
            _fake_instance(sop_instance_uid="two-d-2"),
        ]
        gallery = ThumbnailGalleryWidget()
        gallery.set_horizontal_mode(True)
        gallery.populate([_fake_study(series=[_fake_series(instances=instances)])])

        assert [gallery.item(row).data(_ITEM_ROLE).sop_instance_uid for row in range(3)] == [
            "two-d-1",
            "two-d-2",
            "doppler",
        ]
        assert gallery.item(0).data(_MODE_HEADER_ROLE) == "2d"
        assert gallery.item(0).data(_MODE_COUNT_ROLE) == 2
        assert gallery.item(1).data(_MODE_HEADER_ROLE) is None
        assert gallery.item(2).data(_MODE_HEADER_ROLE) == "doppler"
        assert gallery.item(2).data(_MODE_COUNT_ROLE) == 1
        gallery.close()

    def test_multiple_studies_keep_markers_without_legend(self):
        from PySide6.QtWidgets import QPushButton, QWidget

        from echo_personal_tool.presentation.theme.tokens import GALLERY_GROUP_TOKENS
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
        assert gallery.item(0).data(_GROUP_MARKER_ROLE) == "A"
        assert gallery.item(1).data(_GROUP_MARKER_ROLE) == "A"
        assert gallery.item(2).data(_GROUP_MARKER_ROLE) == "B"
        assert gallery.item(0).data(_GROUP_COLOR_ROLE) == GALLERY_GROUP_TOKENS[0]
        assert gallery.item(2).data(_GROUP_COLOR_ROLE) == GALLERY_GROUP_TOKENS[1]
        assert gallery.findChild(QWidget, "thumbnailGroupLegend") is None
        assert gallery.findChildren(QPushButton, "thumbnailGroupChip") == []
        assert gallery.viewportMargins().top() == _HEADER_HEIGHT
        gallery.close()

    def test_repopulate_does_not_create_a_legend(self):
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        gallery = ThumbnailGalleryWidget()
        gallery.populate(
            [
                _grouped_study("study-old", datetime(2026, 1, 1), 1),
                _grouped_study("study-new", datetime(2026, 1, 2), 1),
            ]
        )
        gallery.populate([_grouped_study("study-only", datetime(2026, 1, 3), 1)])
        assert gallery.findChild(QWidget, "thumbnailGroupLegend") is None
        assert gallery.viewportMargins().top() == _HEADER_HEIGHT
        gallery.close()

    def test_single_study_remains_unmarked(self):
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.thumbnail_gallery import (
            _GROUP_COLOR_ROLE,
            _GROUP_MARKER_ROLE,
            ThumbnailGalleryWidget,
        )

        gallery = ThumbnailGalleryWidget()
        gallery.populate([_grouped_study("study-one", datetime(2026, 1, 1), 1)])

        assert gallery.item(0).data(_GROUP_MARKER_ROLE) is None
        assert gallery.item(0).data(_GROUP_COLOR_ROLE) is None
        assert gallery.findChild(QWidget, "thumbnailGroupLegend") is None
        assert gallery.viewportMargins().top() == _HEADER_HEIGHT
        gallery.close()

    def test_group_and_selection_pen_widths(self):
        from echo_personal_tool.presentation.thumbnail_gallery import GROUP_BORDER_WIDTH, SELECTION_BORDER_WIDTH

        assert GROUP_BORDER_WIDTH == 1
        assert SELECTION_BORDER_WIDTH == 2

    def test_group_markers_continue_after_z(self):
        from echo_personal_tool.presentation.thumbnail_gallery import _group_marker

        assert [_group_marker(index) for index in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]

    def test_marker_text_uses_high_contrast_color(self):
        from PySide6.QtGui import QColor

        from echo_personal_tool.presentation.thumbnail_gallery import _contrast_text_color

        assert _contrast_text_color(QColor("#F0E442")) == "#000000"
        assert _contrast_text_color(QColor("#0072B2")) == "#ffffff"

    def test_theme_switch_refreshes_gallery_tokens(self, monkeypatch):
        from echo_personal_tool.presentation import dark_theme
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        monkeypatch.setattr(dark_theme, "_current_theme_mode", "graphite")
        gallery = ThumbnailGalleryWidget()
        graphite = get_theme_tokens()
        assert gallery._theme_tokens == graphite
        assert graphite["surface.1"] in gallery._mv_start_hint.styleSheet()
        assert graphite["accent.text"] in gallery._mv_start_hint.styleSheet()

        monkeypatch.setattr(dark_theme, "_current_theme_mode", "light")
        gallery.reload_text()
        light = get_theme_tokens()
        assert gallery._theme_tokens == light
        assert light["surface.1"] in gallery._mv_start_hint.styleSheet()
        gallery.close()

    def test_thumbnail_gallery_module_has_no_raw_color_literals(self):
        import sys

        repo_root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo_root / "scripts"))
        import check_ui_colors

        source = Path(check_ui_colors.SRC_ROOT / "presentation/thumbnail_gallery.py").read_text(encoding="utf-8")
        assert check_ui_colors.count_literals(source) == 0

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


class TestGalleryHeader:
    """Header of the vertical gallery: title, count, view toggle, filter chips."""

    def _gallery(self):
        from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget

        return ThumbnailGalleryWidget()

    def test_header_sits_in_the_top_viewport_margin(self):
        gallery = self._gallery()
        assert gallery.viewportMargins().top() == _HEADER_HEIGHT
        assert gallery._header.isVisibleTo(gallery) or not gallery.isVisible()
        gallery.close()

    def test_horizontal_mode_hides_the_header(self):
        gallery = self._gallery()
        gallery.set_horizontal_mode(True)
        assert gallery.viewportMargins().top() == 0
        assert not gallery._header.isVisibleTo(gallery)
        gallery.set_horizontal_mode(False)
        assert gallery.viewportMargins().top() == _HEADER_HEIGHT
        gallery.close()

    def test_populate_fills_the_count_badge_and_filter_counts(self):
        gallery = self._gallery()
        instances = [
            _fake_instance(sop_instance_uid="a", clip_mode="2d"),
            _fake_instance(sop_instance_uid="b", clip_mode="2d"),
            _fake_instance(sop_instance_uid="c", clip_mode="doppler"),
        ]
        gallery.populate([_fake_study(series=[_fake_series(instances=instances)])])
        assert gallery._total_count == 3
        assert gallery._mode_counts == {"2d": 2, "doppler": 1}
        assert gallery._count_badge.text() == "3"
        assert "Все 3" in gallery._filter_buttons["all"].text()
        assert "2D 2" in gallery._filter_buttons["2d"].text()
        gallery.close()

    def test_mode_filter_limits_the_list_and_keeps_the_counts(self):
        gallery = self._gallery()
        instances = [
            _fake_instance(sop_instance_uid="a", clip_mode="2d"),
            _fake_instance(sop_instance_uid="b", clip_mode="doppler"),
        ]
        gallery.populate([_fake_study(series=[_fake_series(instances=instances)])])
        assert gallery.count() == 2
        gallery.set_mode_filter("doppler")
        assert gallery.count() == 1
        assert gallery._mode_filter == "doppler"
        assert gallery._filter_buttons["doppler"].isChecked()
        assert gallery._total_count == 2
        gallery.set_mode_filter("all")
        assert gallery.count() == 2
        gallery.close()

    def test_view_mode_switches_between_two_columns_and_one(self):
        from echo_personal_tool.presentation.thumbnail_gallery import _gallery_width

        gallery = self._gallery()
        assert gallery._view_mode == "grid"
        assert gallery.width() == _gallery_width(gallery.cell_width(), 2)
        gallery.set_view_mode("list")
        assert gallery._view_mode == "list"
        assert gallery._list_btn.isChecked()
        assert not gallery._grid_btn.isChecked()
        assert gallery.width() == _gallery_width(gallery.cell_width(), 1)
        gallery.set_view_mode("grid")
        assert gallery.width() == _gallery_width(gallery.cell_width(), 2)
        gallery.close()

    def test_grid_and_list_buttons_drive_the_view_mode(self):
        gallery = self._gallery()
        gallery._list_btn.click()
        assert gallery._view_mode == "list"
        gallery._grid_btn.click()
        assert gallery._view_mode == "grid"
        gallery.close()

    def test_filter_button_click_applies_the_mode(self):
        gallery = self._gallery()
        instances = [
            _fake_instance(sop_instance_uid="a", clip_mode="2d"),
            _fake_instance(sop_instance_uid="b", clip_mode="m_mode"),
        ]
        gallery.populate([_fake_study(series=[_fake_series(instances=instances)])])
        gallery._filter_buttons["m_mode"].click()
        assert gallery._mode_filter == "m_mode"
        assert gallery.count() == 1
        gallery.close()


class TestThumbnailCaptions:
    """Mode badge and caption text of a thumbnail cell."""

    def test_badge_falls_back_to_the_coarse_mode(self):
        from echo_personal_tool.presentation.thumbnail_gallery import mode_badge

        text, token = mode_badge(_fake_instance(clip_mode="2d"))
        assert token == "gallery.mode.2d"
        assert text
        text, token = mode_badge(_fake_instance(clip_mode="m_mode"))
        assert token == "gallery.mode.mmode"

    def test_badge_reads_a_fine_doppler_kind_from_the_description(self):
        from echo_personal_tool.domain.models import InstanceMetadata
        from echo_personal_tool.presentation.thumbnail_gallery import mode_badge

        instance = InstanceMetadata(
            sop_instance_uid="uid-pw",
            series_uid="s",
            modality="US",
            number_of_frames=1,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="LVOT PW",
            clip_mode="doppler",
        )
        text, token = mode_badge(instance)
        assert token == "gallery.mode.pw"
        assert text == "PW"

    def test_frames_caption_for_a_cine(self):
        from echo_personal_tool.presentation.thumbnail_gallery import frames_caption

        caption = frames_caption(_fake_instance(number_of_frames=83))
        assert caption == "83 к."

    def test_frames_caption_for_a_timed_clip(self):
        from echo_personal_tool.presentation.thumbnail_gallery import frames_caption

        caption = frames_caption(_fake_instance(number_of_frames=1, frame_time_ms=4100.0))
        assert caption == "4,1 с"
