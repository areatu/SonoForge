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
class AnatomicalWindowSpec:
    """Standard radiological anatomical window/level preset (HU)."""

    key: str
    center: float
    width: float
    i18n_key: str
    aliases: tuple[str, ...] = ()

    def to_preset(self, explanation: str = "") -> WindowPreset:
        return WindowPreset(center=self.center, width=self.width, explanation=explanation or self.key)


ANATOMICAL_WINDOW_PRESETS: tuple[AnatomicalWindowSpec, ...] = (
    AnatomicalWindowSpec(
        key="brain",
        center=40.0,
        width=80.0,
        i18n_key="ctmr.window.brain",
        aliases=("brain", "head", "cerebrum", "neuro", "мозг", "головной мозг"),
    ),
    AnatomicalWindowSpec(
        key="lungs",
        center=-600.0,
        width=1500.0,
        i18n_key="ctmr.window.lungs",
        aliases=("lungs", "lung", "pulmonary", "лёгкие", "легкие"),
    ),
    AnatomicalWindowSpec(
        key="bones",
        center=400.0,
        width=1800.0,
        i18n_key="ctmr.window.bones",
        aliases=("bones", "bone", "skeletal", "osseous", "кости", "костный"),
    ),
    AnatomicalWindowSpec(
        key="chest",
        center=40.0,
        width=400.0,
        i18n_key="ctmr.window.chest",
        aliases=("chest", "mediastinum", "thorax", "грудная клетка", "средостение"),
    ),
    AnatomicalWindowSpec(
        key="abdomen",
        center=50.0,
        width=350.0,
        i18n_key="ctmr.window.abdomen",
        aliases=("abdomen", "abdominal", "soft tissue", "soft", "брюшная полость", "живот"),
    ),
    AnatomicalWindowSpec(
        key="angio",
        center=300.0,
        width=600.0,
        i18n_key="ctmr.window.angio",
        aliases=("angio", "cta", "vascular", "vessels", "ангио", "сосуды"),
    ),
)

ANATOMICAL_WINDOW_BY_KEY: dict[str, AnatomicalWindowSpec] = {spec.key: spec for spec in ANATOMICAL_WINDOW_PRESETS}


def anatomical_window_preset(key: str) -> WindowPreset | None:
    """Resolve one canonical anatomical window preset by key."""
    spec = ANATOMICAL_WINDOW_BY_KEY.get(key.strip().casefold())
    return spec.to_preset() if spec is not None else None


def match_anatomical_window(name: str) -> AnatomicalWindowSpec | None:
    """Match a header explanation or user query to an anatomical window spec."""
    token = name.strip().casefold()
    if not token:
        return None
    direct = ANATOMICAL_WINDOW_BY_KEY.get(token)
    if direct is not None:
        return direct
    for spec in ANATOMICAL_WINDOW_PRESETS:
        if any(alias in token for alias in spec.aliases):
            return spec
    return None


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
