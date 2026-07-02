"""Helpers for collecting local DICOM payloads before upload."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.domain.models import StudyMetadata


def collect_dicom_bytes(studies: list[StudyMetadata]) -> list[bytes]:
    """Read raw DICOM file bytes from loaded studies (dicom media only)."""
    payloads: list[bytes] = []
    seen: set[Path] = set()
    for study in studies:
        for series in study.series:
            for instance in series.instances:
                if instance.media_format != "dicom" or instance.path is None:
                    continue
                path = instance.path.resolve()
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                payloads.append(path.read_bytes())
    return payloads
