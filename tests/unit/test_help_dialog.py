from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl

pytestmark = pytest.mark.gui


def test_slug_matches_document_anchors() -> None:
    from echo_personal_tool.presentation.help_dialog import _slug

    assert _slug("1. Purpose and quick start") == "1-purpose-and-quick-start"
    assert _slug("10.1. B-Mode automatic path") == "101-b-mode-automatic-path"


def test_all_document_anchors_resolve() -> None:
    import re

    from echo_personal_tool.presentation.help_dialog import _slug

    root = Path(__file__).resolve().parents[2]
    for name in ("HELP_EN.md", "HELP_RU.md"):
        text = (root / "docs" / name).read_text(encoding="utf-8")
        anchors = set(re.findall(r"\]\(#([^)]+)\)", text))
        headings = set()
        for line in text.splitlines():
            match = re.match(r"^#{1,6}\s+(.*)$", line)
            if match:
                headings.add(_slug(match.group(1)))
        assert anchors <= headings, f"{name}: broken anchors {anchors - headings}"


def test_help_dialog_anchor_click_is_safe(qtbot) -> None:
    from echo_personal_tool.presentation.help_dialog import HelpDialog

    dialog = HelpDialog()
    qtbot.addWidget(dialog)
    browser = dialog._browser
    # A valid internal anchor scrolls to its heading; a foreign-file link (no fragment) is a no-op.
    dialog._on_anchor_clicked(QUrl("#1-purpose-and-quick-start"))
    assert browser.textCursor().block().blockFormat().headingLevel() > 0, "the cursor lands on the heading"
    landed_at = browser.textCursor().position()

    dialog._on_anchor_clicked(QUrl("HELP_RU.md"))

    assert browser.textCursor().position() == landed_at


def test_export_help_pdf_writes_a_pdf(tmp_path) -> None:
    from echo_personal_tool.presentation.help_dialog import export_help_pdf

    target = tmp_path / "help.pdf"
    result = export_help_pdf("en", target=target)
    assert result is not None
    assert target.read_bytes()[:5] == b"%PDF-"
