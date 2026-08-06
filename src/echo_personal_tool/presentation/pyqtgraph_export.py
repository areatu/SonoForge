"""PyQtGraph export dialog tweaks for image-based viewers."""

from __future__ import annotations

from pyqtgraph import exporters as pg_exporters
from pyqtgraph.exporters.CSVExporter import CSVExporter
from pyqtgraph.exporters.HDF5Exporter import HDF5Exporter
from pyqtgraph.exporters.Matplotlib import MatplotlibExporter
from pyqtgraph.graphicsItems.PlotItem import PlotItem
from pyqtgraph.GraphicsScene import exportDialog as pg_export_dialog
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox

_PLOT_ONLY_EXPORTERS = frozenset(
    {CSVExporter, HDF5Exporter, MatplotlibExporter},
)


def allowed_exporter_classes(gitem: object) -> frozenset[type]:
    """Return exporter classes valid for the selected graphics item."""
    if isinstance(gitem, PlotItem):
        return frozenset(pg_exporters.listExporters())
    return frozenset(exporter for exporter in pg_exporters.listExporters() if exporter not in _PLOT_ONLY_EXPORTERS)


def patch_pyqtgraph_export_dialog() -> None:
    """Hide plot-data exporters when the selection is not a PlotItem."""
    dialog_cls = pg_export_dialog.ExportDialog
    if getattr(dialog_cls, "_echo_export_patched", False):
        return

    original_update_format_list = dialog_cls.updateFormatList
    original_export_clicked = dialog_cls.exportClicked

    def update_format_list(self) -> None:
        current = self.ui.formatList.currentItem()
        tree_item = self.ui.itemTree.currentItem()
        gitem = tree_item.gitem if tree_item is not None else self.scene
        allowed = allowed_exporter_classes(gitem)

        self.ui.formatList.clear()
        got_current = False
        for exp in pg_exporters.listExporters():
            if exp not in allowed:
                continue
            item = pg_export_dialog.FormatExportListWidgetItem(
                exp,
                QCoreApplication.translate("Exporter", exp.Name),
            )
            self.ui.formatList.addItem(item)
            if current is not None and item.expClass is current.expClass:
                self.ui.formatList.setCurrentRow(self.ui.formatList.count() - 1)
                got_current = True

        if not got_current and self.ui.formatList.count() > 0:
            self.ui.formatList.setCurrentRow(0)

    def export_clicked(self) -> None:
        self.selectBox.hide()
        if self.currentExporter is None:
            return
        try:
            self.currentExporter.export()
        except (TypeError, Exception) as exc:  # noqa: BLE001 - surface to user
            QMessageBox.warning(
                self,
                "Export failed",
                str(exc),
            )

    dialog_cls.updateFormatList = update_format_list
    dialog_cls.exportClicked = export_clicked
    dialog_cls._echo_export_patched = True

    # Preserve reference for tests/debugging.
    dialog_cls._echo_original_update_format_list = original_update_format_list
    dialog_cls._echo_original_export_clicked = original_export_clicked
