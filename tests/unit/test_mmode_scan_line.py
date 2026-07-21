from __future__ import annotations

import pytest
pytestmark = pytest.mark.gui
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem, _MModeNodeItem


def test_scan_line_is_plain_object(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    assert not isinstance(item, QObject)


def test_scan_line_creation(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    assert item.line_start is None
    assert item.line_end is None
    assert not item.is_complete


def test_scan_line_set_start(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    assert item.line_start == (10.0, 20.0)
    assert not item.is_complete


def test_scan_line_set_end(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    assert item.line_end == (100.0, 200.0)
    assert item.is_complete


def test_scan_line_get_endpoints(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    start, end = item.get_endpoints()
    assert start == (10.0, 20.0)
    assert end == (100.0, 200.0)


def test_scan_line_move_endpoints(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    item.move_start_to((15.0, 25.0))
    item.move_end_to((95.0, 195.0))
    start, end = item.get_endpoints()
    assert start == (15.0, 25.0)
    assert end == (95.0, 195.0)


def test_scan_line_clear(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    item.clear()
    assert item.line_start is None
    assert item.line_end is None
    assert item._line_item is None
    assert item._start_node is None
    assert item._end_node is None


def test_scan_line_preview(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.update_preview((50.0, 50.0))
    assert item.line_start == (10.0, 20.0)
    assert item.line_end == (50.0, 50.0)


def test_scan_line_graphics_created_on_set_end(qtbot) -> None:
    item = MModeScanLineItem(viewer_widget=None)
    item.set_start((10.0, 20.0))
    item.set_end((100.0, 200.0))
    assert item._line_item is not None
    assert item._start_node is not None
    assert item._end_node is not None


def test_mmode_node_item_is_scatter(qtbot) -> None:
    node = _MModeNodeItem(viewer_widget=None, endpoint_index=0, position=(10.0, 20.0))
    import pyqtgraph as pg

    assert isinstance(node, pg.ScatterPlotItem)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
