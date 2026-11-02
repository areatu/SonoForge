"""Background report export (S3-04, #313).

The contract of :class:`ReportExportWorker`: the PDF is rendered off the UI
thread, published atomically, and the UI only ever receives a path or a stable
code. Cancellation wins over publishing — a cancelled export writes no file.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.report_export import ReportExportError
from echo_personal_tool.application.workers import report_export_worker as worker_module
from echo_personal_tool.application.workers.report_export_worker import (
    REPORT_EXPORT_FAILURE_CODE,
    ReportExportSignals,
    ReportExportWorker,
)

UID = "1.2.840.113619.2.55.3.1234567890.77"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


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


def _fake_render(pdf: bytes = b"%PDF-1.7 fake report") -> SimpleNamespace:
    return SimpleNamespace(pdf=pdf, anchors={})


def _record(worker: ReportExportWorker) -> dict[str, list[object]]:
    seen: dict[str, list[object]] = {"finished": [], "failed": [], "cancelled": []}
    worker.signals.finished.connect(seen["finished"].append)
    worker.signals.failed.connect(seen["failed"].append)
    worker.signals.cancelled.connect(lambda: seen["cancelled"].append(True))
    return seen


# ── signals and construction ─────────────────────────────────────────


class TestConstruction:
    def test_exposes_the_three_outcomes(self) -> None:
        signals = ReportExportSignals()
        for name in ("finished", "failed", "cancelled"):
            assert hasattr(signals, name)

    def test_keeps_the_destination_and_the_font_size(self, tmp_path: Path) -> None:
        worker = ReportExportWorker(_document(), tmp_path / "out.pdf", font_size=13)

        assert worker.dest_path == tmp_path / "out.pdf"
        assert worker._font_size == 13  # noqa: SLF001 - the worker forwards it
        assert worker.is_cancelled is False
        assert worker.autoDelete() is True

    def test_cancel_is_idempotent(self, tmp_path: Path) -> None:
        worker = ReportExportWorker(_document(), tmp_path / "out.pdf")

        worker.cancel()
        worker.cancel()

        assert worker.is_cancelled is True


# ── the happy path ───────────────────────────────────────────────────


def test_a_real_document_is_rendered_and_written(tmp_path: Path) -> None:
    target = tmp_path / "study_report.pdf"
    worker = ReportExportWorker(_document(), target)
    seen = _record(worker)

    worker.run()

    assert seen["failed"] == [] and seen["cancelled"] == []
    assert seen["finished"] == [str(target)]
    assert target.read_bytes().startswith(b"%PDF-")


def test_the_font_size_reaches_the_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _render(document: object, *, font_size: int = 10) -> SimpleNamespace:
        captured["font_size"] = font_size
        return _fake_render()

    monkeypatch.setattr(worker_module, "render_report", _render)
    worker = ReportExportWorker(_document(), tmp_path / "out.pdf", font_size=12)

    worker.run()

    assert captured["font_size"] == 12
    assert (tmp_path / "out.pdf").read_bytes() == b"%PDF-1.7 fake report"


# ── cancellation ─────────────────────────────────────────────────────


def test_cancelled_before_the_run_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "out.pdf"
    worker = ReportExportWorker(_document(), target)
    seen = _record(worker)

    worker.cancel()
    worker.run()

    assert seen["cancelled"] == [True]
    assert seen["finished"] == [] and seen["failed"] == []
    assert not target.exists()


def test_a_cancel_during_rendering_never_publishes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "out.pdf"
    worker = ReportExportWorker(_document(), target)

    def _render(document: object, *, font_size: int = 10) -> SimpleNamespace:
        worker.cancel()  # the user presses «Отмена» while the sheet renders
        return _fake_render()

    monkeypatch.setattr(worker_module, "render_report", _render)
    seen = _record(worker)

    worker.run()

    assert seen["cancelled"] == [True]
    assert seen["finished"] == []
    assert not target.exists()


# ── failures stay codes ──────────────────────────────────────────────


def test_a_render_failure_emits_the_stable_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _render(document: object, *, font_size: int = 10) -> SimpleNamespace:
        raise ReportExportError("pdf_export_failed")

    monkeypatch.setattr(worker_module, "render_report", _render)
    worker = ReportExportWorker(_document(), tmp_path / "out.pdf")
    seen = _record(worker)

    worker.run()

    assert seen["failed"] == [REPORT_EXPORT_FAILURE_CODE]
    assert seen["finished"] == []
    assert not (tmp_path / "out.pdf").exists()


def test_an_unexpected_error_never_leaks_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _render(document: object, *, font_size: int = 10) -> SimpleNamespace:
        raise RuntimeError("/home/clinic/PHI_PATIENT.dcm is unreadable")

    monkeypatch.setattr(worker_module, "render_report", _render)
    worker = ReportExportWorker(_document(), tmp_path / "out.pdf")
    seen = _record(worker)

    worker.run()

    assert seen["failed"] == [REPORT_EXPORT_FAILURE_CODE]
    assert "PHI" not in str(seen["failed"])
    assert "/home" not in str(seen["failed"])


def test_a_publish_failure_emits_the_stable_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _publish(pdf: bytes, output_path: Path) -> Path:
        raise ReportExportError("pdf_export_failed")

    monkeypatch.setattr(worker_module, "publish_report_pdf", _publish)
    worker = ReportExportWorker(_document(), tmp_path / "out.pdf")
    seen = _record(worker)

    worker.run()

    assert seen["failed"] == [REPORT_EXPORT_FAILURE_CODE]
    assert seen["finished"] == []


def test_an_existing_report_survives_a_failed_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "study.pdf"
    target.write_bytes(b"%PDF-1.7 previous report")

    def _publish(pdf: bytes, output_path: Path) -> Path:
        raise ReportExportError("pdf_export_failed")

    monkeypatch.setattr(worker_module, "publish_report_pdf", _publish)
    worker = ReportExportWorker(_document(), target)

    worker.run()

    assert target.read_bytes() == b"%PDF-1.7 previous report"
