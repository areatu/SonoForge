"""Helpers for collecting local DICOM payloads before upload."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pydicom

from echo_personal_tool.domain.models import StudyMetadata
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.infrastructure.dicom_annotation_serializer import (
    annotate_dicom,
)

logger = logging.getLogger(__name__)


def collect_dicom_bytes(
    studies: list[StudyMetadata],
    annotations: dict[str, list[LinearMeasurement | Contour]] | None = None,
) -> list[bytes]:
    """Read DICOM file bytes and optionally inject annotations.

    Args:
        studies: List of study metadata with file paths.
        annotations: Optional dict mapping SOP Instance UID to list of
            calipers/contours to inject into the DICOM before upload.
    """
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

                # Read and optionally annotate DICOM
                ds = pydicom.dcmread(str(path), force=True)

                # Inject annotations if available for this instance
                if annotations:
                    uid = instance.sop_instance_uid or ""
                    instance_anns = annotations.get(uid, [])
                    if instance_anns:
                        calipers = [a for a in instance_anns if isinstance(a, LinearMeasurement)]
                        contours = [a for a in instance_anns if isinstance(a, Contour)]
                        ds = annotate_dicom(ds, calipers=calipers, contours=contours)
                        logger.info(
                            "Injected %d calipers, %d contours into %s",
                            len(calipers),
                            len(contours),
                            uid,
                        )

                # Serialize to bytes via BytesIO
                buf = io.BytesIO()
                ds.save_as(buf, write_like_original=False)
                payloads.append(buf.getvalue())
    return payloads
