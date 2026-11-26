"""Confirmation use-case: stage final source-grid snapshots, commit only on acceptance."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

import numpy as np

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.training_archive import (
    ArchiveContext,
    ArchiveSample,
    ArchiveWriteError,
    MeasurementArchive,
)
from echo_personal_tool.domain.services.training_archive import CHAMBERS, make_archive_sample, measurement_slot


class MeasurementArchiveCapture:
    """Shared by explicit apply and confirming frame transitions, not a UI writer.

    Only emitted complete contours enter staging; drawing/cancel states do not.
    A private pixel copy is made BEFORE navigation. A later frame never stands
    in for a missing old frame. Failure never escapes into clinical mutation.
    """

    def __init__(self, archive: MeasurementArchive, skipped: Callable[[], None]) -> None:
        self.archive = archive
        self._skipped = skipped
        self.saved_count = 0
        self.skipped_count = 0
        self.paused = False
        self.pending: dict[str, ArchiveSample] = {}
        self.location: tuple[str, int] | None = None

    def skipped(self) -> None:
        self.skipped_count += 1
        self._skipped()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if paused:
            self.pending.clear()

    def observe(
        self,
        contours: Sequence[Contour],
        pixels: np.ndarray | None,
        loaded_index: int | None,
        context: ArchiveContext,
        *,
        spacing_for: Callable[[Contour], tuple[float, float] | None] | None = None,
    ) -> None:
        if self.paused:
            return
        try:
            instance = self.archive.token("instance", context.instance_key)
            retained: set[str] = set()
            for contour in contours:
                if contour.chamber not in CHAMBERS:
                    continue
                sid = self.archive.token(
                    "measurement", f"{context.study_key}:{context.instance_key}:{measurement_slot(contour)}"
                )
                retained.add(sid)
                if contour.frame_index != loaded_index or pixels is None:
                    self.pending.pop(sid, None)
                    continue
                if contour.review_pending:
                    self.pending.pop(sid, None)
                    continue
                try:
                    local = replace(
                        self._local_context(context),
                        measurement_key=self.archive.token("measurement_id", contour.measurement_id or sid),
                        pixel_spacing_mm=spacing_for(contour) if spacing_for else context.pixel_spacing_mm,
                    )
                    sample = make_archive_sample(contour, pixels, local, sid)
                except ValueError:
                    self.pending.pop(sid, None)
                    continue
                self.pending[sid] = sample
            self.pending = {
                sid: s for sid, s in self.pending.items() if s.metadata["instance_key"] != instance or sid in retained
            }
            self.archive.exclude_missing(instance, retained)
        except (ArchiveWriteError, MemoryError):
            self.skipped()

    def _local_context(self, context: ArchiveContext) -> ArchiveContext:
        return replace(
            context,
            patient_identity_known=bool(context.patient_key),
            patient_key=self.archive.token("patient", context.patient_key or "UNKNOWN_PATIENT"),
            study_key=self.archive.token("study", context.study_key),
            series_key=self.archive.token("series", context.series_key),
            instance_key=self.archive.token("instance", context.instance_key),
        )

    def confirm(self, instance_key: str, frame_index: int) -> None:
        if self.paused:
            return
        try:
            instance = self.archive.token("instance", instance_key)
            for sid, sample in list(self.pending.items()):
                if sample.metadata["instance_key"] == instance and sample.metadata["frame_index"] == frame_index:
                    self.saved_count += int(self.archive.save(sample))
                    del self.pending[sid]
        except (ArchiveWriteError, MemoryError):
            self.skipped()

    def reset(self, study_uid: str) -> None:
        try:
            study = self.archive.token("study", study_uid)
            self.pending = {sid: s for sid, s in self.pending.items() if s.metadata["study_key"] != study}
            self.archive.exclude_study(study)
        except (ArchiveWriteError, MemoryError):
            self.skipped()

    def transition(self, instance_key: str, frame_index: int, *, same_instance: bool = True) -> None:
        target = (instance_key, frame_index)
        if self.location is not None and self.location != target:
            # A clip/study switch is NOT an implicit acceptance operation.
            if same_instance and self.location[0] == instance_key:
                self.confirm(*self.location)
            self.pending.clear()
        self.location = target
