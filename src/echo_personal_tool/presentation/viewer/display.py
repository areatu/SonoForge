"""Display-level projection owner extracted from :class:`ViewerWidget`.

``ViewerDisplay`` owns the window/level/DR sliders, the computed display levels,
the LUT and its double buffer, and the per-instance/per-file WL/DR caches.  It
is a presentation projection, not a document owner: it never stores a
``ViewerState`` and receives the current frame, colour source and enabled flag
through a narrow port.

The two WL/DR caches are intentionally kept as two key spaces: ``set_state``
identifies a clip by ``sop_instance_uid`` while ``show_frame`` identifies the
file by path, and unifying them would change which remembered values win when
the two identities disagree.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QSlider, QWidget

from echo_personal_tool.imaging.display import (
    apply_window_level_rgb,
    compute_display_levels,
    dr_percentiles_from_slider,
    grayscale_source_array,
)

#: Bound of the uid-keyed WL/DR memory; the path-keyed map follows the viewer's
#: file lifetime instead (same as before the extraction).
_WL_DR_CACHE_MAX = 200


class ViewerDisplay(QObject):
    """One owner for the display levels, LUT, buffers and WL/DR caches."""

    def __init__(
        self,
        *,
        parent: QWidget,
        frame_provider: Callable[[], np.ndarray | None],
        enabled_provider: Callable[[], bool],
        color_source_provider: Callable[[], np.ndarray | None],
        color_active_provider: Callable[[], bool],
        image_item: Any,
        invalidate_edge_map: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._frame_provider = frame_provider
        self._enabled_provider = enabled_provider
        self._color_source_provider = color_source_provider
        self._color_active_provider = color_active_provider
        self._image_item = image_item
        self._invalidate_edge_map = invalidate_edge_map

        self.window_slider = QSlider(Qt.Orientation.Horizontal, parent)
        self.window_slider.setRange(1, 400)
        self.window_slider.setValue(100)

        self.level_slider = QSlider(Qt.Orientation.Horizontal, parent)
        self.level_slider.setRange(0, 100)
        self.level_slider.setValue(50)

        self.dr_slider = QSlider(Qt.Orientation.Horizontal, parent)
        self.dr_slider.setRange(0, 100)
        self.dr_slider.setValue(50)
        self.dr_slider.setToolTip("Dynamic range: center = full range; left = clip dark (typical for US)")

        self._cached_levels_key: tuple[int, int, int] | None = None
        self._cached_display_low: float | None = None
        self._cached_display_high: float | None = None
        self._cached_lut: np.ndarray | None = None
        self._cached_lut_key: tuple[float, float, str] | None = None
        self._display_buffers: list[np.ndarray] = []
        self._display_buf_idx = 0

        self._instance_wl_dr_cache: OrderedDict[str, tuple[int, int, int]] = OrderedDict()
        self._per_file_wl_dr: dict[Path, tuple[int, int, int]] = {}
        self._current_path: Path | None = None

        self._external_wl_dr_sliders: tuple[Any, Any, Any] | None = None
        self._external_wl_dr_slider_exts: list[Any] = []
        self._bound_sliders: list[tuple[Any, QSlider]] = []

        for slider in (self.window_slider, self.level_slider, self.dr_slider):
            slider.valueChanged.connect(self.update_levels)

    # ── values and cache keys ────────────────────────────────────────

    @property
    def values(self) -> tuple[int, int, int]:
        return (
            self.window_slider.value(),
            self.level_slider.value(),
            self.dr_slider.value(),
        )

    def levels_key(self) -> tuple[int, int, int]:
        """Canonical cache key for the display levels: (window, level, DR)."""
        return self.values

    @property
    def external_sliders(self) -> tuple[object, object, object] | None:
        return self._external_wl_dr_sliders

    @property
    def cached_levels_key(self) -> tuple[int, int, int] | None:
        return self._cached_levels_key

    @cached_levels_key.setter
    def cached_levels_key(self, value: tuple[int, int, int] | None) -> None:
        # Kept for the frozen contract/test seam; production writers use the
        # method below so the LUT cache is dropped with the level cache.
        self._cached_levels_key = value

    def invalidate_cached_levels(self) -> None:
        """Drop the computed-level cache after a display-mode/instance change."""
        self._cached_display_low = None
        self._cached_display_high = None
        self._cached_levels_key = None
        self._cached_lut = None
        self._cached_lut_key = None

    # ── enabling and external sliders ────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable the internal sliders and the bound panel controls."""
        for slider in (self.window_slider, self.level_slider, self.dr_slider):
            slider.setEnabled(enabled)
        self.sync_external_enabled()

    def sync_external_enabled(self) -> None:
        """Mirror the current enabled flag onto bound controls, if any are bound."""
        enabled = self._enabled_provider()
        for external, internal in self._bound_sliders:
            external.setEnabled(enabled)
            internal.setEnabled(enabled)

    def bind_external(
        self,
        window_slider: object,
        level_slider: object,
        dr_slider: object,
    ) -> None:
        """Wire the panel's labelled sliders to the internal ones."""
        from echo_personal_tool.presentation.ge_labeled_slider import (
            GeLabeledSlider,
            TopLabeledSlider,
        )

        sliders: list[tuple[Any, QSlider]] = []
        for external, internal in (
            (window_slider, self.window_slider),
            (level_slider, self.level_slider),
            (dr_slider, self.dr_slider),
        ):
            if not isinstance(external, (GeLabeledSlider, TopLabeledSlider)):
                continue
            ext = external.slider()
            sliders.append((external, internal))
            ext.setRange(internal.minimum(), internal.maximum())
            ext.setValue(internal.value())

        self._bound_sliders = sliders
        self._external_wl_dr_sliders = (window_slider, level_slider, dr_slider)
        self._external_wl_dr_slider_exts = []
        for external, internal in sliders:
            ext = external.slider()
            self._external_wl_dr_slider_exts.append(ext)
            ext.setRange(internal.minimum(), internal.maximum())
            ext.setValue(internal.value())
            ext.valueChanged.connect(internal.setValue)
            internal.valueChanged.connect(ext.setValue)
            ext.valueChanged.connect(self.update_levels)
        self.sync_external_enabled()

    def disconnect_external(self) -> None:
        """Block external slider signals to prevent dangling references."""
        for ext in self._external_wl_dr_slider_exts:
            try:
                ext.blockSignals(True)
            except RuntimeError:
                pass

    # ── value projection ─────────────────────────────────────────────

    def set_values(
        self,
        window: int,
        level: int,
        dr: int,
        *,
        update_display: bool = True,
    ) -> None:
        """Set window/level/DR on internal + external sliders with signals blocked."""
        ext = self._external_wl_dr_sliders
        internal = (self.window_slider, self.level_slider, self.dr_slider)
        for slider in internal:
            slider.blockSignals(True)
        if ext is not None:
            for external_slider in ext:
                if hasattr(external_slider, "blockSignals"):
                    external_slider.blockSignals(True)
        self.window_slider.setValue(window)
        self.level_slider.setValue(level)
        self.dr_slider.setValue(dr)
        if ext is not None:
            ext_win, ext_lev, ext_dr = ext
            if hasattr(ext_win, "setValue"):
                ext_win.setValue(window)
            if hasattr(ext_lev, "setValue"):
                ext_lev.setValue(level)
            if hasattr(ext_dr, "setValue"):
                ext_dr.setValue(dr)
        for slider in internal:
            slider.blockSignals(False)
        if ext is not None:
            for external_slider in ext:
                if hasattr(external_slider, "blockSignals"):
                    external_slider.blockSignals(False)
        if update_display:
            self.update_levels()

    def save_current_wl_dr(self) -> None:
        """Save the current slider values for the active file path."""
        if self._current_path is not None:
            self._per_file_wl_dr[self._current_path] = self.values

    def set_current_path(self, path: Path | None) -> None:
        """Remember the old file's values and restore the new file's (or 100/50/50)."""
        if path == self._current_path:
            return
        self.save_current_wl_dr()
        self._current_path = path
        saved = self._per_file_wl_dr.get(path) if path is not None else None
        if saved is not None:
            self.set_values(*saved)
        else:
            self.set_values(100, 50, 50)

    # ── uid-keyed memory ─────────────────────────────────────────────

    def remember_instance(self, uid: str) -> None:
        """Remember this clip's WL/DR before switching away from it."""
        if uid in self._instance_wl_dr_cache:
            self._instance_wl_dr_cache.move_to_end(uid)
        else:
            if len(self._instance_wl_dr_cache) >= _WL_DR_CACHE_MAX:
                self._instance_wl_dr_cache.popitem(last=False)
        self._instance_wl_dr_cache[uid] = self.values

    def restore_instance(self, uid: str | None) -> bool:
        """Restore remembered WL/DR for ``uid``; unknown ids leave values alone."""
        if not uid or uid not in self._instance_wl_dr_cache:
            return False
        self._instance_wl_dr_cache.move_to_end(uid)
        window, level, dr = self._instance_wl_dr_cache[uid]
        self.set_values(window, level, dr, update_display=False)
        return True

    # ── levels, LUT and buffers ──────────────────────────────────────

    def update_levels(self) -> None:
        """Compute/cache levels and upload the rendered frame to the image item."""
        frame = self._frame_provider()
        if frame is None or not self._enabled_provider():
            return
        frame = np.asarray(frame)
        if frame.size == 0:
            return

        sliders_key = self.levels_key()
        if (
            self._cached_display_low is not None
            and self._cached_display_high is not None
            and self._cached_levels_key == sliders_key
        ):
            low, high = self._cached_display_low, self._cached_display_high
        else:
            dr_low, dr_high = dr_percentiles_from_slider(self.dr_slider.value())
            window_scale = self.window_slider.value() / 100.0
            level_offset = (self.level_slider.value() - 50) / 50.0
            low, high = compute_display_levels(
                np.asarray(frame, dtype=float),
                dr_low_pct=dr_low,
                dr_high_pct=dr_high,
                window_scale=window_scale,
                level_offset=level_offset,
            )
            is_outlier = self.is_levels_outlier(low, high, frame)
            if not is_outlier:
                self._cached_display_low = low
                self._cached_display_high = high
                self._cached_levels_key = sliders_key
            elif self._cached_display_low is not None and self._cached_display_high is not None:
                low, high = self._cached_display_low, self._cached_display_high

        color_source = self._color_source_provider()
        if self._color_active_provider() and color_source is not None:
            display = apply_window_level_rgb(color_source, low, high)
            self._image_item.setImage(display, autoLevels=False)
        else:
            src = grayscale_source_array(frame)  # MAY BE READ-ONLY
            span = max(high - low, 1.0)
            lut_key = (low, span, str(src.dtype))
            if self._cached_lut_key == lut_key and self._cached_lut is not None:
                lut = self._cached_lut
            elif src.dtype == np.uint16:
                lut = np.clip(
                    (np.arange(65536, dtype=np.float32) - low) / span * 255.0,
                    0.0,
                    255.0,
                ).astype(np.uint8)
                self._cached_lut = lut
                self._cached_lut_key = lut_key
            else:
                lut = np.clip(
                    (np.arange(256, dtype=np.float32) - low) / span * 255.0,
                    0.0,
                    255.0,
                ).astype(np.uint8)
                self._cached_lut = lut
                self._cached_lut_key = lut_key

            dst = self._ensure_display_buffer(src.shape)  # WRITABLE
            if src.dtype == np.uint16:
                np.take(lut, src, out=dst)  # src can be read-only
            else:
                src_u8 = src if src.dtype == np.uint8 else np.clip(src, 0, 255).astype(np.uint8)
                cv2.LUT(src_u8, lut, dst=dst)  # dst is writable

            self._image_item.setImage(dst, autoLevels=False)
            self._display_buf_idx = (self._display_buf_idx + 1) % len(self._display_buffers)
        self._invalidate_edge_map()

    def _ensure_display_buffer(self, shape: tuple[int, ...]) -> np.ndarray:
        """Return a pre-allocated WRITABLE uint8 buffer from the double buffer pool."""
        for buf in self._display_buffers:
            if buf.shape == shape:
                return self._display_buffers[self._display_buf_idx]
        self._display_buffers = [
            np.empty(shape, dtype=np.uint8),
            np.empty(shape, dtype=np.uint8),
        ]
        self._display_buf_idx = 0
        return self._display_buffers[0]

    def is_levels_outlier(self, low: float, high: float, frame: np.ndarray) -> bool:
        """Check whether computed levels indicate an outlier frame (dark/bright/flat)."""
        arr = np.asarray(frame)
        if arr.size == 0:
            return True
        if arr.dtype.kind in "iu":
            info = np.iinfo(arr.dtype)
            low_bound = float(info.min)
            full_scale = float(info.max) - low_bound
        else:
            low_bound = 0.0
            full_scale = 255.0
        to_8bit = 255.0 / max(full_scale, 1.0)

        pixel_range = (high - low) * to_8bit
        if pixel_range < 10.0:
            return True
        flat = arr.astype(np.float32, copy=False).ravel()
        mean_val = (float(flat.mean()) - low_bound) * to_8bit
        if mean_val < 5.0 or mean_val > 250.0:
            return True
        std_val = float(flat.std()) * to_8bit
        return std_val < 3.0

    def effective_levels(self) -> tuple[float, float] | None:
        """The levels implied by the current sliders, without rendering."""
        frame = self._frame_provider()
        if frame is None:
            return None
        frame = np.asarray(frame)
        if frame.size == 0:
            return None
        if frame.ndim == 3:
            gray = np.asarray(frame[..., :3].mean(axis=2, dtype=np.float64))
        else:
            gray = frame.astype(np.float64, copy=False)
        dr_low, dr_high = dr_percentiles_from_slider(self.dr_slider.value())
        return compute_display_levels(
            gray,
            dr_low_pct=dr_low,
            dr_high_pct=dr_high,
            window_scale=self.window_slider.value() / 100.0,
            level_offset=(self.level_slider.value() - 50) / 50.0,
        )
