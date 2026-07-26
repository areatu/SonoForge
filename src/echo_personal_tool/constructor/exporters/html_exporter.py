"""Export reference handbook to standalone HTML."""

from __future__ import annotations

import base64
from pathlib import Path

from echo_personal_tool.constructor.models import ReferenceModel
from echo_personal_tool.constructor.storage.image_storage import ImageStorage
from echo_personal_tool.infrastructure.i18n import tr


def export_to_html(
    model: ReferenceModel,
    path: Path,
    images_dir: Path | None = None,
) -> None:
    """Export reference to standalone HTML with embedded CSS and images."""
    if images_dir is None:
        images_dir = path.parent.parent / "resources" / "references" / "images"

    image_storage = ImageStorage(images_dir)
    html = _build_html(model, image_storage)
    path.write_text(html, encoding="utf-8")


def _build_html(model: ReferenceModel, image_storage: ImageStorage) -> str:
    parts = [
        "<!DOCTYPE html>",
        "<html lang='ru'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{tr('constructor.export.html_title')}</title>",
        "<style>",
        _CSS,
        "</style>",
        "</head>",
        "<body>",
        "<div class='container'>",
        f"<h1>{tr('constructor.export.html_title')}</h1>",
        "<div class='search-box'>",
        f"<input type='text' id='search' placeholder='{tr('constructor.export.html_search')}' oninput='filterTable()'>",
        "</div>",
    ]

    for topic in model.topics:
        parts.append(f"<div class='topic' id='topic-{topic.slug}'>")
        parts.append(f"<h2 onclick='toggleSection(this)'>{topic.name} <span class='toggle'>▼</span></h2>")
        parts.append("<div class='section-content'>")

        for patho in topic.pathologies:
            parts.append("<div class='pathology-card'>")
            parts.append(f"<h3>{patho.name}</h3>")
            if patho.description:
                parts.append(f"<p class='pathology-desc'>{patho.description}</p>")

            params = patho.all_parameters()
            if params:
                parts.append("<table class='param-table'>")
                parts.append(
                    f"<thead><tr><th>ID</th><th>{tr('constructor.export.col_name')}</th><th>{tr('constructor.export.col_unit')}</th>"
                    f"<th>{tr('constructor.export.col_norm_male')}</th><th>{tr('constructor.export.col_norm_female')}</th><th>{tr('constructor.export.col_desc')}</th></tr></thead>"
                    "<tbody>"
                )
                for param in params:
                    norm_m = _format_norm(param.norm_male)
                    norm_f = _format_norm(param.norm_female)
                    parts.append(
                        f"<tr data-search='{param.id} {param.name}'>"
                        f"<td><code>{param.id}</code></td>"
                        f"<td>{param.name}</td>"
                        f"<td>{param.unit}</td>"
                        f"<td class='norm'>{norm_m}</td>"
                        f"<td class='norm'>{norm_f}</td>"
                        f"<td>{param.pathology_desc or ''}</td></tr>"
                    )
                parts.append("</tbody></table>")

            if patho.has_gradations:
                for grad in patho.gradations:
                    parts.append(f"<h4>{grad.name}</h4>")
                    parts.append("<table class='param-table'>")
                    parts.append(
                        f"<thead><tr><th>ID</th><th>{tr('constructor.export.col_name')}</th><th>{tr('constructor.export.col_unit')}</th>"
                        f"<th>{tr('constructor.export.col_norm_male')}</th><th>{tr('constructor.export.col_norm_female')}</th></tr></thead><tbody>"
                    )
                    for param in grad.parameters:
                        norm_m = _format_norm(param.norm_male)
                        norm_f = _format_norm(param.norm_female)
                        parts.append(
                            f"<tr data-search='{param.id} {param.name}'>"
                            f"<td><code>{param.id}</code></td>"
                            f"<td>{param.name}</td>"
                            f"<td>{param.unit}</td>"
                            f"<td class='norm'>{norm_m}</td>"
                            f"<td class='norm'>{norm_f}</td></tr>"
                        )
                    parts.append("</tbody></table>")

            # Embedded images
            if patho.image_paths:
                parts.append("<div class='images'>")
                for img_name in patho.image_paths:
                    img_path = image_storage.resolve(img_name)
                    if img_path and img_path.exists():
                        b64 = _embed_image(img_path)
                        if b64:
                            parts.append(
                                f"<img src='data:image/{_mime(img_path)};base64,{b64}' "
                                f"alt='{img_name}' class='ref-image'>"
                            )
                        else:
                            parts.append(f"<p class='img-missing'>📷 {img_name}</p>")
                    else:
                        parts.append(f"<p class='img-missing'>📷 {img_name} {tr('constructor.export.html_not_found')}</p>")
                parts.append("</div>")

            parts.append("</div>")  # pathology-card

        parts.append("</div>")  # section-content
        parts.append("</div>")  # topic

    # JavaScript for search + collapse
    parts.append("""
<script>
function filterTable() {
    const q = document.getElementById('search').value.toLowerCase();
    document.querySelectorAll('.param-table tr[data-search]').forEach(tr => {
        tr.style.display = tr.dataset.search.toLowerCase().includes(q) ? '' : 'none';
    });
    document.querySelectorAll('.pathology-card').forEach(card => {
        const visible = card.querySelectorAll('.param-table tr[data-search]:not([style*="display: none"])');
        card.style.display = visible.length > 0 || q === '' ? '' : 'none';
    });
}
function toggleSection(h2) {
    const content = h2.nextElementSibling;
    const toggle = h2.querySelector('.toggle');
    if (content.style.display === 'none') {
        content.style.display = '';
        toggle.textContent = '▼';
    } else {
        content.style.display = 'none';
        toggle.textContent = '▶';
    }
}
</script>
""")

    parts.append("</div></body></html>")
    return "\n".join(parts)


