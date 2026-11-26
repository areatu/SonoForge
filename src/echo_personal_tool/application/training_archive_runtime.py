"""Composition and thin runtime bridge for the opt-in local archive."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol
from weakref import WeakKeyDictionary

import numpy as np

from echo_personal_tool import __version__
from echo_personal_tool.application.training_archive import MeasurementArchiveCapture
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.training_archive import ArchiveContext
from echo_personal_tool.domain.models.viewer_state import ViewerState

# Composition supplies the optional capability. This module never imports the
# composition root (including lazily), keeping the complete import graph acyclic.
_BINDINGS: WeakKeyDictionary[object, tuple[MeasurementArchiveCapture, Callable[[], ViewerState]]] = WeakKeyDictionary()


def bind_archive(
    controller: object, capture: MeasurementArchiveCapture | None, snapshot: Callable[[], ViewerState]
) -> None:
    if capture is None:
        _BINDINGS.pop(controller, None)
    else:
        _BINDINGS[controller] = capture, snapshot


def _binding(controller: object) -> tuple[MeasurementArchiveCapture, Callable[[], ViewerState]] | None:
    try:
        return _BINDINGS.get(controller)
    except TypeError:
        return None


def local_archive_capture(*, permitted: bool) -> MeasurementArchiveCapture | None:
    """uv run alone is NOT consent. Require two explicit environment settings.

    An absolute external directory is mandatory: never put patient pixels in
    source trees, release assets, diagnostic logs or the disposable app cache.
    Frozen/public binaries and Presenter deliberately cannot opt in yet.
    """
    import sys

    if not permitted or getattr(sys, "frozen", False) or os.environ.get("SONOFORGE_LOCAL_TRAINING_ARCHIVE") != "1":
        return None
    value = os.environ.get("SONOFORGE_LOCAL_TRAINING_ARCHIVE_DIR", "")
    configured = Path(value)
    try:
        path = configured.resolve()
        valid = configured.is_absolute() and not any((root / ".git").exists() for root in (path, *path.parents))
    except (OSError, RuntimeError):
        valid = False
    if not valid:
        logging.getLogger(__name__).warning("Local training archive disabled: external absolute directory required")
        return None
    from echo_personal_tool.infrastructure.training_archive import SqliteMeasurementArchive

    return MeasurementArchiveCapture(
        SqliteMeasurementArchive(path / "measurement-training.sqlite3"),
        lambda: logging.getLogger(__name__).warning("Local training archive skipped; clinical measurement unchanged"),
    )


def archive_state_changed(capture: MeasurementArchiveCapture, state: object) -> None:
    if not isinstance(state, ViewerState):
        return
    instance = state.instance
    capture.transition(instance.sop_instance_uid if instance else "", state.current_frame_index)


def observe_archive(
    controller: object,
    contours: Sequence[Contour],
    pixels: np.ndarray | None,
    loaded_index: int | None,
    study_uid: str,
) -> None:
    binding = _binding(controller)
    if binding is None:
        return
    capture, snapshot = binding
    state = snapshot()
    instance = state.instance
    if instance is None:
        return
    context = ArchiveContext(
        f"{instance.issuer_of_patient_id}:{instance.patient_id}" if instance.patient_id else "",
        study_uid,
        instance.series_uid,
        instance.sop_instance_uid,
        __version__,
        state.effective_pixel_spacing,
    )

    def spacing_for(contour: Contour) -> tuple[float, float] | None:
        selected = state.calibration_for_points(contour.points, frame_index=contour.frame_index)
        return selected.context.spacing if selected.context is not None else None

    capture.observe(contours, pixels, loaded_index, context, spacing_for=spacing_for)


def confirm_archive(controller: object) -> None:
    """Shared explicit apply; AI acceptance calls this after clearing pending."""
    binding = _binding(controller)
    if binding is None:
        return
    capture, snapshot = binding
    state = snapshot()
    if state.instance is not None:
        capture.confirm(state.instance.sop_instance_uid, state.current_frame_index)


class _ContourConfirmationHost(Protocol):
    def on_contours_changed(self, contours: object) -> None: ...


def complete_archive(controller: _ContourConfirmationHost, contours: Sequence[Contour]) -> None:
    """Read final post-snap geometry only when capture is enabled.

    Disabled archive must not add a second clinical recomputation per tool.
    """
    if _binding(controller) is None:
        return
    controller.on_contours_changed(list(contours))
    confirm_archive(controller)


def reset_archive(controller: object, study_uid: str) -> None:
    binding = _binding(controller)
    if binding is not None:
        binding[0].reset(study_uid)
