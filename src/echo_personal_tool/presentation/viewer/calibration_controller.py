"""CalibrationController — QH-3 slice for per-source calibration.

Spec §7.1: owns validation/commit of per-source pixel/velocity/time calibration
and notifies dependents about invalidation (§5.4 matrix).  It never owns
«calibration for the last viewer» — the key is (study_uid, sop_instance_uid)
plus generation, so a source switch discards the draft and a late confirmation
cannot pollute the new source (S-02, S-03).

The controller validates the user-supplied distance/time against domain rules
(spacing_from_known_distance, calibration_from_roi_and_baseline) and emits a
typed outcome; MainWindow/Application decide whether to write to the store and
invalidate dependents.  No direct store/repository import here (pure presentation).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.presentation.viewer.commands import CommandResult, accepted, rejected
from echo_personal_tool.presentation.viewer.context import ViewerContext

logger = logging.getLogger(__name__)

CalibrationKind = str  # "depth" | "spectral" | "doppler_velocity" | "mmode_time" | "mmode_depth"


class CalibrationController(QObject):
    """Draft and commit for B-mode/Doppler/M-mode calibration."""

    # Emitted when validation succeeds (MainWindow forwards to application)
    calibration_committed = Signal(object, object)  # (kind, value)
    calibration_cancelled = Signal(object)  # reason

    # Emitted when dependents must be marked stale
    invalidation_requested = Signal(object)  # {kind, source_uid, reason}

    def __init__(
        self,
        *,
        parent: QObject | None = None,
        # Narrow injected validators/commit hooks (not the whole MainWindow):
        validate_spacing: Callable[[float, float], float | None] | None = None,
        validate_velocity: Callable[[float, float], float | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._active = False
        self._kind: CalibrationKind | None = None
        self._start_xy: tuple[float, float] | None = None
        self._end_xy: tuple[float, float] | None = None
        self._context: ViewerContext | None = None
        self._validate_spacing = validate_spacing
        self._validate_velocity = validate_velocity

    # -- context -------------------------------------------------------------

    @property
    def context(self) -> ViewerContext | None:
        return self._context

    def set_context(self, ctx: ViewerContext) -> None:
        if self._context is not None and self._context.generation != ctx.generation:
            if self._active:
                self.cancel(reason="generation_bump")
        self._context = ctx

    @property
    def active(self) -> bool:
        return self._active

    @property
    def kind(self) -> CalibrationKind | None:
        return self._kind

    # -- activation ----------------------------------------------------------

    def activate(self, kind: CalibrationKind, *, start: tuple[float, float] | None = None) -> CommandResult:
        if self._active:
            return rejected("calibration_already_active")
        self._active = True
        self._kind = kind
        self._start_xy = start
        self._end_xy = None
        return accepted(payload={"kind": kind})

    def set_end(self, end: tuple[float, float]) -> None:
        if self._active:
            self._end_xy = end

    def deactivate(self) -> CommandResult:
        if not self._active:
            return accepted(reason="no_active_calibration")
        kind = self._kind
        self._active = False
        self._kind = None
        self._start_xy = None
        self._end_xy = None
        self.calibration_cancelled.emit(kind)
        return accepted(reason="deactivated")

    def cancel(self, *, reason: str = "user_cancel") -> CommandResult:
        was = self._active
        kind = self._kind
        self._active = False
        self._kind = None
        self._start_xy = None
        self._end_xy = None
        if was:
            self.calibration_cancelled.emit(reason)
            # keep kind for debugging
            _ = kind
        return accepted(reason=reason)

    # -- commit (validation → typed outcome) --------------------------------

    def commit_with_distance(self, known_mm: float, pixel_length: float) -> CommandResult:
        """Validate known distance and emit pixel spacing."""
        if not self._active or self._kind not in (None, "depth", "mmode_depth"):
            return rejected("calibration_not_for_depth")
        if pixel_length < 1.0:
            return rejected("pixel_length_too_small")
        if known_mm <= 0:
            return rejected("known_distance_must_be_positive")
        if self._validate_spacing is not None:
            spacing = self._validate_spacing(pixel_length, known_mm)
            if spacing is None:
                return rejected("spacing_validation_failed")
            self.calibration_committed.emit(self._kind, spacing)
            # Invalidate dependents per S-03 matrix (presentation only — actual
            # invalidation lives in application `derived_freshness`)
            if self._context is not None:
                self.invalidation_requested.emit(
                    {
                        "kind": self._kind,
                        "source_uid": self._context.identity.sop_instance_uid,
                        "reason": "calibration_changed",
                    }
                )
            self._active = False
            self._kind = None
            self._start_xy = None
            self._end_xy = None
            return accepted(payload=spacing)
        # Fallback: domain helper
        from echo_personal_tool.domain.services.pixel_spacing_resolver import spacing_from_known_distance

        try:
            spacing = spacing_from_known_distance(pixel_length, known_mm)
        except (ArithmeticError, TypeError, ValueError) as exc:
            # rejection reasons cross into UI/logging; never include
            # the exception text (it may carry a path or patient identifier).
            log_boundary_failure(logger, "calibration.manual", exc, code="invalid")
            return rejected("spacing_error")
        self.calibration_committed.emit(self._kind, spacing)
        self._active = False
        self._kind = None
        return accepted(payload=spacing)

    # -- lifecycle -----------------------------------------------------------

    def dispose(self) -> None:
        import warnings

        self._active = False
        self._kind = None
        self._start_xy = None
        self._end_xy = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for sig in (self.calibration_committed, self.calibration_cancelled, self.invalidation_requested):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError) as exc:
                    log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)


__all__ = ["CalibrationController"]
