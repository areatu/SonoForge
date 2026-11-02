"""Rebuild-budget bench for the report preview (UI-4.0, spec §4.6).

The spec picks PDF-preview path (а) only if a rebuild after a value change fits
in **500 ms** (with debouncing). This bench measures the three stages of one
preview rebuild on a synthetic study:

1. ``render_report`` (reportlab build of the PDF bytes + value anchors);
2. ``QPdfDocument.load`` of those bytes;
3. the first page raster through ``QPdfDocument.render`` (what the A4 sheet
   shows; ``QPdfView`` does this on a render thread and does not block the UI,
   but the budget counts it).

Run::

    python tools/report_preview_spike/render_bench.py [--iterations 25] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from echo_personal_tool.domain.services.report_builder import (  # noqa: E402
    PatientInfo,
    ReportDocument,
    ReportGroup,
    ReportValue,
)
from echo_personal_tool.infrastructure.measurement_report_pdf import render_report  # noqa: E402

BUDGET_MS = 500.0


def _document(groups: int, values: int, *, conclusion: str = "") -> ReportDocument:
    built: list[ReportGroup] = []
    labels = ("КДР ЛЖ", "КСР ЛЖ", "ТМЖП", "ТЗСЛЖ", "КДО ЛЖ", "КСО ЛЖ", "ФВ ЛЖ", "ММЛЖ", "ДМЛЖ", "СДЛА")
    for group_index in range(groups):
        rows = tuple(
            ReportValue(
                label=f"{labels[row % len(labels)]} {group_index}-{row}",
                value=f"{40.0 + group_index + row:.1f}",
                unit="мм",
                norm="36–51",
                pathological=(row % 5 == 4),
                group="lv",
            )
            for row in range(values)
        )
        built.append(ReportGroup(title=f"Группа {group_index}", key="lv", values=rows))
    return ReportDocument(
        patient=PatientInfo(
            name="Иванов И.И.",
            patient_id="12345",
            sex="M",
            study_date="17.05.2024",
            height_cm=178,
            weight_kg=80,
            physician="Петров П.П.",
            institution="ГБУЗ ОКБ",
            indication="Одышка при нагрузке",
            conclusion=conclusion,
        ),
        groups=tuple(built),
    )


SCENARIOS = {
    "small (2×4)": _document(2, 4),
    "typical (10×8)": _document(10, 8),
    "large (25×10 + conclusion)": _document(
        25, 10, conclusion="Заключение.\n" + "Дилатация ЛП, нарушение диастолической функции по типу 1. " * 8
    ),
}


def _percentile(samples_ms: list[float], fraction: float) -> float:
    ordered = sorted(samples_ms)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def bench(scenario: str, document: ReportDocument, iterations: int) -> dict:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    render_ms: list[float] = []
    load_ms: list[float] = []
    raster_ms: list[float] = []
    anchors = 0
    page_count = 0

    for _ in range(iterations):
        t0 = time.perf_counter()
        rendered = render_report(document)
        t1 = time.perf_counter()
        render_ms.append((t1 - t0) * 1000)

        device = QBuffer()
        device.setData(rendered.pdf)
        device.open(QIODevice.OpenModeFlag.ReadOnly)
        pdf = QPdfDocument()
        t0 = time.perf_counter()
        pdf.load(device)
        while pdf.status() == QPdfDocument.Status.Loading:
            app.processEvents()
        t1 = time.perf_counter()
        load_ms.append((t1 - t0) * 1000)

        size = pdf.pagePointSize(0)
        image = QImage()
        t0 = time.perf_counter()
        image = pdf.render(0, size.toSize() * 2)  # ~150 dpi sheet
        t1 = time.perf_counter()
        raster_ms.append((t1 - t0) * 1000)
        assert not image.isNull()

        anchors = sum(len(rects) for rects in rendered.anchors.values())
        page_count = pdf.pageCount()

    totals = [a + b for a, b in zip(render_ms, load_ms)]
    result = {
        "scenario": scenario,
        "values": sum(len(g.values) for g in document.groups),
        "anchors": anchors,
        "pages": page_count,
        "pdf_bytes": len(render_report(document).pdf),
        "render_ms": {"p50": statistics.median(render_ms), "p95": _percentile(render_ms, 0.95), "max": max(render_ms)},
        "load_ms": {"p50": statistics.median(load_ms), "p95": _percentile(load_ms, 0.95), "max": max(load_ms)},
        "raster_ms": {"p50": statistics.median(raster_ms), "p95": _percentile(raster_ms, 0.95), "max": max(raster_ms)},
        "rebuild_ms": {"p50": statistics.median(totals), "p95": _percentile(totals, 0.95), "max": max(totals)},
    }
    result["budget_500ms_ok"] = result["rebuild_ms"]["p95"] <= BUDGET_MS
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    results = [bench(name, doc, args.iterations) for name, doc in SCENARIOS.items()]

    print(f"rebuild budget: p95 ≤ {BUDGET_MS:.0f} ms (render + load; raster shown separately)")
    print()
    header = f"{'scenario':28} {'values':>6} {'pages':>5} {'render p50/p95':>16} {'load p50/p95':>14} {'raster p50/p95':>16} {'rebuild p95':>12} {'ok':>4}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['scenario']:28} {r['values']:>6} {r['pages']:>5} "
            f"{r['render_ms']['p50']:>7.1f}/{r['render_ms']['p95']:<8.1f} "
            f"{r['load_ms']['p50']:>6.1f}/{r['load_ms']['p95']:<7.1f} "
            f"{r['raster_ms']['p50']:>7.1f}/{r['raster_ms']['p95']:<8.1f} "
            f"{r['rebuild_ms']['p95']:>12.1f} "
            f"{'yes' if r['budget_500ms_ok'] else 'NO':>4}"
        )

    if args.json:
        args.json.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwritten: {args.json}")

    return 0 if all(r["budget_500ms_ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