def _embed_image(path: Path) -> str | None:
    try:
        data = path.read_bytes()
        return base64.b64encode(data).decode("ascii")
    except Exception:
        return None


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "png",
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".gif": "gif",
        ".svg": "svg+xml",
    }.get(ext, "png")


def _format_norm(norm) -> str:
    if norm is None:
        return "—"
    parts = []
    if norm.low is not None:
        parts.append(f">={norm.low}")
    if norm.high is not None:
        parts.append(f"<={norm.high}")
    return " — ".join(parts) if parts else "—"


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e8eef4; line-height: 1.6; }  # noqa: E501
.container { max-width: 1100px; margin: 0 auto; padding: 24px; }
h1 { font-size: 24px; margin-bottom: 16px; color: #f1f5f9; }
h2 { font-size: 20px; margin: 24px 0 12px; color: #94a3b8; cursor: pointer; }
h2:hover { color: #f1f5f9; }
h3 { font-size: 16px; margin: 12px 0 8px; color: #e8eef4; }
h4 { font-size: 14px; margin: 8px 0 4px; color: #94a3b8; }
.toggle { font-size: 12px; margin-left: 8px; }
.search-box { margin-bottom: 16px; }
.search-box input { width: 100%; padding: 8px 12px; border: 1px solid #334155; border-radius: 6px; background: #1e293b; color: #e8eef4; font-size: 14px; }  # noqa: E501
.search-box input:focus { outline: none; border-color: #3b82f6; }
.pathology-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; margin: 8px 0; }  # noqa: E501
.pathology-desc { color: #94a3b8; font-style: italic; margin: 4px 0 8px; }
.param-table { width: 100%; border-collapse: collapse; margin: 8px 0; }
.param-table th, .param-table td { border: 1px solid #334155; padding: 6px 10px; text-align: left; }
.param-table th { background: #334155; font-weight: 600; font-size: 13px; }
.param-table td { font-size: 13px; }
.param-table code { color: #3b82f6; font-size: 12px; }
.norm { color: #64748b; }
.images { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; }
.ref-image { max-width: 300px; max-height: 200px; border-radius: 4px; border: 1px solid #334155; }
.img-missing { color: #64748b; font-style: italic; }
.section-content { padding-left: 16px; }
"""
