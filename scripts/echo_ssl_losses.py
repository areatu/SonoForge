"""Differentiable ML.4 mirrors; imports remain torch-free until called."""

from __future__ import annotations

from echo_personal_tool.domain.services.echo_ssl_objectives import cycle_triplets, trusted_cycles


def warp_loss(predicted, target, weights):
    import torch

    target = torch.as_tensor(target, dtype=predicted.dtype, device=predicted.device)
    weights = torch.as_tensor(weights, dtype=predicted.dtype, device=predicted.device)
    if predicted.shape != target.shape or predicted.shape[-1:] != (2,) or weights.shape != predicted.shape[:-1]:
        raise ValueError("incompatible warp arrays")
    if not bool(torch.isfinite(weights).all()) or bool(((weights < 0) | (weights > 1)).any()):
        raise ValueError("invalid warp weights")
    use = weights > 0
    if not bool(use.any()):
        return torch.nan_to_num(predicted).mul(0).sum()
    if not bool(torch.isfinite(predicted[use]).all() and torch.isfinite(target[use]).all()):
        raise ValueError("nonfinite observed warp")
    return (torch.linalg.vector_norm(predicted[use] - target[use], dim=-1) * weights[use]).sum() / weights[use].sum()


def physiology_loss(areas, field, *, landmarks=None, max_speed_per_s=3.0, max_acceleration_per_s2=30.0):
    import torch

    # A differentiable zero also means no accidental gradients on arrhythmia.
    zero = sum(
        (torch.nan_to_num(values).mul(0).sum() for values in areas.values()),
        torch.nan_to_num(landmarks).mul(0).sum() if landmarks is not None else torch.tensor(0.0),
    )
    terms = {"ventricles": zero, "la_reservoir": zero, "landmark_motion": zero}
    cycles = trusted_cycles(field)
    if not cycles:
        return terms
    for chamber, values in areas.items():
        for c in cycles:
            segment = values[c.ed : c.end]
            normalized = segment / segment.mean().clamp(min=1e-8)
            signed = -normalized if chamber == "LA" else normalized
            es = c.es - c.ed
            order = torch.relu(0.01 - (signed[0] - signed[es]))
            extrema = torch.relu(signed - signed[0]).mean() + torch.relu(signed[es] - signed).mean()
            monotonic = torch.relu(signed[1 : es + 1] - signed[:es]).mean()
            key = "la_reservoir" if chamber == "LA" else "ventricles"
            terms[key] = terms[key] + (order + extrema + monotonic) / len(cycles)
    if landmarks is not None and field.frame_time_ms is not None and field.frame_time_ms > 0:
        dt = field.frame_time_ms / 1000
        for c in cycles:
            segment = landmarks[c.ed : c.end]
            speed = torch.linalg.vector_norm(segment[1:] - segment[:-1], dim=-1) / dt
            acceleration = torch.linalg.vector_norm(segment[2:] - 2 * segment[1:-1] + segment[:-2], dim=-1) / dt**2
            penalty = torch.relu(speed / max_speed_per_s - 1).mean()
            if acceleration.numel():
                penalty = penalty + torch.relu(acceleration / max_acceleration_per_s2 - 1).mean()
                penalty = penalty + 0.01 * (acceleration / max_acceleration_per_s2).square().mean()
            terms["landmark_motion"] = terms["landmark_motion"] + penalty / len(cycles)
    return terms


def mesh_areas(points, atlas):
    areas = {}
    for chamber in ("LV", "LA", "RV"):
        ids = atlas.structures.get(chamber)
        if not ids:
            continue
        arc = points[:, list(ids)]
        following = arc.roll(-1, dims=1)
        areas[chamber] = (arc[..., 0] * following[..., 1] - arc[..., 1] * following[..., 0]).sum(-1).abs() / 2
    return areas


def cycle_prototype_loss(student_cosines, teacher_cosines, field):
    import torch
    from torch.nn import functional as f

    triplets = cycle_triplets(field)
    if len(triplets) < 2:
        return student_cosines.sum() * 0
    anchors = torch.stack([student_cosines[list(t)].mean(0) for t in triplets])
    positives = torch.stack([teacher_cosines[list(t)].mean(0) for t in triplets]).detach().roll(1, dims=0)
    return (1 - f.cosine_similarity(anchors, positives, dim=-1)).clamp(min=0).mean()


def update_ema(teacher, student, decay):
    import torch

    if not 0 <= decay < 1:
        raise ValueError("invalid EMA decay")
    with torch.no_grad():
        for target, source in zip(teacher.parameters(), student.parameters(), strict=True):
            target.mul_(decay).add_(source, alpha=1 - decay)
        for target, source in zip(teacher.buffers(), student.buffers(), strict=True):
            if target.is_floating_point():
                target.mul_(decay).add_(source, alpha=1 - decay)
            else:
                target.copy_(source)
