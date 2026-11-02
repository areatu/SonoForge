"""Tests for application/workers/dicom_deidentify_worker.py.

The worker is the only place that walks the export plan, so these tests keep the
worker itself honest (counts, cancel, per-file failure) with the de-identifier
stubbed: the real one is exercised end to end in ``test_dicom_deidentifier.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from echo_personal_tool.application.workers import dicom_deidentify_worker as module
from echo_personal_tool.application.workers.dicom_deidentify_worker import (
    DicomDeidentifyWorker,
    _export_root,
)
from echo_personal_tool.infrastructure.dicom_deidentifier import (
    DeidentificationOptions,
    PixelMaskOutcome,
)


@dataclass
class _Result:
    verified: bool = True
    band: tuple[int, int] | None = (0, 100)

    source: Path = Path("src.dcm")
    destination: Path = Path("dst.dcm")
    tags: object = None
    pixels: object = None
    bytes_check: object = None

    def report_lines(self) -> tuple[str, ...]:
        return (f"{self.source.name}: 2 tag(s) cleared", "pixels masked: rows 0..100")


def _plan(tmp_path: Path, count: int = 3) -> list[tuple[Path, Path]]:
    """A plan shaped like the dialog's: one short-named study folder per study."""
    return [
        (
            tmp_path / "cache" / f"IMG{index}.dcm",
            tmp_path / "out" / "Instance" / str(index) / f"abcd{index}.dcm",
        )
        for index in range(1, count + 1)
    ]


def _fake_result(verified: bool = True, band: tuple[int, int] | None = (0, 100)):
    result = _Result(verified=verified, band=band)
    result.source = Path("IMG1.dcm")
    result.tags = type("T", (), {"summary": "2 tag(s) cleared"})()
    result.pixels = PixelMaskOutcome(applied=band is not None, band=band, reason="ok")
    return result


def test_export_root_is_the_instance_folder(tmp_path: Path):
    plan = _plan(tmp_path, count=2)
    assert _export_root([destination for _source, destination in plan]) == tmp_path / "out" / "Instance"


def test_export_root_of_an_empty_plan_is_dot():
    assert _export_root([]) == Path(".")


def test_worker_exports_every_file_and_reports_progress(tmp_path: Path, monkeypatch):
    calls: list[tuple[Path, Path, DeidentificationOptions]] = []

    def fake(source: Path, destination: Path, options: DeidentificationOptions):
        calls.append((source, destination, options))
        return _fake_result()

    monkeypatch.setattr(module, "deidentify_file", fake)
    plan = _plan(tmp_path)
    options = DeidentificationOptions(mask_pixels=True, verify_pixels=True)
    worker = DicomDeidentifyWorker(plan, options)
    progress: list[tuple[int, int]] = []
    summaries: list[object] = []
    worker.signals.progress.connect(lambda current, total: progress.append((current, total)))
    worker.signals.finished.connect(summaries.append)

    worker.run()

    assert len(calls) == 3
    assert all(call[2] is options for call in calls)
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert len(summaries) == 1
    summary = summaries[0]
    assert (summary.exported, summary.failed, summary.unverified) == (3, 0, 0)
    assert summary.cancelled is False and summary.ok is True
    assert summary.target_dir == tmp_path / "out" / "Instance"
    assert summary.mask_bands == ((0, 100),)  # one band, not one per file
    assert len(summary.lines) == 6  # two lines per file


def test_one_broken_file_does_not_lose_the_study(tmp_path: Path, monkeypatch):
    def fake(source: Path, destination: Path, options: DeidentificationOptions):
        if source.name == "IMG2.dcm":
            raise FileNotFoundError("gone")
        return _fake_result()

    monkeypatch.setattr(module, "deidentify_file", fake)
    worker = DicomDeidentifyWorker(_plan(tmp_path), DeidentificationOptions())
    summaries: list[object] = []
    worker.signals.finished.connect(summaries.append)

    worker.run()

    summary = summaries[0]
    assert (summary.exported, summary.failed) == (2, 1)
    assert summary.failures == ("IMG2.dcm: FileNotFoundError",)
    assert summary.ok is False  # a failed file means the export is not clean


def test_unverified_file_is_counted_but_still_exported(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(module, "deidentify_file", lambda *args: _fake_result(verified=False))
    worker = DicomDeidentifyWorker(_plan(tmp_path, count=1), DeidentificationOptions())
    summaries: list[object] = []
    worker.signals.finished.connect(summaries.append)

    worker.run()

    summary = summaries[0]
    assert (summary.exported, summary.unverified, summary.failed) == (1, 1, 0)
    assert summary.ok is False


def test_cancel_stops_before_the_next_file(tmp_path: Path, monkeypatch):
    seen: list[str] = []

    def fake(source: Path, destination: Path, options: DeidentificationOptions):
        seen.append(source.name)
        if len(seen) == 1:
            worker.cancel()  # as the dialog does, from the GUI thread
        return _fake_result()

    monkeypatch.setattr(module, "deidentify_file", fake)
    worker = DicomDeidentifyWorker(_plan(tmp_path), DeidentificationOptions())
    summaries: list[object] = []
    worker.signals.finished.connect(summaries.append)

    worker.run()

    assert seen == ["IMG1.dcm"]  # the file in flight finishes, the rest do not start
    summary = summaries[0]
    assert summary.cancelled is True and summary.exported == 1
    assert summary.ok is False  # a cancelled export is not a clean export


def test_mask_bands_are_reported_without_a_preview(tmp_path: Path, monkeypatch):
    """Variant A (no pixels touched) reports no band at all."""
    monkeypatch.setattr(module, "deidentify_file", lambda *args: _fake_result(band=None))
    worker = DicomDeidentifyWorker(_plan(tmp_path, count=1), DeidentificationOptions(mask_pixels=False))
    summaries: list[object] = []
    worker.signals.finished.connect(summaries.append)

    worker.run()

    assert summaries[0].mask_bands == ()
