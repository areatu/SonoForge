"""The tags overlay is independently owned and driven through narrow callbacks."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from echo_personal_tool.presentation.viewer.overlay_controller import TagsOverlayController

pytestmark = pytest.mark.gui


def test_tags_refresh_style_geometry_and_context(monkeypatch, qtbot, tmp_path):
    host = QWidget()
    qtbot.addWidget(host)
    path = tmp_path / "one.dcm"
    current = [path]
    geo = [QRect(10, 20, 400, 300)]
    calls = []

    def read(source, tags):
        calls.append((source, tags))
        return [SimpleNamespace(keyword="Modality", tag_hex="0008,0060", value="US")]

    monkeypatch.setattr(
        "echo_personal_tool.presentation.viewer.overlay_controller.read_interesting_dicom_tag_rows", read
    )
    owner = TagsOverlayController(host, lambda: geo[0], lambda: current[0])
    owner.configure(" Modality, Rows ", 18, 0.5)
    owner.refresh()
    assert calls == [(path, ("Modality", "Rows"))]
    assert owner.text() == "Modality: US"
    assert "font-size: 18px" in owner.label.styleSheet()
    assert "rgba(0, 0, 0, 127)" in owner.label.styleSheet()
    assert owner.label.x() == 18
    assert owner.label.y() == 320 - owner.label.height() - 8
    geo[0] = QRect(30, 40, 200, 180)
    owner.reposition()
    assert owner.label.x() == 38
    assert owner.label.y() == 220 - owner.label.height() - 8
    current[0] = None
    owner.refresh()
    assert owner.text() == ""
    current[0] = tmp_path / "other.dcm"
    owner.configure("", 12, 0.7)
    owner.refresh()
    assert owner.text() == ""
    assert len(calls) == 1
    owner.configure("Rows", 12, 0.7)
    owner.refresh()
    assert calls[-1] == (current[0], ("Rows",))
    owner.dispose()
    owner.dispose()
    assert owner.text() == ""


def test_owner_and_label_follow_widget_lifetime(qapp):
    host = QWidget()
    owner = TagsOverlayController(host, lambda: QRect(), lambda: None)
    label = owner.label
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(owner)
    assert not isValid(label)
