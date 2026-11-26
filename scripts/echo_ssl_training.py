"""ML.4 teacher targets, fixed-support motion evidence and gold evaluation.

All pixels, paths and pseudo-labels remain in RAM; reports are aggregates only.
"""

from __future__ import annotations

import cv2
import numpy as np
import pydicom
from scripts.echo_template_losses import decode_torch_mesh

from echo_personal_tool.domain.services.echo_ssl_objectives import phase_shape_weights
from echo_personal_tool.domain.services.echo_ssl_tracking import track_ssl_nodes
from echo_personal_tool.domain.services.echo_template_contract import (
    TEMPLATE_VIEWS,
    points_from_crop,
    prepare_template_input,
)


def forward_clip(model, tensor, *, chunk_size=8):
    import torch

    pieces = [model(part) for part in tensor.split(chunk_size)]
    return tuple(torch.cat([p[i] for p in pieces]) for i in range(8))


def clip_geometry(outputs, bank, field, *, view=None, phase_weights=None):
    import torch

    probabilities = outputs[2].detach().softmax(-1)
    index = int(probabilities.mean(0).argmax()) if view is None else TEMPLATE_VIEWS.index(view)
    views = torch.full((len(probabilities),), index, dtype=torch.long)
    if phase_weights is None:
        weights = phase_shape_weights(field)
        learned = outputs[7].detach().softmax(-1)[:, 1]
        phase_weights = (
            learned
            if weights is None
            else torch.where(
                torch.tensor(np.isfinite(weights)), torch.tensor(np.nan_to_num(weights), dtype=torch.float32), learned
            )
        )
    mesh = decode_torch_mesh(outputs, views, torch.zeros_like(views), bank, phase_weight=phase_weights)
    return mesh, phase_weights, TEMPLATE_VIEWS[index]


def pixels_from_mesh(mesh, transforms):
    return np.stack([points_from_crop(p, t) for p, t in zip(mesh, transforms)])


def teacher_support(outputs, pixel_mesh, atlas, view, shape):
    """Reject uncertain view, invisible anchors, off-frame or broken topology."""
    probabilities = outputs[2].detach().softmax(-1).cpu().numpy()
    cosines = outputs[3].detach().cpu().numpy()
    visibility = outputs[1].detach().sigmoid().cpu().numpy()
    entropy = -np.sum(probabilities * np.log(np.maximum(probabilities, 1e-12)), axis=1) / np.log(len(TEMPLATE_VIEWS))
    index = TEMPLATE_VIEWS.index(view)
    confident = (probabilities[:, index] >= 0.35) & (cosines[:, index] >= 0.25) & (entropy <= 0.88)
    supported = np.zeros(pixel_mesh.shape[:2], bool)
    anchor_ids = {"LV": (0, 1, 5), "LA": (0, 1, 7), "RV": (2, 3, 6)}
    for frame, points in enumerate(pixel_mesh):
        actual = points[: len(atlas.mean_ed)]
        if not confident[frame] or not np.isfinite(actual).all() or atlas.violations(actual):
            continue
        for chamber in ("LV", "LA", "RV"):
            ids = list(atlas.structures.get(chamber, ()))
            if not ids or min(visibility[frame, list(anchor_ids[chamber])]) < 0.5:
                continue
            arc = actual[ids]
            if np.any(arc < 4) or np.any(arc[:, 0] >= shape[1] - 4) or np.any(arc[:, 1] >= shape[0] - 4):
                continue
            if abs(cv2.contourArea(arc.astype(np.float32))) >= 5:
                supported[frame, ids] = True
    return supported


def motion_landmark_ids(atlas, supported):
    """Only observed MV/TV and ventricular apices; absent RA must not veto LV/RV."""
    return sorted(
        {
            index
            for name, index in atlas.landmarks.items()
            if (name.startswith(("MV_", "TV_")) or name in {"LV_apex", "RV_apex"}) and supported[:, index].all()
        }
    )


