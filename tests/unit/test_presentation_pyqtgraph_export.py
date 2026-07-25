"""Unit tests for presentation/pyqtgraph_export.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestAllowedExporterClasses:
    def test_plotitem_returns_all_exporters(self):
        from pyqtgraph.graphicsItems.PlotItem import PlotItem

        from echo_personal_tool.presentation.pyqtgraph_export import allowed_exporter_classes

        mock_item = MagicMock(spec=PlotItem)
        result = allowed_exporter_classes(mock_item)
        assert len(result) > 0

    def test_non_plotitem_excludes_plot_only(self):
        from echo_personal_tool.presentation.pyqtgraph_export import _PLOT_ONLY_EXPORTERS, allowed_exporter_classes

        class FakeGraphicsItem:
            pass

        result = allowed_exporter_classes(FakeGraphicsItem())
        for exp in _PLOT_ONLY_EXPORTERS:
            assert exp not in result

    def test_result_is_frozenset(self):
        from echo_personal_tool.presentation.pyqtgraph_export import allowed_exporter_classes

        result = allowed_exporter_classes(MagicMock())
        assert isinstance(result, frozenset)

    def test_image_item_excludes_csv(self):
        from pyqtgraph.exporters.CSVExporter import CSVExporter

        from echo_personal_tool.presentation.pyqtgraph_export import allowed_exporter_classes

        mock_item = MagicMock()
        # Not a PlotItem
        result = allowed_exporter_classes(mock_item)
        assert CSVExporter not in result


class TestPlotOnlyExporters:
    def test_contains_expected_exporters(self):
        from pyqtgraph.exporters.CSVExporter import CSVExporter
        from pyqtgraph.exporters.HDF5Exporter import HDF5Exporter
        from pyqtgraph.exporters.Matplotlib import MatplotlibExporter

        from echo_personal_tool.presentation.pyqtgraph_export import _PLOT_ONLY_EXPORTERS

        assert CSVExporter in _PLOT_ONLY_EXPORTERS
        assert HDF5Exporter in _PLOT_ONLY_EXPORTERS
        assert MatplotlibExporter in _PLOT_ONLY_EXPORTERS


class TestPatchPyqtgraphExportDialog:
    def test_first_patch_sets_flag(self):
        from echo_personal_tool.presentation.pyqtgraph_export import patch_pyqtgraph_export_dialog

        try:
            from pyqtgraph.GraphicsScene.exportDialog import ExportDialog
        except ImportError:
            pytest.skip("pyqtgraph ExportDialog not importable on this version")

        dialog_cls = ExportDialog
        # Clean up any prior patching
        if getattr(dialog_cls, "_echo_export_patched", False):
            delattr(dialog_cls, "_echo_export_patched")
            dialog_cls.updateFormatList = dialog_cls._echo_original_update_format_list
            dialog_cls.exportClicked = dialog_cls._echo_original_export_clicked
            delattr(dialog_cls, "_echo_original_update_format_list")
            delattr(dialog_cls, "_echo_original_export_clicked")

        patch_pyqtgraph_export_dialog()
        assert dialog_cls._echo_export_patched is True
        assert hasattr(dialog_cls, "_echo_original_update_format_list")
        assert hasattr(dialog_cls, "_echo_original_export_clicked")

    def test_idempotent(self):
        from echo_personal_tool.presentation.pyqtgraph_export import patch_pyqtgraph_export_dialog

        try:
            from pyqtgraph.GraphicsScene.exportDialog import ExportDialog
        except ImportError:
            pytest.skip("pyqtgraph ExportDialog not importable on this version")

        patch_pyqtgraph_export_dialog()
        patch_pyqtgraph_export_dialog()
        assert ExportDialog._echo_export_patched is True

    def test_patched_update_format_list(self):
        from echo_personal_tool.presentation.pyqtgraph_export import patch_pyqtgraph_export_dialog

        try:
            from pyqtgraph.GraphicsScene.exportDialog import ExportDialog
        except ImportError:
            pytest.skip("pyqtgraph ExportDialog not importable on this version")

        patch_pyqtgraph_export_dialog()
        assert callable(ExportDialog.updateFormatList)

    def test_patched_export_clicked(self):
        from echo_personal_tool.presentation.pyqtgraph_export import patch_pyqtgraph_export_dialog

        try:
            from pyqtgraph.GraphicsScene.exportDialog import ExportDialog
        except ImportError:
            pytest.skip("pyqtgraph ExportDialog not importable on this version")

        patch_pyqtgraph_export_dialog()
        assert callable(ExportDialog.exportClicked)
