"""Unit tests for lazy thumbnail requesting in LocalBrowser."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.thumbnail_scheduler import ThumbnailPriority
from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.presentation.local_browser import LocalBrowserWidget


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _build_study(total_instances: int) -> StudyMetadata:
    instances = tuple(
        InstanceMetadata(
            sop_instance_uid=f"uid-{index}",
            series_uid="series-1",
            modality="US",
            number_of_frames=12,
            pixel_spacing=None,
            frame_time_ms=40.0,
            series_description="Series 1",
            path=Path(f"/tmp/uid-{index}.dcm"),
            media_format="dicom",
        )
        for index in range(total_instances)
    )
    series = SeriesMetadata(
        series_uid="series-1",
        study_uid="study-1",
        modality="US",
        description="A4C",
        instances=instances,
    )
    return StudyMetadata(
        study_uid="study-1",
        study_datetime=datetime(2026, 6, 13, 12, 0, 0),
        series=(series,),
    )


def test_populate_requires_explicit_visible_preview_request(qapp: QApplication) -> None:
    requested: list[tuple[str, ThumbnailPriority | None]] = []

    def loader(instance: InstanceMetadata, priority: ThumbnailPriority) -> None:
        requested.append((instance.sop_instance_uid, priority))

    widget = LocalBrowserWidget()
    widget.resize(320, 280)
    widget.show()
    qapp.processEvents()
    widget.set_thumbnail_loader(loader)

    total_instances = 40
    widget.populate([_build_study(total_instances)])
    qapp.processEvents()

    assert requested == []

    widget.request_visible_previews()
    qapp.processEvents()

    requested_uids = {uid for uid, _priority in requested}
    assert requested_uids
    assert len(requested_uids) < total_instances


def test_selection_requests_p0_for_clicked_instance(qapp: QApplication) -> None:
    requested: list[tuple[str, ThumbnailPriority | None]] = []

    def loader(instance: InstanceMetadata, priority: ThumbnailPriority) -> None:
        requested.append((instance.sop_instance_uid, priority))

    widget = LocalBrowserWidget()
    widget.resize(320, 280)
    widget.show()
    qapp.processEvents()
    widget.set_thumbnail_loader(loader)
    widget.populate([_build_study(24)])
    qapp.processEvents()
    requested.clear()

    clicked_uid = "uid-5"
    clicked_item = widget._items_by_uid[clicked_uid]
    widget.scrollToItem(clicked_item)
    qapp.processEvents()
    widget._on_item_clicked(clicked_item, 0)
    qapp.processEvents()

    assert (clicked_uid, ThumbnailPriority.P0_VISIBLE_SELECTED) in requested


def test_expand_or_scroll_requests_visible_window(qapp: QApplication) -> None:
    requested: list[tuple[str, ThumbnailPriority | None]] = []

    def loader(instance: InstanceMetadata, priority: ThumbnailPriority) -> None:
        requested.append((instance.sop_instance_uid, priority))

    widget = LocalBrowserWidget()
    widget.resize(320, 260)
    widget.show()
    qapp.processEvents()
    widget.set_thumbnail_loader(loader)
    widget.populate([_build_study(80)])
    qapp.processEvents()
    requested.clear()

    series_item = widget.topLevelItem(0).child(0)
    series_item.setExpanded(False)
    qapp.processEvents()
    series_item.setExpanded(True)
    qapp.processEvents()

    scrollbar = widget.verticalScrollBar()
    if scrollbar.maximum() > 0:
        scrollbar.setValue(min(scrollbar.maximum(), scrollbar.singleStep() * 8))
        QTest.qWait(35)
        qapp.processEvents()

    assert requested
    priorities = {priority for _uid, priority in requested}
    assert ThumbnailPriority.P1_NEAR_VISIBLE in priorities
    assert ThumbnailPriority.P2_BACKGROUND in priorities


def test_one_arg_loader_compatibility_path(qapp: QApplication) -> None:
    called_uids: list[str] = []

    def loader(instance: InstanceMetadata) -> None:
        called_uids.append(instance.sop_instance_uid)

    widget = LocalBrowserWidget()
    widget.set_thumbnail_loader(loader)
    instance = _build_study(1).series[0].instances[0]

    widget._request_thumbnail(instance, ThumbnailPriority.P0_VISIBLE_SELECTED)

    assert called_uids == [instance.sop_instance_uid]


def test_two_arg_loader_compatibility_path(qapp: QApplication) -> None:
    calls: list[tuple[str, ThumbnailPriority]] = []

    def loader(instance: InstanceMetadata, priority: ThumbnailPriority) -> None:
        calls.append((instance.sop_instance_uid, priority))

    widget = LocalBrowserWidget()
    widget.set_thumbnail_loader(loader)
    instance = _build_study(1).series[0].instances[0]

    widget._request_thumbnail(instance, ThumbnailPriority.P0_VISIBLE_SELECTED)

    assert calls == [(instance.sop_instance_uid, ThumbnailPriority.P0_VISIBLE_SELECTED)]


def test_internal_loader_typeerror_is_not_swallowed(qapp: QApplication) -> None:
    def loader(_instance: InstanceMetadata, _priority: ThumbnailPriority) -> None:
        raise TypeError("internal loader failure")

    widget = LocalBrowserWidget()
    widget.set_thumbnail_loader(loader)
    instance = _build_study(1).series[0].instances[0]

    with pytest.raises(TypeError, match="internal loader failure"):
        widget._request_thumbnail(instance, ThumbnailPriority.P1_NEAR_VISIBLE)
