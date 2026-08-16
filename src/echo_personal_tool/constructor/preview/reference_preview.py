"""Preview window: renders reference as HTML tables."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QTextBrowser,
    QVBoxLayout,
)

from echo_personal_tool.constructor.models import ReferenceModel
from echo_personal_tool.infrastructure.i18n import tr


class ReferencePreviewWindow(QDialog):
    """Read-only preview with HTML tables matching StructuredReferenceWidget."""

    def __init__(self, model: ReferenceModel, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("constructor.preview.title"))
        self.setWindowFlags(Qt.WindowType.Window)
        self._model = model
        self._build_ui()
        self._render()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.document().setDefaultStyleSheet(_CSS)
        layout.addWidget(self._browser)

    def _render(self) -> None:
        parts = ["<html><body>"]
        for topic in self._model.topics:
            parts.append(f"<h1>{topic.name}</h1>")
            for patho in topic.pathologies:
                parts.append(f"<h2>{patho.name}</h2>")
                if patho.description:
                    parts.append(f'<p class="desc">{patho.description}</p>')
                if patho.has_gradations:
                    parts.append(self._render_gradation_table(patho))
                else:
                    parts.append(self._render_flat_table(patho))
                if patho.image_paths:
                    parts.append('<div class="images">')
                    for img in patho.image_paths:
                        parts.append(f'<span class="img">📷 {img}</span>')
                    parts.append("</div>")
        parts.append("</body></html>")
        self._browser.setHtml("\n".join(parts))

    def _render_flat_table(self, patho) -> str:
        params = patho.all_parameters()
        if not params:
            return ""
        rows = []
        for p in params:
            norm_cell = self._render_norm_cell(p)
            rows.append(
                f"<tr><td>{p.id}</td><td>{p.name}</td><td>{p.unit}</td>"
                f"{norm_cell}"
                f"<td>{p.pathology_desc or ''}</td><td>{p.source or ''}</td></tr>"
            )
        return (
            '<table class="data"><thead><tr>'
            f"<th>ID</th><th>{tr('constructor.preview.col_name')}</th><th>{tr('constructor.preview.col_unit')}</th>"
            f"<th>{tr('constructor.preview.col_norm')}</th>"
            f"<th>{tr('constructor.preview.col_desc')}</th><th>{tr('constructor.preview.col_source')}</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    def _render_norm_cell(self, p) -> str:
        if p.gradations:
            parts = ['<td class="norm"><table class="gradations"><tr>']
            for g in p.gradations:
                parts.append(f"<th>{g.name}</th>")
            parts.append("</tr><tr>")
            for g in p.gradations:
                items = []
                if g.range_male:
                    items.append(f"{tr('constructor.meta.sex_male')}: {self._format_norm(g.range_male)}")
                if g.range_female:
                    items.append(f"{tr('constructor.meta.sex_female')}: {self._format_norm(g.range_female)}")
                parts.append(f'<td>{" / ".join(items) if items else "—"}</td>')
            parts.append("</tr></table></td>")
            return "".join(parts)
        norm_m = self._format_norm(p.norm_male)
        norm_f = self._format_norm(p.norm_female)
        return f"<td class='norm'>{norm_m} / {norm_f}</td>"

    def _render_gradation_table(self, patho) -> str:
        grads = patho.gradations
        grad_names = [g.name for g in grads]
        seen: dict[str, object] = {}
        for grad in grads:
            for param in grad.parameters:
                if param.id not in seen:
                    seen[param.id] = param
        params = list(seen.values())

        headers = [tr("constructor.preview.col_parameter")] + grad_names
        header_row = "".join(f"<th>{h}</th>" for h in headers)
        rows = []
        for p in params:
            cells = [f"<td><b>{p.name}</b> ({p.unit})</td>"]
            for grad in grads:
                val = ""
                for gp in grad.parameters:
                    if gp.id == p.id:
                        val = gp.pathology_desc or ""
                        break
                css = " class='patho'" if val else ""
                cells.append(f"<td{css}>{val or '—'}</td>")
            rows.append(f"<tr>{''.join(cells)}</tr>")
        return f'<table class="data"><thead><tr>{header_row}</tr></thead><tbody>{"".join(rows)}</tbody></table>'

    def _format_norm(self, norm) -> str:
        if norm is None:
            return "—"
        parts = []
        if norm.low is not None:
            parts.append(f">={norm.low}")
        if norm.high is not None:
            parts.append(f"<={norm.high}")
        return " — ".join(parts) if parts else "—"

_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #fff; color: #1a1a1a; padding: 20px; line-height: 1.5; }  # noqa: E501
h1 { font-size: 20px; color: #1a1a1a; margin: 24px 0 12px; border-bottom: 2px solid #3b82f6; padding-bottom: 6px; }
h2 { font-size: 16px; color: #374151; margin: 20px 0 8px; }
.desc { color: #6b7280; font-style: italic; margin: 4px 0 8px; }
table.data { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 13px; }
table.data th { background: #f3f4f6; font-weight: bold; padding: 6px 10px; border: 1px solid #d1d5db; text-align: left; }  # noqa: E501
table.data td { padding: 6px 10px; border: 1px solid #d1d5db; }
table.data tr:hover { background: #f9fafb; }
.norm { color: #2563eb; }
.patho { color: #dc2626; }
table.gradations { border-collapse: collapse; width: 100%; }
table.gradations th { background: #e5e7eb; font-weight: bold; padding: 3px 6px; border: 1px solid #d1d5db; font-size: 12px; }
table.gradations td { padding: 3px 6px; border: 1px solid #d1d5db; font-size: 12px; }
.images { margin-top: 8px; }
.img { display: inline-block; padding: 4px 8px; margin: 2px; border: 1px dashed #d1d5db; border-radius: 4px; color: #9ca3af; font-size: 12px; }  # noqa: E501
"""