def warp_pairs(gray, pixel_mesh, supported, atlas):
    """Fixed per-node support, forward/backward NCC; no bootstrap on rejected nodes."""
    positions = pixel_mesh[1:].copy()
    weights = np.zeros(positions.shape[:2])
    for t in range(len(gray) - 1):
        ids = np.flatnonzero(supported[t] & supported[t + 1])
        if not len(ids):
            continue
        warp = track_ssl_nodes(
            gray[t], gray[t + 1], pixel_mesh[t, ids], reference_sector=gray[t] > 1e-6, target_sector=gray[t + 1] > 1e-6
        )
        positions[t, ids], weights[t, ids] = warp.positions, warp.weights
    return positions, weights


def warp_to_normalized(positions, transforms):
    return np.stack(
        [(p - [t.crop_x0, t.crop_y0]) / [t.crop_width, t.crop_height] for p, t in zip(positions, transforms[1:])]
    ).astype(np.float32)


def motion_evidence(pixel_mesh, baseline_mesh, warped, weights, atlas):
    """Flow-compensated jitter on IDENTICAL baseline support before/after.

    Candidate cannot look better by lowering its confidence or dropping nodes.
    Reject nonfinite motion instead of averaging it away.
    """
    difference = (pixel_mesh[1:] - pixel_mesh[:-1]) - (warped - baseline_mesh[:-1])
    result = {}
    for chamber in ("LV", "LA", "RV"):
        ids = list(atlas.structures.get(chamber, ()))
        w = weights[:, ids]
        use = w > 0
        if np.count_nonzero(use.sum(axis=1) >= 3) < 3:
            result[chamber] = None
        elif not np.isfinite(difference[:, ids][use]).all():
            result[chamber] = float("inf")
        else:
            result[chamber] = float((np.linalg.norm(difference[:, ids][use], axis=-1) * w[use]).sum() / w[use].sum())
    return result


def evaluate_gold(model, samples, atlases, bank, input_size):
    import torch

    errors, ious = [], {c: [] for c in ("LV", "LA", "RV")}
    model.eval()
    for sample in samples:
        ds = pydicom.dcmread(sample.path)
        frames = ds.pixel_array
        frame = frames[sample.frame_index] if int(getattr(ds, "NumberOfFrames", 1)) > 1 else frames
        tensor, transform = prepare_template_input(frame, input_size=input_size)
        index = torch.tensor([TEMPLATE_VIEWS.index(sample.view)])
        with torch.no_grad():
            outputs = model(torch.from_numpy(tensor))
            mesh = decode_torch_mesh(outputs, index, torch.tensor([0 if sample.phase == "ED" else 1]), bank)[0].numpy()
        pixel = points_from_crop(mesh, transform)
        atlas = atlases[sample.view]
        for chamber, truth in sample.contours.items():
            if chamber not in ious or chamber not in atlas.structures:
                continue
            from echo_personal_tool.domain.services.cardiac_atlas_geometry import resample_arc

            ids = list(atlas.structures[chamber])
            true_nodes = (
                truth
                if len(truth) == len(ids)
                else resample_arc(truth, len(ids), closed=chamber in atlas.closed_structures)
            )
            predicted = pixel[ids]
            if not np.isfinite(predicted).all():
                raise ValueError("nonfinite gold prediction")
            errors.extend(np.linalg.norm(predicted - true_nodes, axis=-1).tolist())
            masks = []
            for points in (predicted, true_nodes):
                mask = np.zeros(frame.shape[:2], np.uint8)
                cv2.fillPoly(mask, [np.rint(points).clip(-100000, 100000).astype(np.int32)], 1)
                masks.append(mask.astype(bool))
            union = (masks[0] | masks[1]).sum()
            ious[chamber].append(float((masks[0] & masks[1]).sum() / union) if union else 0.0)
    metrics = {f"{c}_iou": float(np.mean(values)) for c, values in ious.items() if values}
    if errors:
        metrics["node_error_px"] = float(np.mean(errors))
        metrics["frames"] = float(len(samples))
    return metrics
