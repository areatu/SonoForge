"""Viewer cleanup failures are observable without leaking their messages."""

import logging
from types import SimpleNamespace

import pytest

from echo_personal_tool.presentation.viewer.magnifier_controller import MagnifierController

pytestmark = pytest.mark.gui

_PHI_PROBE = "Patient Name /private/1.2.3"


def test_lens_failure_drops_lens_and_logs_safely(monkeypatch, caplog, qapp):
    class Lens:
        def configure(self, *_args):
            raise RuntimeError(_PHI_PROBE)

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


def _widget_with_instance(make_viewer, tmp_path):
    widget = make_viewer()
    widget._current_state = SimpleNamespace(instance=SimpleNamespace(path=tmp_path / "study.dcm"))
    return widget


def test_dicom_tags_overlay_failure_hides_and_logs_safely(monkeypatch, caplog, tmp_path, make_viewer):
    """S2-02: an unreadable header hides the overlay via an allowlisted event."""

    def _explode(*_args, **_kwargs):
        raise ValueError(_PHI_PROBE)

    monkeypatch.setattr("echo_personal_tool.presentation.viewer_widget.read_interesting_dicom_tag_rows", _explode)
    widget = _widget_with_instance(make_viewer, tmp_path)
    widget._interesting_dicom_tags = ("PatientName",)
    with caplog.at_level(logging.DEBUG):
        widget._refresh_dicom_tags_overlay()
    assert widget._dicom_tags_overlay_label.isHidden()
    assert "operation=dicom.annotations code=invalid" in caplog.text
    assert "Patient Name" not in caplog.text
    assert "/private" not in caplog.text
    assert "1.2.3" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_load_ecg_strip_failure_logs_safely(monkeypatch, caplog, tmp_path, make_viewer):
    """S2-02: a missing/unreadable waveform skips the strip with a safe event."""

    def _explode(*_args, **_kwargs):
        raise ValueError(_PHI_PROBE)

    monkeypatch.setattr("echo_personal_tool.presentation.viewer_widget.read_ecg_waveform", _explode)
    widget = _widget_with_instance(make_viewer, tmp_path)
    with caplog.at_level(logging.DEBUG):
        widget._load_ecg_for_strip()
    assert "operation=dicom.waveform code=invalid" in caplog.text
    assert "Patient Name" not in caplog.text
    assert "/private" not in caplog.text
    assert "1.2.3" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_doppler_cardiac_cycles_waveform_failure_degrades_safely(monkeypatch, caplog, tmp_path, make_viewer):
    """S2-02: cycle detection falls back without ECG and logs only a safe event."""

    def _explode(*_args, **_kwargs):
        raise ValueError(_PHI_PROBE)

    monkeypatch.setattr("echo_personal_tool.presentation.viewer_widget.read_ecg_waveform", _explode)
    widget = _widget_with_instance(make_viewer, tmp_path)
    envelope = ((0.0, 0.0), (10.0, 5.0), (20.0, 0.0))
    with caplog.at_level(logging.DEBUG):
        cycles = widget._doppler_cardiac_cycles(envelope)
    assert isinstance(cycles, tuple)
    assert "operation=dicom.waveform code=invalid" in caplog.text
    assert "Patient Name" not in caplog.text
    assert "/private" not in caplog.text
    assert "1.2.3" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
