"""Conservative patient-space partition/sort for classic CT/MR (#557).

Tolerances are numerical grouping tolerances, not clinical acceptance limits.
A sorted stack is not proof of a complete acquisition or diagnostic validity.
"""

from __future__ import annotations

from dataclasses import replace
from statistics import median

import numpy as np

from echo_personal_tool.domain.models.ctmr_stack import CtMrIndex, CtMrStack, StackFrameRef, StackIndexDiagnostic

ORIENTATION_ATOL = 1e-5
SPACING_ATOL_MM = 1e-5
POSITION_ATOL_MM = 1e-3
MAX_INDEX_FRAMES = 10_000


def _compatible(a: StackFrameRef, b: StackFrameRef) -> bool:
    fields = (
        "study_uid",
        "series_uid",
        "frame_of_reference_uid",
        "sop_class_uid",
        "modality",
        "rows",
        "columns",
        "bits_allocated",
        "bits_stored",
        "pixel_representation",
        "photometric",
        "dimension_key",
        "image_type",
    )
    if any(getattr(a, field) != getattr(b, field) for field in fields):
        return False
    ga, gb = a.geometry, b.geometry
    if ga is None or gb is None:
        return ga is gb
    return bool(
        np.allclose(ga.orientation, gb.orientation, rtol=0, atol=ORIENTATION_ATOL)
        and np.allclose(ga.pixel_spacing, gb.pixel_spacing, rtol=0, atol=SPACING_ATOL_MM)
    )


def _stack(frames: list[StackFrameRef]) -> CtMrStack:
    anchor = frames[0]
    geometry = anchor.geometry
    warnings: set[str] = set()
    if geometry is None:
        return CtMrStack(tuple(sorted(frames, key=lambda f: f.identity)), False, (), (), ("spatial_order_unverified",))
    normal = np.cross(geometry.orientation[:3], geometry.orientation[3:])
    normal /= np.linalg.norm(normal)
    locations = [(float(np.dot(f.geometry.position, normal)), f) for f in frames if f.geometry is not None]
    locations.sort(key=lambda item: (item[0], item[1].identity))
    positions = tuple(p for p, _ in locations)
    steps = tuple(b - a for a, b in zip(positions, positions[1:]))
    if any(step <= POSITION_ATOL_MM for step in steps):
        warnings.add("duplicate_positions")
    positive = [step for step in steps if step > POSITION_ATOL_MM]
    if positive:
        expected = median(positive)
        # Warn, never invent missing slices or regularise coordinates.
        if any(abs(step - expected) > max(POSITION_ATOL_MM, expected * 0.05) for step in positive):
            warnings.add("nonuniform_spacing_possible_gaps")
    origin = np.asarray(geometry.position)
    for _, frame in locations:
        assert frame.geometry is not None
        delta = np.asarray(frame.geometry.position) - origin
        if np.linalg.norm(delta - np.dot(delta, normal) * normal) > POSITION_ATOL_MM:
            warnings.add("in_plane_origin_shift")
    verified = bool(anchor.frame_of_reference_uid) and "duplicate_positions" not in warnings
    if not verified:
        warnings.add("spatial_order_unverified")
    return CtMrStack(tuple(f for _, f in locations), verified, positions, steps, tuple(sorted(warnings)))


def build_ctmr_stacks(frames: tuple[StackFrameRef, ...]) -> CtMrIndex:
    """Partition conservatively; conflicting SOP identities are quarantined.

    Equal header metadata cannot prove equal pixel bytes. Repeated SOPs keep
    one deterministic path with a visible unverified-duplicate diagnostic.
    """
    if len(frames) > MAX_INDEX_FRAMES:
        raise ValueError("stack_index_limit")
    diagnostics: list[StackIndexDiagnostic] = []
    by_sop: dict[tuple[str, int], list[StackFrameRef]] = {}
    for frame in sorted(frames, key=lambda f: str(f.path)):
        by_sop.setdefault(frame.identity, []).append(frame)
    unique = []
    for duplicates in by_sop.values():
        anchor = duplicates[0]
        conflicting = any(replace(f, path=anchor.path, file_stamp=anchor.file_stamp) != anchor for f in duplicates[1:])
        if conflicting:
            diagnostics.extend(StackIndexDiagnostic(f.path, "conflicting_sop") for f in duplicates)
            continue
        unique.append(anchor)
        diagnostics.extend(StackIndexDiagnostic(f.path, "duplicate_sop_pixels_unverified") for f in duplicates[1:])
    groups: list[list[StackFrameRef]] = []
    # Sort by identity before choosing group anchors: no input-order dependency
    # at tolerance boundaries, and filenames never choose the anatomical order.
    for frame in sorted(unique, key=lambda f: f.identity):
        for group in groups:
            if _compatible(group[0], frame):
                group.append(frame)
                break
        else:
            if len(groups) >= 256:
                raise ValueError("stack_partition_limit")
            groups.append([frame])
    stacks = tuple(_stack(group) for group in groups)
    partition_counts: dict[tuple[str, str], int] = {}
    for stack in stacks:
        f = stack.frames[0]
        key = f.study_uid, f.series_uid
        partition_counts[key] = partition_counts.get(key, 0) + 1
    stacks = tuple(
        replace(s, warnings=tuple(sorted((*s.warnings, "series_partitioned"))))
        if partition_counts[(s.frames[0].study_uid, s.frames[0].series_uid)] > 1
        else s
        for s in stacks
    )
    return CtMrIndex(stacks, tuple(diagnostics))
