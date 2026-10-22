"""Background workers for DICOM I/O."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker


class DicomLoaderWorker(FrameLoaderWorker):
    """Load a single DICOM frame on a thread pool thread."""

    def __init__(self, path: Path, frame_index: int = 0) -> None:
        super().__init__(path, frame_index=frame_index, media_format="dicom")
