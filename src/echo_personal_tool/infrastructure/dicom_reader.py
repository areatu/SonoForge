"""DICOM pixel reader implementation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.infrastructure.dicom_metadata_mapper import map_instance_metadata


class DicomReaderImpl:
    """Infrastructure implementation of IDicomReader."""

    def read_metadata(self, path: Path) -> InstanceMetadata:
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        return map_instance_metadata(dataset, path=path)

    def read_pixels(self, path: Path, frame_index: int = 0) -> np.ndarray:
        dataset = pydicom.dcmread(path, force=True)
        pixel_array = dataset.pixel_array
        if pixel_array.ndim == 4:
            frame = pixel_array[frame_index]
        elif pixel_array.ndim == 3:
            if pixel_array.shape[0] <= pixel_array.shape[-1]:
                frame = pixel_array[frame_index]
            else:
                frame = pixel_array[..., frame_index]
        else:
            frame = pixel_array

        if frame.ndim == 3 and frame.shape[-1] in (3, 4):
            frame = frame[..., 0]
        return np.ascontiguousarray(frame, dtype=frame.dtype).copy()
