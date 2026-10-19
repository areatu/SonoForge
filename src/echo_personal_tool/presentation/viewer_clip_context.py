"""Thin viewer adapter for the protocol projection (closes TP-3 PR-2b debt).

The protocol projection needs to know which contexts the *open clip* offers so a
step of a different mode (``cw`` while a 2D clip is open) becomes ``locked`` with
a reason (spec §4.3/§6.2).  That knowledge belongs to the viewer, but
``ViewerWidget`` must not grow a second, protocol-shaped state — QH-3 will own
the tool hooks (spec §9 «Согласование с QH-3»).  Until then this module is the
thin adapter: it reads what the viewer already computes and returns a plain
``frozenset``/``str``, so the caller can feed ``build_study_projection`` without
the viewer knowing about protocols.

The clip's projection label (``clip_view``: ``A4C`` / ``A2C`` / ``PLAX``) has no
source in the current build — DICOM ``ViewName`` is not read and no other module
keeps it.  The adapter therefore returns ``""`` (unknown), which locks nothing
(``domain.protocols.step_lock_reason``): a real source arrives with QH-3 or a
DICOM slice and only has to implement ``current_clip_view()`` to be picked up.
"""

from __future__ import annotations

from typing import Any

from echo_personal_tool.domain.measurement_catalog import (
    CTX_2D,
    CTX_M,
    DOPPLER_CONTEXTS,
)

#: Fallback when the viewer reports Doppler but not *which* Doppler: an unknown
#: mode must not lock the step (spec: a lock needs knowledge of the problem).
UNKNOWN_DOPPLER: frozenset[str] = frozenset()


def clip_modes(viewer: Any, *, mmode_active: bool = False) -> frozenset[str]:
    """Contexts of the open clip: ``{2d}``, ``{m}`` or ``{pw/cw/tdi}``.

    ``mmode_active`` comes from the window (the M-mode widget is not the viewer's
    state).  An unknown Doppler mode yields an empty set — «nothing known,
    nothing blocked».
    """
    if mmode_active:
        return frozenset({CTX_M})
    if not _is_doppler(viewer):
        return frozenset({CTX_2D})
    mode = _resolved_mode(viewer)
    if mode in DOPPLER_CONTEXTS:
        return frozenset({mode})
    return UNKNOWN_DOPPLER


def clip_view(viewer: Any) -> str:
    """Projection label of the open clip, or ``""`` when it is unknown.

    A future source only has to expose ``current_clip_view()`` on the viewer; the
    adapter stays a duck-typed read and adds no state to ``ViewerWidget``.
    """
    reader = getattr(viewer, "current_clip_view", None)
    if not callable(reader):
        return ""
    try:
        return (reader() or "").strip().upper()
    except Exception:  # noqa: BLE001 - a viewer hiccup must not break the projection
        return ""


def _is_doppler(viewer: Any) -> bool:
    reader = getattr(viewer, "is_doppler_context", None)
    return bool(reader()) if callable(reader) else False


def _resolved_mode(viewer: Any) -> str:
    reader = getattr(viewer, "resolved_doppler_mode", None)
    if not callable(reader):
        return ""
    mode = reader()
    return (mode or "").strip().lower()
