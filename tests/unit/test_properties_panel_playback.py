"""Playback must not rebuild unchanged property forms on every frame."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QLabel

from echo_personal_tool.domain.models.properties_snapshot import PropertiesSnapshot
from echo_personal_tool.presentation.properties_panel import PropertiesPanel

pytestmark = pytest.mark.gui


def test_repeated_snapshot_does_not_rebuild_forms(qtbot, monkeypatch) -> None:
    panel = PropertiesPanel()
    qtbot.addWidget(panel)
    snapshot = PropertiesSnapshot.default(depth_ok=True)
    panel.update_from_snapshot(snapshot)
    labels = panel.findChildren(QLabel)
    assert labels

    calls: list[object] = []
    monkeypatch.setattr(panel, "_clear_form", lambda form: calls.append(form))
    for _ in range(30):
        panel.update_from_snapshot(snapshot)
    assert calls == []


def test_changed_calibration_still_updates(qtbot) -> None:
    panel = PropertiesPanel()
    qtbot.addWidget(panel)
    panel.update_from_snapshot(PropertiesSnapshot.default())
    changed = replace(PropertiesSnapshot.default(), mmode_calibrated=True)
    panel.update_from_snapshot(changed)
    labels = [label.text() for label in panel._calibration_group.findChildren(QLabel)]
    assert any("DICOM" in text or "mm/px" in text or "Complete" in text or "Завершена" in text for text in labels)


def test_measurement_summary_is_deduplicated_and_clear_invalidates(qtbot, monkeypatch) -> None:
    panel = PropertiesPanel()
    qtbot.addWidget(panel)
    panel.update_measurement_info(label="LVOTd", value_mm=20.0, start=(0.0, 0.0), end=(3.0, 4.0))
    calls: list[object] = []
    monkeypatch.setattr(panel, "_clear_form", lambda form: calls.append(form))
    for _ in range(30):
        panel.update_measurement_info(label="LVOTd", value_mm=20.0, start=(0.0, 0.0), end=(3.0, 4.0))
    assert calls == []

    panel.update_measurement_info(label="LVOTd", value_mm=21.0, start=(0.0, 0.0), end=(3.0, 4.0))
    assert len(calls) == 1

    panel.clear_all()
    panel.update_measurement_info(label="LVOTd", value_mm=20.0, start=(0.0, 0.0), end=(3.0, 4.0))
    assert len(calls) == 2


def test_legacy_instance_summary_is_deduplicated(qtbot, monkeypatch) -> None:
    panel = PropertiesPanel()
    qtbot.addWidget(panel)
    kwargs = {"modality": "US", "series_desc": "Echo", "number_of_frames": 30, "frame_time_ms": 33.3}
    panel.update_instance_info(**kwargs)
    calls: list[object] = []
    monkeypatch.setattr(panel, "_clear_form", lambda form: calls.append(form))
    for _ in range(30):
        panel.update_instance_info(**kwargs)
    assert calls == []
    panel.update_instance_info(**{**kwargs, "number_of_frames": 31})
    assert calls
