"""Background worker that writes de-identified DICOM instances to a folder.

The download dialog first pulls the selected series into the Orthanc cache and
then has to put them somewhere on disk.  Before this worker existed that step
was a byte copy, which is exactly what leaked: the cache holds the raw instance
with the real ``PatientName`` and the burned-in header.

The worker walks a ``(source, destination)`` plan (built by the dialog, so the
directory layout stays short-name based), de-identifies each file, and reports
progress plus a PHI-free summary.  Failures are per file: one unreadable
instance must not lose the rest of the study.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.dicom_deidentifier import (
    DeidentificationOptions,
    deidentify_file,
)

logger = logging.getLogger(__name__)


def _export_root(destinations: list[Path]) -> Path:
    """The folder the export was written under (informational).

    The plan uses ``<target>/Instance/<study>/<file>``, so the deepest common
    parent of the destinations is that ``Instance`` folder.  It is reported for
    the log and the summary; the dialog opens the folder it was given and does
    not depend on this value.
    """
    if not destinations:
        return Path(".")
    root = destinations[0].parent
    for destination in destinations[1:]:
        while root != destination.parent and root not in destination.parent.parents:
            if root == root.parent:  # a filesystem root, nothing left to climb
                return root
            root = root.parent
    return root


@dataclass(frozen=True)
class DeidentificationSummary:
    """Counts and PHI-free notes for the finished export."""

    #: Folder the files were written under (deepest common parent of the plan).
    target_dir: Path
    exported: int = 0
    failed: int = 0
    unverified: int = 0
    #: One line per file, containing file names and field names only.
    lines: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    cancelled: bool = False
    mask_bands: tuple[tuple[int, int], ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.unverified == 0 and not self.cancelled


class DicomDeidentifySignals(QObject):
    progress = Signal(int, int)  # current, total
    finished = Signal(object)  # DeidentificationSummary
    failed = Signal(str)


class DicomDeidentifyWorker(QRunnable):
    """De-identify every ``(source, destination)`` pair of the plan."""

    def __init__(
        self,
        plan: list[tuple[Path, Path]],
        options: DeidentificationOptions,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._plan = list(plan)
        self._options = options
        self._cancelled = False
        self.signals = DicomDeidentifySignals()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        """Ask the worker to stop after the file it is working on."""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        target = _export_root([destination for _source, destination in self._plan])
        exported = 0
        failed = 0
        unverified = 0
        lines: list[str] = []
        failures: list[str] = []
        bands: list[tuple[int, int]] = []
        total = len(self._plan)

        for index, (source, destination) in enumerate(self._plan, start=1):
            if self._cancelled:
                break
            try:
                result = deidentify_file(source, destination, self._options)
            except Exception as exc:  # noqa: BLE001 - report per file, keep going
                logger.exception("De-identified export failed for %s", source)
                failed += 1
                failures.append(f"{source.name}: {type(exc).__name__}")
            else:
                exported += 1
                if not result.verified:
                    unverified += 1
                lines.extend(result.report_lines())
                if result.pixels.band is not None and result.pixels.band not in bands:
                    bands.append(result.pixels.band)
            self.signals.progress.emit(index, total)

        summary = DeidentificationSummary(
            target_dir=target,
            exported=exported,
            failed=failed,
            unverified=unverified,
            lines=tuple(lines),
            failures=tuple(failures),
            cancelled=self._cancelled,
            mask_bands=tuple(bands),
        )
        self.signals.finished.emit(summary)
