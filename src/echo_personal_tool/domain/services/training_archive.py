"""Stable tool/phase mapping and lossless partial measurement annotations."""

from __future__ import annotations

from dataclasses import asdict

import numpy as np

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.training_archive import ArchiveContext, ArchiveSample

CHAMBERS = frozenset({"LV", "LA", "RV", "RA"})
IDENTITY_TRANSFORM = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def phase_semantics(chamber: str, phase: str) -> str:
    """Existing atrial ES tools measure maximal volume, not atrial systole."""
    if phase not in {"ED", "ES"}:
        return "unspecified"
    if chamber in {"LA", "RA"}:
        return {"ES": "atrial_maximum", "ED": "atrial_minimum"}[phase]
    return {"ED": "ventricular_end_diastole", "ES": "ventricular_end_systole"}[phase]


def atlas_phase(semantics: str) -> str:
    """Explicit mapping to the atlas's GLOBAL ventricular ED/ES convention."""
    phases = {
        "ventricular_end_diastole": "ED",
        "ventricular_end_systole": "ES",
        "atrial_maximum": "ES",
        "atrial_minimum": "ED",
    }
    if semantics not in phases:
        raise ValueError("unspecified archive phase cannot train an ED/ES atlas")
    return phases[semantics]


def measurement_slot(contour: Contour) -> str:
    """Same replacement identity as study session chamber contours, across frames."""
    return "|".join((contour.chamber, contour.view, contour.phase))


def make_archive_sample(
    contour: Contour,
    pixels: np.ndarray,
    context: ArchiveContext,
    sample_id: str,
) -> ArchiveSample:
    """Use source-grid pixels and coordinates, never a viewport screenshot/crop."""
    if contour.chamber not in CHAMBERS or contour.review_pending or contour.frame_index is None:
        raise ValueError("not an accepted chamber contour")
    image = np.asarray(pixels)
    points = np.asarray(contour.points, dtype=np.float64)
    if (
        image.ndim not in {2, 3}
        or image.dtype.kind not in "uif"
        or image.nbytes > 128 * 1024**2
        or min(image.shape[:2]) < 2
        or max(image.shape[:2]) > 8192
        or not np.isfinite(image).all()
        or (image.ndim == 3 and image.shape[2] not in {1, 3, 4})
    ):
        raise ValueError("invalid source frame")
    if (
        points.ndim != 2
        or points.shape[1] != 2
        or not 3 <= len(points) <= 10000
        or not np.isfinite(points).all()
        or contour.frame_index < 0
        or len(np.unique(points, axis=0)) < 3
    ):
        raise ValueError("incomplete contour")
    if np.any(points < 0) or np.any(points > [image.shape[1] - 1, image.shape[0] - 1]):
        raise ValueError("contour is not in the source frame grid")
    if contour.source not in {"manual", "model", "ai", "ste_auto"}:
        raise ValueError("unknown contour origin")
    if contour.geometry_kind not in {"trace", "landmark_prior"}:
        raise ValueError("unknown geometry kind")
    for landmark in (contour.mitral_annulus, contour.apex_landmark):
        if landmark is not None and not np.isfinite(np.asarray(landmark, dtype=float)).all():
            raise ValueError("invalid landmarks")
    automatic = contour.auto_generated or contour.source != "manual"
    origin = "AUTO_EDITED" if contour.auto_edited else "AUTO_ACCEPTED"
    metadata: dict[str, object] = {
        **asdict(context),
        "schema_version": 1,
        "sample_id": sample_id,
        "chamber": contour.chamber,
        "view": contour.view,
        "phase": contour.phase,
        "phase_mapping_version": 1,
        "phase_semantics": phase_semantics(contour.chamber, contour.phase),
        "tool_id": f"chamber_{'open_arc' if contour.is_open_arc else 'polygon'}:{contour.chamber}",
        "measurement_id": context.measurement_key or sample_id,
        "measurement_revision": contour.revision,
        "frame_index": contour.frame_index,
        "points": points.tolist(),
        "mitral_annulus": contour.mitral_annulus,
        "apex_landmark": contour.apex_landmark,
        "origin": origin if automatic else "MANUAL",
        "source": contour.source,
        "geometry_kind": contour.geometry_kind,
        "source_to_saved": IDENTITY_TRANSFORM,
        "frame_shape": list(image.shape),
        "partial_annotation": True,
        "privacy": "LOCAL_NOT_ANONYMISED_BURNED_IN_TEXT_POSSIBLE",
    }
    return ArchiveSample(sample_id, metadata, np.ascontiguousarray(image).copy())
