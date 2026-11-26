"""Decode ML.3 numerical heads into a single topology-safe, review-only mesh."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel
from echo_personal_tool.domain.services.echo_template_contract import (
    MAX_TEMPLATE_MODES,
    MAX_TEMPLATE_NODES,
    TEMPLATE_LANDMARKS,
    TEMPLATE_OUTPUTS,
    TEMPLATE_VIEWS,
    TemplatePrediction,
    node_normals,
    points_from_crop,
)
from echo_personal_tool.domain.services.rv_segmentation_service import build_rv_auto_contour
from echo_personal_tool.domain.services.segmentation_service import EchoNetCropTransform


def validate_template_outputs(outputs: Mapping[str, np.ndarray]) -> None:
    views = len(TEMPLATE_VIEWS)
    shapes = {
        "visibility": (1, 9),
        "view_logits": (1, views),
        "view_cosines": (1, views),
        "pose": (1, views, 5),
        "coefficients": (1, views, MAX_TEMPLATE_MODES),
        "offsets": (1, views, MAX_TEMPLATE_NODES),
        "phase_logits": (1, 2),
    }
    if set(outputs) != set(TEMPLATE_OUTPUTS):
        raise ValueError("incompatible template output names")
    for name, expected in shapes.items():
        if outputs[name].shape != expected or not np.isfinite(outputs[name]).all():
            raise ValueError(f"invalid template head: {name}")
    maps = outputs["heatmaps"]
    if maps.ndim != 4 or maps.shape[:2] != (1, 9) or min(maps.shape[2:]) < 4 or not np.isfinite(maps).all():
        raise ValueError("invalid landmark heatmaps")
    if np.any(np.abs(outputs["view_cosines"]) > 1.0001):
        raise ValueError("invalid prototype cosine")


def decode_template_prediction(
    outputs: Mapping[str, np.ndarray],
    atlases: Mapping[str, CoupledShapeModel],
    transform: EchoNetCropTransform,
    frame: np.ndarray,
    *,
    phase: str,
    frame_index: int,
    pixel_spacing: tuple[float, float] | None,
    sector_mask: np.ndarray | None,
    requested_view: str | None = None,
    min_cosine: float = 0.25,
    min_confidence: float = 0.35,
    max_entropy: float = 0.88,
    refine_rv: bool = True,
) -> TemplatePrediction:
    validate_template_outputs(outputs)
    if phase not in {"ED", "ES"} or frame_index < 0:
        raise ValueError("explicit measurement ED/ES and nonnegative frame required")
    if requested_view is not None and requested_view not in TEMPLATE_VIEWS:
        raise ValueError("unsupported requested view")
    logits = outputs["view_logits"][0].astype(float)
    probabilities = np.exp(logits - logits.max())
    probabilities /= probabilities.sum()
    index = int(np.argmax(probabilities)) if requested_view is None else TEMPLATE_VIEWS.index(requested_view)
    confidence = float(probabilities[index])
    entropy = float(-np.sum(probabilities * np.log(np.maximum(probabilities, 1e-12))) / np.log(len(probabilities)))
    if requested_view is None and (
        confidence < min_confidence or entropy > max_entropy or outputs["view_cosines"][0, index] < min_cosine
    ):
        return TemplatePrediction("UNKNOWN", confidence, reject_reason="view_unknown")
    view = TEMPLATE_VIEWS[index]
    model = atlases[view]
    # Coefficients are standard deviations, bounded by the same ±3σ prior as ML.1.
    coefficients = np.clip(outputs["coefficients"][0, index, : len(model.eigenvalues)], -3, 3) * np.sqrt(
        model.eigenvalues
    )
    mesh = model.synthesize(coefficients, phase=phase)
    offsets = np.clip(outputs["offsets"][0, index, : len(mesh)], -5, 5)
    mesh = model.constrain(mesh + node_normals(model) * offsets[:, None], phase=phase)
    pose = outputs["pose"][0, index].astype(float)
    c, s = pose[2:4] / max(float(np.linalg.norm(pose[2:4])), 1e-8)
    if abs(c) + abs(s) < 1e-6:
        return TemplatePrediction(view, confidence, reject_reason="degenerate_pose")
    rotation = np.array([[c, -s], [s, c]])
    placed = mesh @ rotation.T * np.exp(np.clip(pose[4], -8, 0)) + pose[:2]
    placed = points_from_crop(placed, transform)
    if np.any(placed < 0) or np.any(placed[:, 0] >= frame.shape[1]) or np.any(placed[:, 1] >= frame.shape[0]):
        return TemplatePrediction(view, confidence, reject_reason="outside_image")
    proposals = []
    for chamber in ("LV", "LA"):
        if chamber not in model.structures:
            continue
        arc = placed[list(model.structures[chamber])]
        annulus = None if chamber in model.closed_structures else (tuple(arc[0]), tuple(arc[-1]))
        apex = tuple(placed[model.landmarks[f"{chamber}_apex"]]) if f"{chamber}_apex" in model.landmarks else None
        proposals.append(
            Contour(
                phase=phase,
                view=view,
                chamber=chamber,
                points=[tuple(p) for p in arc],
                mitral_annulus=annulus,
                apex_landmark=apex,
                num_nodes=len(arc),
                source="ai",
                frame_index=frame_index,
                review_pending=True,
            )
        )
    maps = outputs["heatmaps"][0]
    visibility = 1 / (1 + np.exp(-np.clip(outputs["visibility"][0], -40, 40)))
    landmarks = {}
    for i, name in enumerate(TEMPLATE_LANDMARKS):
        if visibility[i] < 0.5:
            continue
        y, x = np.unravel_index(int(maps[i].argmax()), maps[i].shape)
        point = points_from_crop(np.array([[x / max(maps.shape[2] - 1, 1), y / max(maps.shape[1] - 1, 1)]]), transform)[
            0
        ]
        landmarks[name] = (float(point[0]), float(point[1]))
    reason = None
    if "RV" in model.structures and view in {"A4C", "RV_A4C"}:
        arc = placed[list(model.structures["RV"])]
        rv, reason = build_rv_auto_contour(
            frame,
            arc,
            annulus=(tuple(arc[0]), tuple(arc[-1])),
            apex=tuple(placed[model.landmarks["RV_apex"]]),
            phase=phase,
            view=view,
            frame_index=frame_index,
            pixel_spacing=pixel_spacing,
            sector_mask=sector_mask,
            lv_contour=proposals[0],
            confidence=float(min(visibility[2], visibility[3], visibility[6])),
            refine=refine_rv,
        )
        if rv is not None:
            proposals.append(rv)
    return TemplatePrediction(view, confidence, tuple(proposals), landmarks, reason)
