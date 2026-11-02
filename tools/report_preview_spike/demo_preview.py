"""Manual demo: A4 preview in QPdfView with "where did this value come from" hover.

End-to-end path (а) from the spike: ``render_report`` → PDF bytes →
``QPdfDocument`` → ``QPdfView``; hover hit-tests the value-cell anchors through
``view_map`` and shows the value's identity next to the cursor.

Run (headless container: see README for Qt system stubs)::

    python tools/report_preview_spike/demo_preview.py            # window
    python tools/report_preview_spike/demo_preview.py --smoke    # offscreen check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import view_map  # noqa: E402

from echo_personal_tool.domain.services.report_builder import (  # noqa: E402
    PatientInfo,
    ReportDocument,
    ReportGroup,
    ReportValue,
)
from echo_personal_tool.infrastructure.measurement_report_pdf import render_report  # noqa: E402


def _sample_document() -> tuple[ReportDocument, dict]:
    """Two groups of rows; returns the document and a label lookup for hover text."""
    groups = []
    labels = {}
    for group_index, (title, rows) in enumerate(
        (
            (
                "Левый желудочек",
                (("КДР ЛЖ", "52.0", "мм", "36–51"), ("КСР ЛЖ", "38.0", "мм", "22–40"), ("ФВ ЛЖ", "48.0", "%", "52–72")),
            ),
            ("Правый желудочек", (("ТЗСЛЖ", "32.0", "мм", "24–41"), ("СДЛА", "28.0", "мм рт. ст.", "—"))),
        )
    ):
        values = tuple(
            ReportValue(
                label=label,
                value=value,
                unit=unit,
                norm=norm,
                pathological=value == "48.0",
                group="lv",
            )
            for label, value, unit, norm in rows
        )
        for row, (label, value, unit, _norm) in enumerate(rows):
            labels[(group_index, row)] = f"{label} = {value} {unit}"
        groups.append(ReportGroup(title=title, key="lv", values=values))
    document = ReportDocument(
        patient=PatientInfo(
            name="Иванов И.И.",
            patient_id="12345",
            sex="M",
            study_date="17.05.2024",
            physician="Петров П.П.",
            conclusion="Дилатация ЛП. Нарушение диастолической функции по типу 1.",
        ),
        groups=tuple(groups),
    )
    return document, labels


def _make_hover_filter(owner):  # noqa: ANN001, ANN202 - QObject subclass factory
    from PySide6.QtCore import QEvent, QObject

    class HoverFilter(QObject):
        def eventFilter(self, obj, event):  # noqa: ANN001
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.Leave):
                owner.on_mouse(event)
            return False

    return HoverFilter()


class PreviewDemo:
    def __init__(self) -> None:
        from PySide6.QtCore import QBuffer, QIODevice, Qt
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        from PySide6.QtWidgets import (
            QComboBox,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QVBoxLayout,
            QWidget,
        )

        document, self.labels = _sample_document()
        rendered = render_report(document)
        self.anchors = rendered.anchors

        self.window = QMainWindow()
        self.window.setWindowTitle("UI-4.0 spike — предпросмотр отчёта (QPdfView)")
        central = QWidget()
        self.window.setCentralWidget(central)
        layout = QVBoxLayout(central)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Масштаб:"))
        self.zoom_box = QComboBox()
        self.zoom_box.addItems(["FitToWidth", "FitInView", "Custom 1.0", "Custom 0.5"])
        bar.addWidget(self.zoom_box)
        self.status = QLabel("наведите курсор на значение")
        bar.addWidget(self.status, 1)
        layout.addLayout(bar)

        self.view = QPdfView()
        self.pdf = QPdfDocument()
        self.buffer = QBuffer()
        self.buffer.setData(rendered.pdf)
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.pdf.load(self.buffer)
        self.view.setDocument(self.pdf)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        layout.addWidget(self.view, 1)

        self.screen_res = view_map.screen_resolution(self.view)

        self.highlight = QWidget(self.view.viewport())
        self.highlight.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.highlight.setStyleSheet("background: rgba(43, 209, 203, 70); border: 1px solid #2bd1cb;")
        self.highlight.hide()

        self.zoom_box.currentTextChanged.connect(self._apply_zoom)
        self.view.viewport().installEventFilter(_make_hover_filter(self))

        self.window.resize(1100, 900)

    def _apply_zoom(self, name: str) -> None:
        from PySide6.QtPdfWidgets import QPdfView

        modes = {
            "FitToWidth": (QPdfView.ZoomMode.FitToWidth, None),
            "FitInView": (QPdfView.ZoomMode.FitInView, None),
            "Custom 1.0": (QPdfView.ZoomMode.Custom, 1.0),
            "Custom 0.5": (QPdfView.ZoomMode.Custom, 0.5),
        }
        mode, zoom = modes[name]
        self.view.setZoomMode(mode)
        if zoom is not None:
            self.view.setZoomFactor(zoom)

    def on_mouse(self, event) -> None:
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.Leave:
            self.highlight.hide()
            self.status.setText("наведите курсор на значение")
            return
        pos = event.position()
        geoms = view_map.document_geometry(
            self.view,
            screen_res=self.screen_res,
            page_sizes_pt=[
                (self.pdf.pagePointSize(i).width(), self.pdf.pagePointSize(i).height())
                for i in range(self.pdf.pageCount())
            ],
            current_page=self.view.pageNavigator().currentPage(),
        )
        hit = view_map.hit_test_anchors(geoms, pos.x(), pos.y(), self.anchors, tolerance_pt=3.0)
        if hit is None:
            self.highlight.hide()
            self.status.setText("наведите курсор на значение")
            return
        self.status.setText(f"{hit}: {self.labels.get(hit, '')}")
        rect = self.anchors[hit][0]
        geom = next(g for g in geoms if g.page == rect.page)
        box = view_map.page_rect_to_viewport(geom, rect)
        self.highlight.setGeometry(box.toRect())
        self.highlight.show()
        self.highlight.raise_()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="offscreen: load + grab + exit")
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    demo = PreviewDemo()
    demo.window.show()
    if args.smoke:
        for _ in range(30):
            app.processEvents()
        demo.view.grab()  # forces a paint round trip
        app.processEvents()
        print("smoke ok: preview loaded, anchors:", {k: len(v) for k, v in demo.anchors.items()})
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
