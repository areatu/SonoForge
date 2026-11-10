from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from unittest.mock import MagicMock

import pyqtgraph as pg

from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem
from tests.unit.mmode_fakes import FakeMModeViewer


def test_vertical_lock_default_false():
    item = MModeScanLineItem(host=None)
    assert item.vertical_lock is False


def test_vertical_lock_can_set():
    item = MModeScanLineItem(host=None)
    item.vertical_lock = True
    assert item.vertical_lock is True


def test_guide_items_default_none():
    item = MModeScanLineItem(host=None)
    assert item._guide_h is None
    assert item._guide_v is None


def test_guide_graphics_created():
    item = MModeScanLineItem(host=None)
    item._create_guide_graphics()
    assert item._guide_h is not None
    assert item._guide_v is not None
    assert isinstance(item._guide_h, pg.PlotDataItem)
    assert isinstance(item._guide_v, pg.PlotDataItem)


def test_guide_graphics_removed():
    item = MModeScanLineItem(host=None)
    item._create_guide_graphics()
    item._remove_guide_graphics()
    assert item._guide_h is None
    assert item._guide_v is None


def test_guide_graphics_created_on_set_end_with_vertical_lock():
    item = MModeScanLineItem(host=None)
    item.vertical_lock = True
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    assert item._guide_h is not None
    assert item._guide_v is not None


def test_viewer_widget_vertical_lock_flag():
    controller = FakeMModeViewer().controller
    assert controller.vertical_lock is False


def test_viewer_widget_set_mmode_vertical_lock():
    controller = FakeMModeViewer().controller
    controller.start_line()
    assert controller.line_item is not None
    controller.set_vertical_lock(True)
    assert controller.vertical_lock is True
    assert controller.line_item.vertical_lock is True


def test_viewer_widget_set_mmode_vertical_lock_no_item():
    controller = FakeMModeViewer().controller
    assert controller.line_item is None
    controller.set_vertical_lock(True)
    assert controller.vertical_lock is True


def test_guides_visible_during_drag():
    item = MModeScanLineItem(host=None)
    item.vertical_lock = True
    # Mock view
    item._view = MagicMock()
    item._view.width.return_value = 800
    item._guide_h = MagicMock()
    item._guide_v = MagicMock()
    # Simulate drag update
    item.line_end = (100.0, 200.0)
    item.update_guides((100.0, 200.0), 600.0)
    item._guide_h.setData.assert_called_once()
    item._guide_v.setData.assert_called_once()
