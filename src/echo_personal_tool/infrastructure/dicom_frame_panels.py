"""Load frame panel layout from DICOM files."""

from __future__ import annotations

import logging
from pathlib import Path

import pydicom

from echo_personal_tool.domain.models.frame_panels import FramePanelLayout
from echo_personal_tool.domain.services.frame_panel_parser import parse_panels_from_dataset
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)


def try_parse_from_path(path: Path) -> FramePanelLayout | None:
    try:
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    except Exception as exc:  # noqa: BLE001 - an unreadable file has no panel layout
        log_boundary_failure(logger, "frame_panels.read", exc, code="unreadable", level=logging.DEBUG)
        return None
    return parse_panels_from_dataset(dataset)
