"""Unit tests for PyQtGraph export filtering."""

from __future__ import annotations

import sys

import pytest
from pyqtgraph import exporters as pg_exporters
from pyqtgraph.exporters.CSVExporter import CSVExporter
from pyqtgraph.exporters.ImageExporter import ImageExporter
from pyqtgraph.graphicsItems.PlotItem import PlotItem
from PySide6.QtWidgets import QApplication

from echo_personal_tool.presentation.pyqtgraph_export import (
    allowed_exporter_classes,
    patch_pyqtgraph_export_dialog,
)

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_allowed_exporters_for_viewbox_like_excludes_plot_only() -> None:
    allowed = allowed_exporter_classes(object())
    assert CSVExporter not in allowed
    assert ImageExporter in allowed


def test_allowed_exporters_for_plot_item_includes_all(qapp: QApplication) -> None:
    plot = PlotItem()
    allowed = allowed_exporter_classes(plot)
    assert allowed == frozenset(pg_exporters.listExporters())


def test_patch_is_idempotent() -> None:
    patch_pyqtgraph_export_dialog()
    patch_pyqtgraph_export_dialog()
