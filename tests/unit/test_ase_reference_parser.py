"""Tests for ASE reference markdown loader and renderer."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.domain.services.ase_reference_parser import (
    default_ase_reference_path,
    load_ase_reference_text,
    markdown_to_html,
)

_SAMPLE = """\
# Заголовок

> Источник: ASE

## 1. Левый желудочек

| Показатель | Норма | Источник |
|---|---|---|
| LVEF | 52–72 | [ASE] |

### Подраздел

- пункт один
- пункт два

---

Обычный абзац с **жирным** текстом.
"""


def test_default_path_is_repo_root_file() -> None:
    path = default_ase_reference_path()
    assert path.name == "References ASE+.md"
    assert Path(path).exists()


def test_load_project_reference_file() -> None:
    text = load_ase_reference_text()
    assert "Левый желудочек" in text
    assert "| Показатель |" in text


def test_markdown_to_html_renders_structure() -> None:
    html = markdown_to_html(_SAMPLE)
    assert "<h1>" in html
    assert "<h2>" in html
    assert "<h3>" in html
    assert "<table" in html
    assert "<li>" in html
    assert "<strong>жирным</strong>" in html
    assert "LVEF" in html


def test_markdown_table_normalizes_extra_columns() -> None:
    md = """\
## Тест

| A | B | C |
|---|---|---|
| 1 | 2 | extra | tail |
"""
    html = markdown_to_html(md)
    assert "extra — tail" in html


def test_project_markdown_renders_without_error() -> None:
    html = markdown_to_html(load_ase_reference_text())
    assert "<h2>" in html
    assert "Аортальный стеноз" in html
