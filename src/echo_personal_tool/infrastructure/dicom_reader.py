"""DICOM pixel reader implementation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.infrastructure.dicom_metadata_mapper import map_instance_metadata
from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session


class DicomReaderImpl:
    """Infrastructure implementation of IDicomReader."""

    def read_metadata(self, path: Path) -> InstanceMetadata:
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        return map_instance_metadata(dataset, path=path)

    def read_pixels(self, path: Path, frame_index: int = 0) -> np.ndarray:
        session = get_thread_dicom_session()
        session.open(path)
        if session.frame_count == 0:
            session.decode_all_frames()
        return session.read_frame(frame_index)
