"""Bounded validation of persisted IMT geometry/statistics (#558).

Image evidence cannot be re-established from JSON. These checks establish
internal consistency, NOT clinical validity or freshness against a live frame.
"""

from __future__ import annotations

from math import isclose, isfinite

import numpy as np

from echo_personal_tool.domain.models.imt import ImtDraft, ImtRefusal
from echo_personal_tool.domain.services.imt_geometry import measure_boundaries

MAX_IMT_MEASUREMENTS = 64


def imt_key(draft: ImtDraft) -> tuple[str, int, str, str]:
    source = draft.source
    return source.instance_uid, source.frame_index, source.side, source.segment


def validate_imt(draft: ImtDraft) -> None:
    """Reject forged statistics, invalid normal indices and unbounded payloads."""
    if draft.method != "research_imt_dp_v1" or type(draft.revision) is not int or not 0 <= draft.revision <= 10**9:
        raise ImtRefusal("invalid_imt_record")
    if (
        type(draft.confirmed) is not bool
        or type(draft.attempted_samples) is not int
        or not 8 <= draft.attempted_samples <= 1024
    ):
        raise ImtRefusal("invalid_imt_record")
    if any(len(v) > 256 for v in (draft.source.study_uid, draft.source.instance_uid, draft.source.phase)):
        raise ImtRefusal("invalid_imt_record")
    indices, distances = draft.accepted_sample_indices, draft.distances_mm
    if not distances or len(distances) > 1024 or len(indices) != len(distances):
        raise ImtRefusal("invalid_imt_record")
    if any(type(i) is not int for i in indices) or tuple(sorted(set(indices))) != indices:
        raise ImtRefusal("invalid_imt_record")
    if not all(isfinite(v) and v > 0 for v in distances) or draft.coverage < draft.policy.min_coverage:
        raise ImtRefusal("invalid_imt_record")
    x0, y0, x1, y1 = draft.source.roi
    geometric = measure_boundaries(
        draft.source, draft.policy, draft.lumen_intima, draft.media_adventitia, np.ones((y1 - y0, x1 - x0))
    )
    allowed = dict(zip(geometric.accepted_sample_indices, geometric.distances_mm, strict=True))
    if geometric.attempted_samples != draft.attempted_samples:
        raise ImtRefusal("invalid_imt_record")
    if any(
        i not in allowed or not isclose(d, allowed[i], rel_tol=1e-7, abs_tol=1e-8)
        for i, d in zip(indices, distances, strict=True)
    ):
        raise ImtRefusal("invalid_imt_record")
    expected = (np.mean(distances), np.max(distances), np.std(distances), geometric.sampled_length_mm)
    actual = (draft.mean_mm, draft.max_mm, draft.sd_mm, draft.sampled_length_mm)
    if not all(
        isfinite(a) and isclose(a, e, rel_tol=1e-7, abs_tol=1e-8) for a, e in zip(actual, expected, strict=True)
    ):
        raise ImtRefusal("invalid_imt_record")
