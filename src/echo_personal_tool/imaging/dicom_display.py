"""The DICOM display chain: stored pixels → modality → VOI → presentation.

The decoder deliberately returns stored values (signed 16-bit CT pixels are
*not* HU yet).  This module owns the pure, Qt-free transforms that turn those
values into an 8-bit display image:

* Modality LUT (or ``RescaleSlope``/``RescaleIntercept``) → modality values;
* VOI LUT, or a DICOM ``WindowCenter``/``WindowWidth`` pair;
* the standard ``LINEAR``/``LINEAR_EXACT``/``SIGMOID`` window functions;
* ``MONOCHROME1`` inversion on the presentation value, not on the source;
* pixel padding removed from auto-window statistics and painted black.

Intensity measurements must use :func:`modality_value`, never the uint8
display image: the screen is windowed and quantised, the modality value is the
measurable number (HU for a properly rescaled CT, otherwise stored units).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np

from echo_personal_tool.domain.models.dicom_display import DicomDisplay, LookupTable


@dataclass(frozen=True)
class RenderedDisplay:
    """An 8-bit presentation image and the window that produced it."""

    pixels: np.ndarray
    center: float
    width: float


def _lut_values(table: LookupTable, values: np.ndarray) -> np.ndarray:
    """Nearest-entry lookup with DICOM clipping outside the LUT range."""
    entries = np.asarray(table.entries, dtype=np.float32)
    if entries.size == 0:
        return np.asarray(values, dtype=np.float32)
    index = np.rint(np.asarray(values, dtype=np.float32) - float(table.first_input))
    index = np.clip(index, 0, entries.size - 1).astype(np.intp)
    return cast(np.ndarray, entries[index])


def stored_to_modality(stored: np.ndarray, display: DicomDisplay) -> np.ndarray:
    """Map stored pixel values to modality values (identity when no transform)."""
    values = np.asarray(stored, dtype=np.float32)
    if display.modality_lut is not None:
        return _lut_values(display.modality_lut, values)
    return values * float(display.rescale_slope) + float(display.rescale_intercept)


def modality_value(stored_value: float, display: DicomDisplay | None) -> float:
    """One measurable modality value (HU after a proven CT rescale)."""
    if display is None:
        return float(stored_value)
    if display.modality_lut is None:
        return float(stored_value) * float(display.rescale_slope) + float(display.rescale_intercept)
    table = display.modality_lut
    if not table.entries:
        return float(stored_value)
    index = int(np.rint(float(stored_value) - float(table.first_input)))
    index = max(0, min(index, len(table.entries) - 1))
    return float(table.entries[index])


def padding_mask(stored: np.ndarray, display: DicomDisplay | None) -> np.ndarray | None:
    """Stored-value mask of the DICOM pixel padding, or ``None`` when absent."""
    if display is None or display.pixel_padding_value is None:
        return None
    values = np.asarray(stored)
    padding = float(display.pixel_padding_value)
    if display.pixel_padding_range_limit is None:
        return cast(np.ndarray, values == padding)
    limit = float(display.pixel_padding_range_limit)
    low, high = min(padding, limit), max(padding, limit)
    return (values >= low) & (values <= high)


def _percentile_range(values: np.ndarray, low_pct: float, high_pct: float) -> tuple[float, float]:
    flat = np.asarray(values, dtype=np.float32)
    flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return 0.0, 1.0
    low = float(np.percentile(flat, float(np.clip(low_pct, 0.0, 100.0))))
    high = float(np.percentile(flat, float(np.clip(high_pct, 0.0, 100.0))))
    if not np.isfinite(low) or not np.isfinite(high):
        return 0.0, 1.0
    if high < low:
        low, high = high, low
    return low, high


def resolve_window(
    display: DicomDisplay,
    modality: np.ndarray,
    *,
    dr_low_pct: float,
    dr_high_pct: float,
    window_scale: float,
    level_offset: float,
    numeric: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """Window center/width from a numeric choice, header pair, or auto range."""
    if numeric is not None:
        center, width = float(numeric[0]), max(float(numeric[1]), 1.0)
        return center, width

    preset = display.default_window
    if preset is not None:
        base_width = max(float(preset.width), 1.0)
        width = max(base_width * max(float(window_scale), 0.01), 1.0)
        center = float(preset.center) + float(level_offset) * base_width * 0.5
        return center, width

    low, high = _percentile_range(modality, dr_low_pct, dr_high_pct)
    span = max(high - low, 1.0)
    center = low + span * (0.5 + 0.5 * float(level_offset))
    width = max(span * max(float(window_scale), 0.01), 1.0)
    return center, width


def _linear_exact(values: np.ndarray, center: float, width: float) -> np.ndarray:
    low = center - width / 2.0
    scale = 255.0 / max(width, 1.0)
    return np.clip((values - low) * scale, 0.0, 255.0)


def _linear(values: np.ndarray, center: float, width: float) -> np.ndarray:
    """DICOM PS3.3 C.11.2.1.2.1 LINEAR, including the ``width == 1`` case."""
    if width <= 1.0:
        return np.where(values <= center - 0.5, 0.0, 255.0)
    low = center - 0.5 - (width - 1.0) / 2.0
    scale = 255.0 / (width - 1.0)
    return np.clip((values - low) * scale, 0.0, 255.0)


def _sigmoid(values: np.ndarray, center: float, width: float) -> np.ndarray:
    exponent = np.clip(-4.0 * (values - center) / max(width, 1.0), -60.0, 60.0)
    return 255.0 / (1.0 + np.exp(exponent))


def _apply_window(values: np.ndarray, center: float, width: float, function: str) -> np.ndarray:
    name = function.upper()
    if name == "LINEAR_EXACT":
        return _linear_exact(values, center, width)
    if name == "SIGMOID":
        return _sigmoid(values, center, width)
    return _linear(values, center, width)


def _voi_lut_display(values: np.ndarray, table: LookupTable) -> np.ndarray:
    """VOI LUT entries as presentation values (0–255)."""
    result = _lut_values(table, values)
    full_scale = float((1 << max(int(table.bits_per_entry), 1)) - 1)
    if full_scale > 255.0:
        result = result * (255.0 / full_scale)
    return cast(np.ndarray, np.clip(result, 0.0, 255.0))


def render_dicom_frame(
    stored: np.ndarray,
    display: DicomDisplay,
    *,
    dr_low_pct: float = 0.0,
    dr_high_pct: float = 100.0,
    window_scale: float = 1.0,
    level_offset: float = 0.0,
    numeric_window: tuple[float, float] | None = None,
) -> RenderedDisplay:
    """Render stored pixels through the full DICOM display chain.

    ``numeric_window`` is a physician-entered ``(center, width)`` and always
    wins.  Otherwise the first header window is the default, a VOI LUT is used
    only while the W/L sliders are untouched, and a study without either gets
    an auto range from non-padding modality values.
    """
    values = stored_to_modality(stored, display)
    mask = padding_mask(stored, display)
    valid = values[~mask] if mask is not None else values
    center, width = resolve_window(
        display,
        valid,
        dr_low_pct=dr_low_pct,
        dr_high_pct=dr_high_pct,
        window_scale=window_scale,
        level_offset=level_offset,
        numeric=numeric_window,
    )

    use_voi_lut = (
        display.voi_lut is not None
        and numeric_window is None
        and not display.window_presets
        and float(window_scale) == 1.0
        and float(level_offset) == 0.0
    )
    if use_voi_lut and display.voi_lut is not None:
        pixels = _voi_lut_display(values, display.voi_lut)
    else:
        pixels = _apply_window(values, center, width, display.voi_lut_function)

    if display.is_monochrome1:
        pixels = 255.0 - pixels
    result = np.asarray(np.rint(np.clip(pixels, 0.0, 255.0)), dtype=np.uint8)
    if mask is not None:
        result = result.copy()
        result[mask] = 0
    return RenderedDisplay(pixels=result, center=center, width=width)
