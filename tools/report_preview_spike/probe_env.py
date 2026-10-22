"""Environment probe for the UI-4.0 spike: is PDF preview via QtPdf viable?

Answers, on the exact PySide6 build the project locks (``uv.lock``):

* are ``PySide6.QtPdf`` / ``PySide6.QtPdfWidgets`` importable, and which
  distribution ships the binaries (``pyside6-essentials`` or ``pyside6-addons``)
  — matters for packaging and the PyInstaller standalone;
* which QPdfView/QPdfDocument APIs the spike relies on;
* the screen-resolution factor ``QPdfView`` bakes into its layout.

Run (headless container: see README for Qt system stubs)::

    python tools/report_preview_spike/probe_env.py
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import importlib.util
import json
import sys


def _dist_for_file(filename: str) -> list[str]:
    owners = []
    for dist in ("pyside6", "pyside6-essentials", "pyside6-addons", "shiboken6"):
        try:
            files = md.distribution(dist).files or ()
        except md.PackageNotFoundError:
            continue
        if any(str(f).endswith(filename) for f in files):
            owners.append(f"{dist}=={md.version(dist)}")
    return owners


def main() -> int:
    report: dict[str, object] = {}
    report["python"] = sys.version.split()[0]

    import PySide6

    report["pyside6"] = PySide6.__version__

    qt_pdf_spec = importlib.util.find_spec("PySide6.QtPdf")
    qt_pdf_widgets_spec = importlib.util.find_spec("PySide6.QtPdfWidgets")
    report["QtPdf_available"] = bool(qt_pdf_spec)
    report["QtPdfWidgets_available"] = bool(qt_pdf_widgets_spec)
    report["QtPdf_module"] = qt_pdf_spec.origin if qt_pdf_spec else None
    report["QtPdf_binary_providers"] = _dist_for_file("PySide6/QtPdf.abi3.so")
    report["QtPdfWidgets_binary_providers"] = _dist_for_file("PySide6/QtPdfWidgets.abi3.so")

    from PySide6.QtCore import qVersion
    from PySide6.QtPdf import QPdfDocument, QPdfLinkModel, QPdfPageNavigator
    from PySide6.QtPdfWidgets import QPdfView
    from PySide6.QtWidgets import QApplication

    report["qt_runtime"] = qVersion()

    app = QApplication.instance() or QApplication([])
    report["logical_dpi"] = app.primaryScreen().logicalDotsPerInch()
    report["screen_resolution"] = app.primaryScreen().logicalDotsPerInch() / 72.0

    report["QPdfView_api"] = sorted(
        name
        for name in (
            "document",
            "setDocument",
            "pageNavigator",
            "pageMode",
            "zoomMode",
            "zoomFactor",
            "documentMargins",
            "pageSpacing",
            "searchModel",
        )
        if hasattr(QPdfView, name)
    )
    report["QPdfDocument_api"] = sorted(
        name
        for name in ("load", "pageCount", "pagePointSize", "render", "status", "getAllText")
        if hasattr(QPdfDocument, name)
    )
    report["QPdfLinkModel_api"] = sorted(
        name for name in ("linkAt", "setPage", "setDocument") if hasattr(QPdfLinkModel, name)
    )
    report["QPdfPageNavigator_api"] = sorted(
        name for name in ("currentPage", "currentLocation", "currentZoom", "jump") if hasattr(QPdfPageNavigator, name)
    )

    # round trip: a bytes-built PDF must load
    from io import BytesIO

    from PySide6.QtCore import QBuffer, QIODevice
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas

    buffer = BytesIO()
    page = pdf_canvas.Canvas(buffer, pagesize=A4)
    page.drawString(72, 800, "probe")
    page.showPage()
    page.save()
    device = QBuffer()
    device.setData(bytes(buffer.getvalue()))
    device.open(QIODevice.OpenModeFlag.ReadOnly)
    document = QPdfDocument()
    document.load(device)
    report["bytes_round_trip"] = {
        "status": str(document.status()),
        "pages": document.pageCount(),
        "page_point_size": [document.pagePointSize(0).width(), document.pagePointSize(0).height()],
    }

    report["packaging_note"] = (
        "QtPdf/QtPdfWidgets binaries ship in pyside6-addons; the project depends on "
        "the pyside6 meta-package so both wheels are installed. For "
        "sonoforge-standalone.spec add hiddenimports PySide6.QtPdf + PySide6.QtPdfWidgets "
        "when UI-4 imports them and verify the Windows build renders the preview."
    )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
