"""Versioned numerical train/serve contract for ML.3; no neural runtime or I/O."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.view_recognition import TTE_STANDARD_VIEWS
from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel, build_cardiac_atlas
from echo_personal_tool.domain.services.segment_roi import detect_view_sector_crop_box
from echo_personal_tool.domain.services.segmentation_preprocess import (
    mask_burned_ecg_for_segmentation,
    prepare_segmentation_input,
)
from echo_personal_tool.domain.services.segmentation_service import EchoNetCropTransform

TEMPLATE_SCHEMA = 1
TEMPLATE_VIEWS = TTE_STANDARD_VIEWS
TEMPLATE_LANDMARKS = (
    "MV_septal",
    "MV_lateral",
    "TV_septal",
    "TV_lateral",
    "crux",
    "LV_apex",
    "RV_apex",
    "LA_roof",
    "Ao_root",
)
MAX_TEMPLATE_NODES = 128
MAX_TEMPLATE_MODES = 16
TEMPLATE_OUTPUTS = (
    "heatmaps",
    "visibility",
    "view_logits",
    "view_cosines",
    "pose",
    "coefficients",
    "offsets",
    "phase_logits",
)


@dataclass(frozen=True)
class TemplatePrediction:
    view: str
    confidence: float
    contours: tuple[Contour, ...] = ()
    landmarks: Mapping[str, tuple[float, float]] | None = None
    reject_reason: str | None = None


def default_atlases() -> dict[str, CoupledShapeModel]:
    return {view: build_cardiac_atlas("A4C" if view == "SUBCOSTAL" else view) for view in TEMPLATE_VIEWS}


def validate_atlases(atlases: Mapping[str, CoupledShapeModel]) -> None:
    if set(atlases) != set(TEMPLATE_VIEWS):
        raise ValueError("atlas bank must contain exactly the template view vocabulary")
    for view, model in atlases.items():
        expected = "A4C" if view == "SUBCOSTAL" else view
        if (
            model.view != expected
            or len(model.mean_ed) > MAX_TEMPLATE_NODES
            or len(model.eigenvalues) > MAX_TEMPLATE_MODES
        ):
            raise ValueError("incompatible atlas bank")


def node_normals(model: CoupledShapeModel) -> np.ndarray:
    """One displacement per shared node; no independent LV/RV septal copies."""
    normals = np.zeros_like(model.mean_ed)
    for name in ("LV", "LA", "RV", "RA"):
        ids = list(model.structures.get(name, ()))
        if not ids:
            continue
        arc = model.mean_ed[ids]
        tangent = np.roll(arc, -1, axis=0) - np.roll(arc, 1, axis=0)
        normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-8)
        normals[ids] += normal
    return np.asarray(normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-8))


def prepare_template_input(frame: np.ndarray, *, input_size: int = 224) -> tuple[np.ndarray, EchoNetCropTransform]:
    """One canonical path in both training/serving: ECG suppression, sector ROI, I/Y/X."""
    if input_size < 64 or input_size > 512 or input_size % 32:
        raise ValueError("template input size must be 64..512 divisible by 32")
    if frame.ndim not in (2, 3) or min(frame.shape[:2]) < 16 or not np.isfinite(frame).all():
        raise ValueError("invalid input frame")
    cleaned = mask_burned_ecg_for_segmentation(frame)
    gray = np.mean(cleaned[..., :3], axis=2) if cleaned.ndim == 3 else cleaned.astype(float)
    scaled = (gray - gray.min()) / max(float(np.ptp(gray)), 1e-6)
    y0, x0, y1, x1 = detect_view_sector_crop_box([scaled])
    tensor, transform = prepare_segmentation_input(
        gray, roi_xyxy=(x0, y0, x1, y1), crop_mode="full_roi", target_size=input_size
    )
    yy, xx = np.meshgrid(np.linspace(-1, 1, input_size), np.linspace(-1, 1, input_size), indexing="ij")
    tensor[0, 1], tensor[0, 2] = yy, xx
    return tensor, transform


def points_to_crop(points: np.ndarray, transform: EchoNetCropTransform) -> np.ndarray:
    return np.asarray((points - [transform.crop_x0, transform.crop_y0]) / [transform.crop_width, transform.crop_height])


def points_from_crop(points: np.ndarray, transform: EchoNetCropTransform) -> np.ndarray:
    return np.asarray(points * [transform.crop_width, transform.crop_height] + [transform.crop_x0, transform.crop_y0])
