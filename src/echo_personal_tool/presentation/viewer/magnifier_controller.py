"""MagnifierController — QH-3 pilot slice.

Spec §7.1: MagnifierController owns zoom/pan/crop and transient lens state;
it never owns source identity/persistence/calculator inputs.  The lens itself
(MagnifierLens, a QWidget) stays a plain child of the viewer for lifetime
reasons — QGraphicsEffect on a native window crashes X11 (§7.3 lifecycle).

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

from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QPoint, Signal

try:
    from shiboken6 import isValid  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001 - test env without shiboken

    def isValid(obj: Any) -> bool:  # type: ignore[no-redef]
        return obj is not None


from echo_personal_tool.presentation.viewer.commands import CommandResult, accepted


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
        if enabled is not None:
            self._enabled = bool(enabled)
        if zoom is not None:
            self._zoom = float(max(2.0, min(6.0, zoom)))
            if self._lens is not None and isValid(self._lens):
                try:
                    self._lens.configure(self._zoom, self._reduce_motion)
                except RuntimeError:
                    self._lens = None
            if not self._enabled and self._lens is not None:
                try:
                    if isValid(self._lens) and self._lens.isVisible():
                        self._lens.hide_animated(instant=True)
                except RuntimeError:
                    pass
        if radius_px is not None:
            self._radius_px = float(radius_px)
        if linear_persistent is not None:
            self._linear_persistent = bool(linear_persistent)
            if not self._linear_persistent:
                self._persistent_active = False
        if reduce_motion is not None:
            self._reduce_motion = bool(reduce_motion)
            if self._lens is not None and isValid(self._lens):
                try:
                    self._lens.configure(self._zoom, self._reduce_motion)
                except RuntimeError:
                    self._lens = None
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

    # -- transient state ----------------------------------------------------

    def set_held(self, held: bool, *, cursor_scene_pos: Any | None = None) -> CommandResult:
        self._held = bool(held)
        self.held_changed.emit(self._held)
        if not self._held:
            if not self._persistent_active and self._lens is not None and isValid(self._lens):
                try:
                    if self._lens.isVisible():
                        self._lens.hide_animated()
                except RuntimeError:
                    self._lens = None
            return accepted(reason="released")
        if cursor_scene_pos is not None:
            # Caller supplied scene pos — update immediately
            self._update_loupe_impl(cursor_scene_pos)
        else:
            self._show_now()
        return accepted(reason="held")

    # -- loupe geometry -----------------------------------------------------

    def _ensure_lens(self) -> Any | None:
        if self._lens is not None and isValid(self._lens):
            return self._lens
        if self._lens_factory is None:
            return None
        try:
            self._lens = self._lens_factory()
            if self._lens is not None:
                self._lens.configure(self._zoom, self._reduce_motion)
            return self._lens
        except Exception:  # noqa: BLE001
            self._lens = None
            return None

    def _show_now(self) -> None:
        if self._cursor_provider is None:
            return
        try:
            scene_pos = self._cursor_provider()
        except Exception:  # noqa: BLE001
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

    def _update_loupe_impl(self, scene_pos: Any, *, display: Any = None, view_mapping: Any = None) -> None:
        if not self._enabled or not (self._held or self._persistent_active):
            if self._lens is not None and isValid(self._lens):
                try:
                    if self._lens.isVisible():
                        self._lens.hide_animated(instant=True)
                except RuntimeError:
                    self._lens = None
            return
        # Resolve display buffer
        if display is None and self._geometry_provider is not None:
            # Legacy fallback: ask the parent viewer
            try:
                parent = self.parent()
                if parent is not None and hasattr(parent, "_image_item"):
                    display = parent._image_item.image  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                display = None
        if display is None:
            return
        # Resolve mapped view point
        mapped = None
        if view_mapping is not None:
            mapped = view_mapping(scene_pos)
        elif self._geometry_provider is not None:
            # Try viewer._view.mapSceneToView
            try:
                parent = self.parent()
                if parent is not None and hasattr(parent, "_view"):
                    mapped = parent._view.mapSceneToView(scene_pos)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                mapped = None
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
            parent = self.parent()
            if parent is not None and hasattr(parent, "mapFromGlobal"):
                local = parent.mapFromGlobal(cursor_global)  # type: ignore[attr-defined]
                offset = QPoint(-lens.width() + 12, -lens.height() + 16)
                pos = local + offset
                pos.setX(max(0, min(pos.x(), max(0, parent.width() - lens.width()))))
                pos.setY(max(0, min(pos.y(), max(0, parent.height() - lens.height()))))
                lens.move(pos)
                center = QPoint(pos.x() + lens.width() // 2, pos.y() + lens.height() // 2)
                lens.set_anchor_delta(local - center)
                if not lens.isVisible():
                    lens.show_animated()
                    lens.raise_()
                else:
                    lens.update()
        except RuntimeError:
            self._lens = None
        except Exception:  # noqa: BLE001, S110
            pass

    def hide(self) -> None:
        self._held = False
        if self._lens is not None and isValid(self._lens):
            try:
                if self._lens.isVisible():
                    self._lens.hide_animated()
            except RuntimeError:
                pass

    def notify_point_placed(self) -> None:
        """A contour/caliper point was committed — hold drops unless persistent."""
        if self._persistent_active:
            return
        self._held = False
        if self._lens is not None and isValid(self._lens):
            try:
                if self._lens.isVisible():
                    self._lens.hide_animated()
            except RuntimeError:
                self._lens = None

    # -- persistent mode (linear calipers) ---------------------------------

    def sync_persistent(self, linear_active: bool, doppler_mode: str = "none", vessel_status: str = "none") -> None:
        allowed = self._enabled and self._linear_persistent and doppler_mode == "none" and vessel_status == "none"
        if linear_active and allowed:
            self._persistent_active = True
            self._show_now()
            return
        self._persistent_active = False
        if not self._held and self._lens is not None and isValid(self._lens):
            try:
                if self._lens.isVisible():
                    self._lens.hide_animated()
            except RuntimeError:
                pass

    @property
    def persistent_active(self) -> bool:
        return self._persistent_active

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
            except RuntimeError:
                pass
            self._lens = None
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self.held_changed.disconnect()
            except (RuntimeError, TypeError):
                pass
