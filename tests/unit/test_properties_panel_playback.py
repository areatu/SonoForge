"""Playback must not rebuild unchanged property forms on every frame."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QLabel

from echo_personal_tool.application.localization import set_language
from echo_personal_tool.domain.models.calibration import (
    ASSUMPTION_SECONDS_AS_LENGTH,
    CALIBRATION_REGION_REQUIRED,
    CalibrationConfidence,
    CalibrationContext,
    CalibrationRegion,
    CalibrationScope,
)
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


def test_scoped_scales_are_listed_with_bounds_and_an_assumption(qtbot) -> None:
    """A clip with frame/panel scales is not described by one effective value (#555)."""
    set_language("en")
    try:
        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        measured = CalibrationContext(
            spacing=(0.1, 0.1),
            source="SequenceOfUltrasoundRegions",
            confidence=CalibrationConfidence.DERIVED,
            scope=CalibrationScope.REGION,
            region=CalibrationRegion(x0=0, x1=50, y0=0, y1=50),
        )
        assumed = CalibrationContext(
            spacing=(0.2, 0.2),
            source="SequenceOfUltrasoundRegions",
            confidence=CalibrationConfidence.ASSUMED,
            scope=CalibrationScope.REGION,
            region=CalibrationRegion(x0=60, x1=99, y0=0, y1=50),
            assumption=ASSUMPTION_SECONDS_AS_LENGTH,
        )
        snapshot = replace(
            PropertiesSnapshot.default(),
            calibration=None,
            calibration_reason=CALIBRATION_REGION_REQUIRED,
            calibrations=(measured, assumed),
        )
        panel.update_from_snapshot(snapshot)

        labels = [label.text() for label in panel._calibration_group.findChildren(QLabel)]
        text = "\n".join(labels)
        assert "Scales in this clip:" in text
        assert "X[0..50]" in text and "X[60..99]" in text
        assert "time-axis seconds used as length" in text
        assert "assumption" in text.lower()
    finally:
        set_language("en")


def test_identical_scoped_contexts_are_not_repeated(qtbot) -> None:
    set_language("en")
    try:
        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        region = CalibrationRegion(x0=0, x1=50, y0=0, y1=50)
        context = CalibrationContext(
            spacing=(0.1, 0.1),
            source="SequenceOfUltrasoundRegions",
            confidence=CalibrationConfidence.DERIVED,
            scope=CalibrationScope.REGION,
            region=region,
        )
        panel.update_from_snapshot(
            replace(
                PropertiesSnapshot.default(),
                calibration=None,
                calibration_reason=CALIBRATION_REGION_REQUIRED,
                calibrations=(context, context),
            )
        )
        labels = [label.text() for label in panel._calibration_group.findChildren(QLabel)]
        assert sum("region X[0..50]" in text for text in labels) == 1
    finally:
        set_language("en")


def test_an_assumed_isotropic_scale_names_its_reason(qtbot) -> None:
    """«assumed» is repeated in words, not only by colour (#555)."""
    set_language("en")
    try:
        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        context = CalibrationContext(
            spacing=(0.1, 0.1),
            source="manual",
            confidence=CalibrationConfidence.ASSUMED,
            assumed_isotropic=True,
        )
        panel.update_from_snapshot(replace(PropertiesSnapshot.default(), calibration=context, calibrations=(context,)))
        labels = [label.text() for label in panel._calibration_group.findChildren(QLabel)]
        assert "Assumption:" in labels
        assert "isotropy assumed from one known distance" in labels
    finally:
        set_language("en")
