"""The modal «PDF…» job of the report mode (S3-04, #313).

What the job promises, and what the window relies on:

* the dialog is modal, and the window keeps running because the render happens
  on a pool thread;
* cancelling while the sheet renders publishes no file and reports
  :data:`PDF_EXPORT_CANCELLED` — including the case where the dialog is closed
  *before* the worker has finished rendering (the Qt 6 ``canceled`` signal
  arrives a turn later, after a fast render could already have written);
* the callback fires exactly once, with a stable outcome code.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers import report_export_worker as worker_module
from echo_personal_tool.presentation.report_mode.export_job import (
    PDF_EXPORT_CANCELLED,
    PDF_EXPORT_FAILED,
    PDF_EXPORT_FINISHED,
    ReportPdfExportJob,
)

UID = "1.2.840.113619.2.55.3.1234567890.77"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture()
def window(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def _document():
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_document

    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=120.0,
        millimeter_length=48.0,
        frame_index=7,
        sop_instance_uid=UID,
        measurement_id="m-0001",
    )
    return build_report_document(MeasurementSnapshot(linear_measurements=(measurement,)), None)


def _job(window: QWidget, target: Path, outcomes: list[tuple[str, str]]) -> ReportPdfExportJob:
    return ReportPdfExportJob(
        window,
        _document(),
        target,
        on_outcome=lambda outcome, name: outcomes.append((outcome, name)),
    )


def _slow_render(delay_s: float) -> callable:
    def _render(document: object, *, font_size: int = 10) -> SimpleNamespace:
        time.sleep(delay_s)
        return SimpleNamespace(pdf=b"%PDF-1.7 fake report", anchors={})

    return _render


# ── the happy path ───────────────────────────────────────────────────


def test_the_sheet_is_written_and_reported_once(window, tmp_path: Path) -> None:
    target = tmp_path / "study_report.pdf"
    outcomes: list[tuple[str, str]] = []

    _job(window, target, outcomes).run()

    assert outcomes == [(PDF_EXPORT_FINISHED, "study_report.pdf")]
    assert target.read_bytes().startswith(b"%PDF-")


def test_the_destination_is_exposed(window, tmp_path: Path) -> None:
    job = _job(window, tmp_path / "study.pdf", [])

    assert job.destination == tmp_path / "study.pdf"
    assert job.worker is not None


# ── cancellation ─────────────────────────────────────────────────────


def test_cancelling_while_the_sheet_renders_publishes_nothing(
    window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "study_report.pdf"
    monkeypatch.setattr(worker_module, "render_report", _slow_render(0.4))
    outcomes: list[tuple[str, str]] = []
    job = _job(window, target, outcomes)

    QTimer.singleShot(50, job.cancel)
    job.run()

    # The dialog closes at the cancel click, the worker keeps rendering for a
    # moment: the outcome (and the proof that nothing was written) arrives on the
    # next event-loop turns, exactly as it does in the window.
    deadline = time.time() + 3
    while time.time() < deadline and not outcomes:
        QApplication.processEvents()
        time.sleep(0.02)

    assert outcomes == [(PDF_EXPORT_CANCELLED, "")]
    assert not target.exists()


def test_cancelling_before_the_run_publishes_nothing(window, tmp_path: Path) -> None:
    target = tmp_path / "study_report.pdf"
    outcomes: list[tuple[str, str]] = []
    job = _job(window, target, outcomes)

    job.cancel()
    job.run()

    assert outcomes == [(PDF_EXPORT_CANCELLED, "")]
    assert not target.exists()


# ── failures ─────────────────────────────────────────────────────────


def test_a_render_failure_is_reported_as_a_stable_code(window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from echo_personal_tool.application.report_export import ReportExportError

    def _render(document: object, *, font_size: int = 10) -> SimpleNamespace:
        raise ReportExportError("pdf_export_failed")

    monkeypatch.setattr(worker_module, "render_report", _render)
    outcomes: list[tuple[str, str]] = []
    job = _job(window, tmp_path / "study.pdf", outcomes)

    job.run()

    assert outcomes == [(PDF_EXPORT_FAILED, "")]
    assert not (tmp_path / "study.pdf").exists()


def test_the_outcome_is_reported_only_once(window, tmp_path: Path) -> None:
    outcomes: list[tuple[str, str]] = []
    job = _job(window, tmp_path / "study.pdf", outcomes)

    job.run()
    job._on_cancelled()  # noqa: SLF001 - a late signal after the outcome

    assert outcomes == [(PDF_EXPORT_FINISHED, "study.pdf")]
