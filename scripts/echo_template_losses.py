"""Differentiable shared-node geometry and masked multi-task losses (optional torch)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.echo_template_contract import (
    MAX_TEMPLATE_MODES,
    MAX_TEMPLATE_NODES,
    TEMPLATE_VIEWS,
    node_normals,
    validate_atlases,
)


def atlas_bank_arrays(atlases):
    validate_atlases(atlases)
    n, k, v = MAX_TEMPLATE_NODES, MAX_TEMPLATE_MODES, len(TEMPLATE_VIEWS)
    bank = {
        "ed": np.zeros((v, n, 2), np.float32),
        "es": np.zeros((v, n, 2), np.float32),
        "modes": np.zeros((v, k, n, 2), np.float32),
        "std": np.zeros((v, k), np.float32),
        "normals": np.zeros((v, n, 2), np.float32),
    }
    pairs_by_view = []
    for j, view in enumerate(TEMPLATE_VIEWS):
        model = atlases[view]
        count, modes = len(model.mean_ed), len(model.eigenvalues)
        bank["ed"][j, :count], bank["es"][j, :count] = model.mean_ed, model.mean_es
        bank["modes"][j, :modes, :count], bank["std"][j, :modes] = model.modes, np.sqrt(model.eigenvalues)
        bank["normals"][j, :count] = node_normals(model)
        edges = set()
        for chamber in ("LV", "LA", "RV", "RA"):
            ids = model.structures.get(chamber, ())
            if ids:
                edges.update(tuple(sorted((a, b))) for a, b in zip(ids, (*ids[1:], ids[0])))
        edges = sorted(edges)
        pairs_by_view.append([(*a, *b) for i, a in enumerate(edges) for b in edges[i + 1 :] if not set(a) & set(b)])
    count = max(map(len, pairs_by_view))
    bank["pairs"] = np.zeros((v, count, 4), dtype=np.int64)
    bank["pair_mask"] = np.zeros((v, count), dtype=np.float32)
    for j, pairs in enumerate(pairs_by_view):
        bank["pairs"][j, : len(pairs)], bank["pair_mask"][j, : len(pairs)] = pairs, 1
    return bank


def decode_torch_mesh(outputs, view, phase, bank):
    import torch
    from torch.nn import functional as f

    batch = torch.arange(len(view), device=view.device)
    index = view.clamp(min=0)
    pose, coefficients, offsets = outputs[4][batch, index], outputs[5][batch, index], outputs[6][batch, index]
    mean = torch.where(phase[:, None, None] == 0, bank["ed"][index], bank["es"][index])
    mesh = mean + torch.einsum("bk,bknd->bnd", coefficients * bank["std"][index], bank["modes"][index])
    mesh = mesh + offsets[..., None] * bank["normals"][index]
    direction = f.normalize(pose[:, 2:4], dim=1, eps=1e-8)
    c, s = direction[:, 0:1], direction[:, 1:2]
    x, y = mesh[..., 0], mesh[..., 1]
    rotated = torch.stack([c * x - s * y, s * x + c * y], dim=-1)
    return rotated * pose[:, 4:5].exp()[:, None] + pose[:, None, :2]


def crossing_penalty(points, pairs, mask):
    import torch
    from torch.nn import functional as f

    batch = torch.arange(len(points), device=points.device)[:, None]
    a, b, c, d = (points[batch, pairs[..., i]] for i in range(4))

    def cross(u, v):
        return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]

    u, v = b - a, d - c
    p, q = cross(u, c - a), cross(u, d - a)
    r, s = cross(v, a - c), cross(v, b - c)
    denominator = ((u * u).sum(-1) * (v * v).sum(-1)).clamp(min=1e-8)
    score = f.relu(-p * q) * f.relu(-r * s) / denominator.square()
    return (score * mask).sum() / mask.sum().clamp(min=1)


def multitask_loss(outputs, target, bank, class_weights=None):
    import torch
    from torch.nn import functional as f

    view, phase = target["view"].long(), target["phase"].long()
    valid = view >= 0
    predicted = decode_torch_mesh(outputs, view, phase, bank)
    observed = target["node_mask"].float() * valid[:, None]
    geometry = (
        f.smooth_l1_loss(predicted, target["nodes"], reduction="none").sum(-1) * observed
    ).sum() / observed.sum().clamp(min=1)
    visible, known = target["visible"], target["visibility_mask"]
    heatmap = ((outputs[0].sigmoid() - target["heatmaps"]) ** 2 * visible[:, :, None, None]).mean()
    visibility = (
        f.binary_cross_entropy_with_logits(outputs[1], visible, reduction="none") * known
    ).sum() / known.sum().clamp(min=1)
    classification = outputs[2].sum() * 0
    phase_loss = outputs[7].sum() * 0
    if valid.any():
        ce = f.cross_entropy(outputs[2][valid], view[valid], weight=class_weights, reduction="none")
        probabilities = outputs[2][valid].softmax(-1).gather(1, view[valid, None]).squeeze(1)
        classification = (((1 - probabilities) ** 2) * ce).mean()
        phase_loss = f.cross_entropy(outputs[7][valid], phase[valid])
    if (~valid).any():
        classification = classification + f.relu(outputs[3][~valid].max(dim=1).values - 0.2).mean()
    index = view.clamp(min=0)
    topology = crossing_penalty(predicted, bank["pairs"][index], bank["pair_mask"][index] * valid[:, None])
    batch = torch.arange(len(view), device=view.device)
    prior = outputs[5][batch, index].square().mean() + outputs[6][batch, index].square().mean()
    loss = 20 * geometry + heatmap + 0.5 * visibility + classification + 0.2 * phase_loss + 5 * topology + 0.001 * prior
    return loss, {
        "geometry": geometry,
        "view": classification,
        "heatmap": heatmap,
        "visibility": visibility,
        "topology": topology,
        "prior": prior,
    }
