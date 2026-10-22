"""Load frame panel layout from DICOM files."""

from __future__ import annotations

from pathlib import Path

import pydicom

from echo_personal_tool.domain.models.frame_panels import FramePanelLayout
from echo_personal_tool.domain.services.frame_panel_parser import parse_panels_from_dataset


def try_parse_from_path(path: Path) -> FramePanelLayout | None:
    try:
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    except Exception:
        return None
    return parse_panels_from_dataset(dataset)
