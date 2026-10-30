"""Viewer cleanup failures are observable without leaking their messages."""

import logging

import pytest

from echo_personal_tool.presentation.viewer.magnifier_controller import MagnifierController

pytestmark = pytest.mark.gui


def test_lens_failure_drops_lens_and_logs_safely(monkeypatch, caplog, qapp):
    class Lens:
        def configure(self, *_args):
            raise RuntimeError("Patient Name /private/1.2.3")

    monkeypatch.setattr("echo_personal_tool.presentation.viewer.magnifier_controller.isValid", lambda _: True)
    controller = MagnifierController()
    controller._lens = Lens()
    with caplog.at_level(logging.DEBUG):
        controller.configure(zoom=3)
    assert controller._lens is None
    assert "operation=ui.cleanup code=cleanup" in caplog.text
    assert "Patient Name" not in caplog.text
    assert "/private" not in caplog.text
    assert "1.2.3" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
