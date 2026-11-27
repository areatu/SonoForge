"""Bind the compact sex selector to the active tab and live norm providers."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject

from echo_personal_tool.application.diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)


def normalized_sex(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"f", "female", "ж", "женский", "w"}:
        return "F"
    if text in {"m", "male", "м", "мужской"}:
        return "M"
    return ""


class PatientSexController(QObject):
    """No global setting: switching tabs restores that study's patient context.

    Unknown source sex defaults the *norm selector* to male, without inventing
    patient demographics. Only an explicit click edits the report header.
    """

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.token: object = None
        window._system_bar.patient_sex_changed.connect(self.select)
        window._controller.state_manager.state_changed.connect(self.sync)
        window.report_coordinator.patient_context_changed.connect(self.sync)
        self.sync()

    def sync(self, _state: object = None) -> None:
        window = self.window
        tab = window._tabs.active
        instance = window._controller.state_manager.snapshot.instance
        token = (
            getattr(tab, "tab_id", None),
            getattr(instance, "path", None),
            getattr(tab, "report_patient_fields", {}).get("sex"),
            getattr(tab, "report_finished", False),
        )
        if token == self.token:
            return
        self.token = token
        sex = ""
        if instance is not None or tab is not None:
            try:
                patient = window.report_coordinator.patient_info(window._controller.compute_study_snapshot())
                sex = normalized_sex(patient.sex)
            except Exception as exc:  # noqa: BLE001 — corrupt demographics must not block image controls
                log_boundary_failure(logger, "patient.demographics", exc, code="io", level=logging.WARNING)
        window._system_bar.set_patient_sex(sex or "M", enabled=tab is not None and not tab.report_finished)

    def select(self, sex: str) -> None:
        window = self.window
        window.report_coordinator.set_patient_field("sex", sex)
        self.token = None
        self.sync()
        page = window.report_coordinator.page
        if page is not None and window.report_coordinator.mode_active():
            patient = window.report_coordinator.patient_info(window._controller.compute_study_snapshot())
            page.patient_editor.set_patient(patient)


def reference_sex(window: Any) -> str:
    """Read on every hover; no stale per-file cache after a manual override."""
    return "male" if window._system_bar.patient_sex() == "M" else "female"


def install_study_header_controls(window: Any) -> None:
    from echo_personal_tool.presentation.training_archive_prompt import install_training_archive_prompt

    if window.findChild(PatientSexController) is None:
        PatientSexController(window)
    install_training_archive_prompt(window)
