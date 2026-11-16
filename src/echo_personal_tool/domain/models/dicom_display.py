"""DICOM display metadata: modality values, VOI windows and inversion.

The decoder returns *stored pixel values*.  Turning them into something a
monitor can show is a separate, standardised chain (PS3.3 C.11):

    stored values -> modality values -> VOI / window -> presentation -> screen

This module carries the header facts that chain needs.  It is deliberately
Qt-free and holds no pixels: the pure transforms live in
``echo_personal_tool.imaging.dicom_display``, so the same rules can be tested
without a window and reused by intensity measurements.

An empty ``DicomDisplay`` is not created for a plain ultrasound image: the
mapper returns ``None`` and the existing ultrasound window/level path stays in
charge.  ``value_unit`` is only ``HU`` when the header actually proves the
rescale, never merely because the modality says CT.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowPreset:
    """One ``WindowCenter``/``WindowWidth`` pair from the header."""

    center: float
    width: float
    explanation: str = ""

    @property
    def label(self) -> str:
        return self.explanation.strip() or f"{self.center:g} / {self.width:g}"


@dataclass(frozen=True)
class LookupTable:
    """A DICOM LUT: first mapped input plus its entries."""

    first_input: float
    entries: tuple[float, ...]
    bits_per_entry: int = 16

    @property
    def last_input(self) -> float:
        return self.first_input + max(len(self.entries) - 1, 0)


@dataclass(frozen=True)
class DicomDisplay:
    """How one DICOM instance maps stored pixels to a display image."""

    photometric: str = "MONOCHROME2"
    rescale_slope: float = 1.0
    rescale_intercept: float = 0.0
    rescale_type: str = ""
    #: Header windows in declaration order; the first is the default.
    window_presets: tuple[WindowPreset, ...] = ()
    voi_lut_function: str = "LINEAR"
    voi_lut: LookupTable | None = None
    modality_lut: LookupTable | None = None
    pixel_padding_value: float | None = None
    pixel_padding_range_limit: float | None = None
    presentation_lut_shape: str = ""
    #: ``HU`` only after a proven RescaleSlope/Intercept on a CT instance.
    value_unit: str = ""

    @property
    def is_monochrome1(self) -> bool:
        """MONOCHROME1 or an explicit inverse presentation LUT."""
        return self.photometric.upper() == "MONOCHROME1" or self.presentation_lut_shape.upper() == "INVERSE"

    @property
    def has_modality_transform(self) -> bool:
        return self.modality_lut is not None or self.rescale_slope != 1.0 or self.rescale_intercept != 0.0

    @property
    def default_window(self) -> WindowPreset | None:
        return self.window_presets[0] if self.window_presets else None

    @property
    def has_header_window(self) -> bool:
        return bool(self.window_presets)
