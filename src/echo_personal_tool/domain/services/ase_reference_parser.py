"""Load and render ``References ASE+.md`` for the norms viewer."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path


def default_references_dir() -> Path:
    """Return the bundled references directory, or project-tree fallback."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        candidate = base / "echo_personal_tool" / "resources" / "references"
        if candidate.is_dir():
            return candidate
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "resources" / "references"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("resources/references/ not found in project tree")


def scan_references_dir(directory: Path | None = None) -> list[tuple[str, Path, str]]:
    """Scan *directory* for .md and .pdf files, return sorted (name, path, kind)."""
    ref_dir = directory or default_references_dir()
    docs: list[tuple[str, Path, str]] = []
    for path in sorted(ref_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in (".md", ".pdf"):
            kind = "pdf" if path.suffix.lower() == ".pdf" else "md"
            docs.append((path.stem, path, kind))
    return docs


def default_ase_reference_path() -> Path:
    try:
        ref_dir = default_references_dir()
        candidate = ref_dir / "References ASE+.md"
        if candidate.is_file():
            return candidate
    except FileNotFoundError:
        pass
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "References ASE+.md"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("References ASE+.md not found in project tree")


def load_ase_reference_text(path: Path | None = None) -> str:
    md_path = path or default_ase_reference_path()
    return md_path.read_text(encoding="utf-8")


def markdown_to_html(text: str) -> str:
    lines = text.splitlines()
    parts = ["<html><body>"]
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped == "---":
            parts.append("<hr/>")
            index += 1
            continue
        if stripped.startswith("|"):
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            parts.append(_render_table(table_lines))
            continue
        if stripped.startswith("### "):
            parts.append(f"<h3>{_inline_html(stripped[4:])}</h3>")
            index += 1
            continue
        if stripped.startswith("## "):
            parts.append(f"<h2>{_inline_html(stripped[3:])}</h2>")
            index += 1
            continue
        if stripped.startswith("# "):
            parts.append(f"<h1>{_inline_html(stripped[2:])}</h1>")
            index += 1
            continue
        if stripped.startswith(">"):
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().lstrip(">").strip())
                index += 1
            body = "<br/>".join(_inline_html(part) for part in quote_lines)
            parts.append(f"<blockquote><p>{body}</p></blockquote>")
            continue
        if stripped.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(f"<li>{_inline_html(lines[index].strip()[2:])}</li>")
                index += 1
            parts.append("<ul>" + "".join(items) + "</ul>")
            continue
        if re.match(r"^\d+\.\s", stripped):
            items = []
            while index < len(lines) and re.match(r"^\d+\.\s", lines[index].strip()):
                item_text = re.sub(r"^\d+\.\s", "", lines[index].strip())
                items.append(f"<li>{_inline_html(item_text)}</li>")
                index += 1
            parts.append("<ol>" + "".join(items) + "</ol>")
            continue
        paragraph = [stripped]
        index += 1
        while index < len(lines):
            next_line = lines[index].strip()
            if not next_line or _is_block_start(next_line):
                break
            paragraph.append(next_line)
            index += 1
        parts.append(f"<p>{_inline_html(' '.join(paragraph))}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _is_block_start(line: str) -> bool:
    if line == "---":
        return True
    if line.startswith("|"):
        return True
    if line.startswith(("# ", "## ", "### ", "> ", "- ")):
        return True
    return bool(re.match(r"^\d+\.\s", line))


def _split_md_row(line: str) -> tuple[str, ...]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return tuple(cells)


def _is_separator(line: str) -> bool:
    stripped = line.strip().strip("|")
    return bool(stripped) and all(ch in "-:| " for ch in stripped)


def _normalize_row(row: tuple[str, ...], header_count: int) -> tuple[str, ...]:
    if len(row) == header_count:
        return row
    if len(row) < header_count:
        return row + ("",) * (header_count - len(row))
    merged_tail = " — ".join(cell for cell in row[header_count - 1 :] if cell)
    return row[: header_count - 1] + (merged_tail,)


def _render_table(table_lines: list[str]) -> str:
    if not table_lines:
        return ""
    headers = _split_md_row(table_lines[0])
    rows: list[tuple[str, ...]] = []
    start = 1
    if start < len(table_lines) and _is_separator(table_lines[start]):
        start += 1
    for line in table_lines[start:]:
        rows.append(_normalize_row(_split_md_row(line), len(headers)))
    header_html = "".join(f"<th>{_inline_html(cell)}</th>" for cell in headers)
    body_html = []
    for row in rows:
        cells = "".join(f"<td>{_inline_html(cell)}</td>" for cell in row)
        body_html.append(f"<tr>{cells}</tr>")
    return (
        '<table cellspacing="0" cellpadding="6">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_html)}</tbody>"
        "</table>"
    )


def _inline_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = escaped.replace("$", "")
    return escaped
