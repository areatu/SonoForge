"""MagnifierController — QH-3 pilot slice.

Spec §7.1: MagnifierController owns zoom/pan/crop and transient lens state;
it never owns source identity/persistence/calculator inputs.  The lens itself
(MagnifierLens, a QWidget) stays a plain child of the viewer for lifetime
reasons — QGraphicsEffect on a native window crashes X11 (§7.3 lifecycle).

Follow-up issue 420: this controller is the *only* owner of the magnifier
state.  The pilot kept a second copy of enabled/zoom/radius/
linear-persistent (and a second copy of the lens geometry) inside the viewer,
so the two could drift apart; `ViewerWidget` now holds no magnifier state and
only translates Qt events into the calls documented below.

The controller is owner-scoped QObject with an explicit `dispose()`; it
cancels its timer/anims and hides the lens so the 50/500-cycle harness (§7.3)
sees zero live closed-owner objects.

The viewer facade only translates Qt events into Controller calls:
  wheelEvent → controller.on_wheel(delta)
  sceneMouseMoved → controller.update_loupe(scene_pos, display, view_mapping)
  key Z hold → controller.set_held(True/False)
  tool change → controller.sync_persistent(active_tool, doppler_mode)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QPoint, Signal

try:
    from shiboken6 import isValid as _shiboken_is_valid

    isValid: Callable[[object], bool] = _shiboken_is_valid
except ImportError:  # Test stubs may not provide shiboken.

    def _fallback_is_valid(obj: object) -> bool:
        return obj is not None

    isValid = _fallback_is_valid


from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.presentation.viewer.commands import CommandResult, accepted

logger = logging.getLogger(__name__)


class MagnifierController(QObject):
    """State and geometry for the offset loupe."""

    # Proxy so MainWindow can still listen to viewer signals if needed
    held_changed = Signal(bool)

    def __init__(
        self,
        *,
        parent: QObject | None = None,
        lens_factory: Callable[[], Any] | None = None,
        geometry_provider: Callable[[], Any] | None = None,
        cursor_provider: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._enabled = True
        self._zoom = 3.0
        self._radius_px = 70.0
        self._held = False
        self._linear_persistent = False
        self._persistent_active = False
        self._reduce_motion = False

        self._lens: Any | None = None
        self._lens_factory = lens_factory
        self._geometry_provider = geometry_provider
        self._cursor_provider = cursor_provider

        # For generation checks
        self.context: Any = None

    @property
    def lens(self) -> Any | None:
        """Transient loupe widget owned by this controller (issue 327 public seam)."""
        return self._lens

    @lens.setter
    def lens(self, value: Any | None) -> None:
        self._lens = value

    # -- configuration -------------------------------------------------------

    def configure(
        self,
        *,
        enabled: bool | None = None,
        zoom: float | None = None,
        radius_px: float | None = None,
        linear_persistent: bool | None = None,
        reduce_motion: bool | None = None,
    ) -> CommandResult:
        if zoom is not None:
            self._zoom = float(max(2.0, min(6.0, zoom)))
        if radius_px is not None:
            self._radius_px = float(radius_px)
        if reduce_motion is not None:
            self._reduce_motion = bool(reduce_motion)
        if linear_persistent is not None:
            self._linear_persistent = bool(linear_persistent)
            if not self._linear_persistent:
                self._persistent_active = False
        if enabled is not None:
            self._enabled = bool(enabled)
        # Apply to the live lens first, then honour a switch-off immediately:
        # a disabled magnifier must not leave a visible loupe behind.
        self._configure_lens()
        if not self._enabled:
            self._hide_lens(instant=True)
        return accepted()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def radius_px(self) -> float:
        return self._radius_px

    @property
    def held(self) -> bool:
        return self._held

    @property
    def linear_persistent(self) -> bool:
        return self._linear_persistent

    @property
    def persistent_active(self) -> bool:
        return self._persistent_active

    # -- lens bookkeeping ----------------------------------------------------

    def _live_lens(self) -> Any | None:
        """The lens while its C++ object is alive; a dead reference is dropped."""
        if self._lens is not None and not isValid(self._lens):
            self._lens = None
        return self._lens

    def _configure_lens(self) -> None:
        lens = self._live_lens()
        if lens is None:
            return
        try:
            lens.configure(self._zoom, self._reduce_motion)
        except RuntimeError as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            self._lens = None

    def _hide_lens(self, *, instant: bool = False) -> None:
        lens = self._live_lens()
        if lens is None:
            return
        try:
            if lens.isVisible():
                lens.hide_animated(instant=instant)
        except RuntimeError as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            self._lens = None

    # -- transient state ----------------------------------------------------

    def set_held(self, held: bool, *, cursor_scene_pos: Any | None = None) -> CommandResult:
        self._held = bool(held)
        self.held_changed.emit(self._held)
        if not self._held:
            if not self._persistent_active:
                self._hide_lens()
            return accepted(reason="released")
        if cursor_scene_pos is not None:
            # Caller supplied scene pos — update immediately
            self._update_loupe_impl(cursor_scene_pos)
        else:
            self._show_now()
        return accepted(reason="held")

    # -- loupe geometry -----------------------------------------------------

    def _ensure_lens(self) -> Any | None:
        lens = self._live_lens()
        if lens is not None:
            return lens
        if self._lens_factory is None:
            return None
        try:
            self._lens = self._lens_factory()
            if self._lens is not None:
                self._lens.configure(self._zoom, self._reduce_motion)
            return self._lens
        except (RuntimeError, TypeError, ValueError) as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            self._lens = None
            return None

    def _show_now(self) -> None:
        if self._cursor_provider is None:
            return
        try:
            scene_pos = self._cursor_provider()
        except (RuntimeError, TypeError, ValueError) as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            return
        if scene_pos is not None:
            self._update_loupe_impl(scene_pos)

    def update_loupe(self, scene_pos: Any, *, display: Any = None, view_mapping: Any = None) -> None:
        """Update loupe content; `display` is the already-masked 8-bit RGB/gray.

        When `display` is None the controller asks the geometry provider's viewer
        for its image (legacy path used by the facade).  Prefer passing display
        explicitly so the lens never touches raw DICOM.
        """
        self._update_loupe_impl(scene_pos, display=display, view_mapping=view_mapping)

    def _resolve_display(self, display: Any) -> Any:
        if display is not None or self._geometry_provider is None:
            return display
        # Legacy fallback: ask the parent viewer
        try:
            parent = self.parent()
            if parent is not None and hasattr(parent, "_image_item"):
                return parent._image_item.image
        except (AttributeError, RuntimeError, TypeError) as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
        return None

    def _resolve_mapped_point(self, scene_pos: Any, view_mapping: Any) -> Any:
        if view_mapping is not None:
            return view_mapping(scene_pos)
        if self._geometry_provider is None:
            return None
        # Try viewer._view.mapSceneToView
        try:
            parent = self.parent()
            if parent is not None and hasattr(parent, "_view"):
                return parent._view.mapSceneToView(scene_pos)
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
        return None

    def _update_loupe_impl(self, scene_pos: Any, *, display: Any = None, view_mapping: Any = None) -> None:
        if not self._enabled or not (self._held or self._persistent_active):
            self._hide_lens(instant=True)
            return
        display = self._resolve_display(display)
        if display is None:
            return
        mapped = self._resolve_mapped_point(scene_pos, view_mapping)
        if mapped is None:
            return
        lens = self._ensure_lens()
        if lens is None or not isValid(lens):
            self._lens = None
            return
        try:
            lens.set_lens_diameter(int(self._radius_px) * 2)
            lens.set_crop(np.asarray(display), float(mapped.x()), float(mapped.y()))
            # Offset left-above so the true cursor point stays visible
            from PySide6.QtGui import QCursor  # local import for test env

            cursor_global = QCursor.pos()
            # parent is ViewerWidget which maps global to local
            host: Any = self.parent()
            if host is not None and hasattr(host, "mapFromGlobal"):
                local = host.mapFromGlobal(cursor_global)
                offset = QPoint(-lens.width() + 12, -lens.height() + 16)
                pos = local + offset
                pos.setX(max(0, min(pos.x(), max(0, host.width() - lens.width()))))
                pos.setY(max(0, min(pos.y(), max(0, host.height() - lens.height()))))
                lens.move(pos)
                center = QPoint(pos.x() + lens.width() // 2, pos.y() + lens.height() // 2)
                lens.set_anchor_delta(local - center)
                if not lens.isVisible():
                    lens.show_animated()
                    lens.raise_()
                else:
                    lens.update()
        except RuntimeError as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            self._lens = None
        except (AttributeError, TypeError, ValueError) as exc:
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)

    def hide(self) -> None:
        self._held = False
        self._hide_lens()

    def notify_point_placed(self) -> None:
        """A contour/caliper point was committed — hold drops unless persistent."""
        if self._persistent_active:
            return
        self._held = False
        self._hide_lens()

    # -- persistent mode (linear calipers) ---------------------------------

    def sync_persistent(self, linear_active: bool, doppler_mode: str = "none", vessel_status: str = "none") -> None:
        allowed = self._enabled and self._linear_persistent and doppler_mode == "none" and vessel_status == "none"
        if linear_active and allowed:
            self._persistent_active = True
            self._show_now()
            return
        self._persistent_active = False
        if not self._held:
            self._hide_lens()

    # -- lifecycle ----------------------------------------------------------

    def dispose(self) -> None:
        """Idempotent — called on viewer teardown and by the lifecycle harness."""
        self._held = False
        self._persistent_active = False
        if self._lens is not None:
            try:
                if isValid(self._lens):
                    self._lens.hide()
                    # lens is a child of the viewer; viewer deletion handles it
            except RuntimeError as exc:
                log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            self._lens = None
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self.held_changed.disconnect()
            except (RuntimeError, TypeError) as exc:
                log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
