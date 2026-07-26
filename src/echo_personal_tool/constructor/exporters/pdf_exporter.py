"""Export reference handbook to PDF."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.constructor.models import ReferenceModel
from echo_personal_tool.infrastructure.i18n import tr


def export_to_pdf(model: ReferenceModel, path: Path) -> None:
    """Export reference to PDF via QPrinter."""
    try:
        from PySide6.QtCore import QMarginsF, QPageLayout, QPageSize
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrinter
    except ImportError:
        raise ImportError(tr("constructor.export.pdf_error"))

    # Build HTML
    html = _build_html(model)

    printer = QPrinter(QPrinter.OutputFormat.PdfOutput)
    printer.setOutputFileName(str(path))
    printer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSize.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(15, 15, 15, 15),
        )
    )

    doc = QTextDocument()
    doc.setHtml(html)
    doc.print_(printer)


def _build_html(model: ReferenceModel) -> str:
    parts = [
        "<html><head><style>",
        "body { font-family: sans-serif; font-size: 10pt; }",
        "h1 { font-size: 16pt; page-break-before: always; }",
        "h1:first-of-type { page-break-before: avoid; }",
        "h2 { font-size: 13pt; margin-top: 16pt; }",
        "h3 { font-size: 11pt; }",
        "table { border-collapse: collapse; width: 100%; margin: 8pt 0; }",
        "th, td { border: 1px solid #ccc; padding: 3pt 6pt; text-align: left; }",
        "th { background: #f0f0f0; font-weight: bold; }",
        ".norm { color: #666; }",
        ".pathology { color: #0066cc; font-style: italic; }",
        "</style></head><body>",
    ]

    for topic in model.topics:
        parts.append(f"<h1>{topic.name}</h1>")

        for patho in topic.pathologies:
            parts.append(f"<h2>{patho.name}</h2>")
            if patho.description:
                parts.append(f"<p class='pathology'>{patho.description}</p>")

            params = patho.all_parameters()
            if params:
                parts.append("<table>")
                parts.append(
                    f"<tr><th>ID</th><th>{tr('constructor.export.col_name')}</th><th>{tr('constructor.export.col_unit')}</th><th>{tr('constructor.export.col_norm_male')}</th><th>{tr('constructor.export.col_norm_female')}</th><th>{tr('constructor.export.col_desc')}</th></tr>"
                )
                for param in params:
                    norm_m = _format_norm(param.norm_male)
                    norm_f = _format_norm(param.norm_female)
                    parts.append(
                        f"<tr><td>{param.id}</td><td>{param.name}</td>"
                        f"<td>{param.unit}</td><td class='norm'>{norm_m}</td>"
                        f"<td class='norm'>{norm_f}</td>"
                        f"<td>{param.pathology_desc or ''}</td></tr>"
                    )
                parts.append("</table>")

            if patho.has_gradations:
                for grad in patho.gradations:
                    parts.append(f"<h3>{grad.name}</h3>")
                    parts.append("<table>")
                    parts.append(f"<tr><th>ID</th><th>{tr('constructor.export.col_name')}</th><th>{tr('constructor.export.col_unit')}</th><th>{tr('constructor.export.col_norm_male')}</th><th>{tr('constructor.export.col_norm_female')}</th></tr>")
                    for param in grad.parameters:
                        norm_m = _format_norm(param.norm_male)
                        norm_f = _format_norm(param.norm_female)
                        parts.append(
                            f"<tr><td>{param.id}</td><td>{param.name}</td>"
                            f"<td>{param.unit}</td><td class='norm'>{norm_m}</td>"
                            f"<td class='norm'>{norm_f}</td></tr>"
                        )
                    parts.append("</table>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _format_norm(norm) -> str:
    if norm is None:
        return "—"
    parts = []
    if norm.low is not None:
        parts.append(f">={norm.low}")
    if norm.high is not None:
        parts.append(f"<={norm.high}")
    return " — ".join(parts) if parts else "—"
