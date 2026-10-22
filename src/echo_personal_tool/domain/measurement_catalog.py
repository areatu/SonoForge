"""Measurement tool catalog: stable ids, RU/EN labels, units (TP-0, spec 2026-10-15 §5, §8.1).

Pure domain module (no Qt, no infrastructure).  It is the single source for:

* **Measurements** (:data:`MEASUREMENTS`) — the results a tool produces
  (``lv.lvedd``, ``av.vti`` …) with one-language labels (D-02), the physical
  quantity and the rounding rule.
* **Tools** (:data:`CATALOG`) — every button of the Measures menu with a
  stable id, its action payload, contexts, requirements and the
  ``legacy_ids`` used by the version-2 tool layout (``"<action>|<view>|…"``).
* **Sections** (:data:`SECTIONS`) — the built-in anatomical sections.

TP-0 PR-1 has **no visible change**: the panel still renders
``presentation/measures_menu._MENU``; the catalog mirrors it one-to-one and
``tests/unit/test_measurement_catalog.py`` keeps both in sync.  TP-1 switches
the labels of the panel, overlay, report text and PDF to this catalog.

Label rules (spec §5.1 with the user's Q-03 answers, 2026-10-16):

1. One label, one language — the interface language.  No bracketed
   translations.
2. EN — ASE 2025 abbreviations (Table 6 «Measurement dictionary»); entries not
   yet reconciled with the full table carry ``verified=False`` (TP-0 PR-3).
3. RU — Russian clinical abbreviations.  Latin is allowed only for the
   symbols and terms in :data:`RU_LATIN_ALLOWLIST`: wave/quantity symbols
   (E, A, e′, a′, s′, Vmax, Vps, Ved, dP/dt, Qp, Qs) and the terms kept
   untranslated by decision Q-03 (DT, IVRT, VTI, DVI).
4. Biplane in RU is «Биплан» (not «бипланово»).
5. Indexed values in RU take a lower-case «и» prefix: иКДО, иОЛП, иУО …
6. PASP in RU is «Сист. ДЛА».

Units (decisions Q-01/Q-02, 2026-10-16): linear dimensions are shown in
**mm** by default; TP-1 adds the switch «Линейные размеры: мм / см (ASE)».
Doppler velocities: **CW — m/s, PW and TDI — cm/s** (D-17).

ASE 2025 (TP-0 PR-3): the measurement dictionary of the reporting standard
lives in :mod:`echo_personal_tool.domain.ase_table6`; a measurement points at
its row through :attr:`MeasurementSpec.ase_row`, and the deviations of the
project from the table (mm instead of cm, cm/s instead of m/s) are listed
there with a reason — nothing deviates silently.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from echo_personal_tool.domain.ase_table6 import TABLE6_BY_ID as _TABLE6_BY_ID
from echo_personal_tool.domain.ase_table6 import Table6Row


def ase_table6_row(row_id: str | None) -> Table6Row | None:
    """Row of ASE 2025 Table 6 by id (``None`` when the row is unknown)."""
    if not row_id:
        return None
    return _TABLE6_BY_ID.get(row_id)


# ── Vocabulary ──────────────────────────────────────────────────────

LANGUAGES: tuple[str, ...] = ("ru", "en")

CTX_2D = "2d"
CTX_M = "m"
CTX_PW = "pw"
CTX_CW = "cw"
CTX_TDI = "tdi"
CTX_VESSEL = "vessel"
CONTEXTS: tuple[str, ...] = (CTX_2D, CTX_M, CTX_PW, CTX_CW, CTX_TDI, CTX_VESSEL)
DOPPLER_CONTEXTS: frozenset[str] = frozenset({CTX_PW, CTX_CW, CTX_TDI})

REQ_SPATIAL = "spatial_calibration"
REQ_DOPPLER = "doppler_calibration"
REQ_MMODE = "mmode_calibration"
REQ_BSA = "bsa"
REQ_FRAME_TIMING = "frame_timing"  # cine loop with a known frame rate

FLAG_EXPERIMENTAL = "experimental"
FLAG_AI = "ai"  # ONNX inference; hidden in builds without AI segmentation
FLAG_SEQUENCE = "sequence"  # one tool, several results in a fixed order
FLAG_MULTIVIEW = "multiview"  # compares two clips


class ToolKind(str, Enum):
    """What the user does with the tool in the viewer."""

    DISTANCE = "distance"
    AREA = "area"
    VOLUME = "volume"
    PEAK = "peak"
    INTERVAL = "interval"
    TRACE = "trace"
    AUTO = "auto"
    INPUT = "input"
    ACTION = "action"  # command without a measurement of its own

    def __str__(self) -> str:
        return str(self.value)


class Quantity(str, Enum):
    """Physical quantity of a result; the display unit follows from it."""

    LENGTH = "length"  # chamber / wall / vessel dimension — mm or cm (Q-01)
    ORIFICE = "orifice"  # diameter used in area formulas (LVOT, RVOT, MV) — cm
    PISA_RADIUS = "pisa_radius"  # cm
    VTI = "vti"  # cm
    VELOCITY = "velocity"  # CW m/s, PW/TDI cm/s (Q-02 / D-17)
    TIME = "time"  # ms
    AREA = "area"  # cm²
    VOLUME = "volume"  # mL
    MASS = "mass"  # g
    INDEXED_VOLUME = "indexed_volume"  # mL/m²
    INDEXED_MASS = "indexed_mass"  # g/m²
    INDEXED_AREA = "indexed_area"  # cm²/m²
    PRESSURE = "pressure"  # mmHg
    PRESSURE_RATE = "pressure_rate"  # mmHg/s
    RATE = "rate"  # bpm
    RATIO = "ratio"  # dimensionless
    PERCENT = "percent"  # %

    def __str__(self) -> str:
        return str(self.value)


# Q-01 (2026-10-16): linear dimensions in mm by default; "cm" is the ASE
# option of the TP-1 switch «Линейные размеры: мм / см (ASE)».
LINEAR_UNIT_MM = "mm"
LINEAR_UNIT_CM = "cm"
LINEAR_UNIT_OPTIONS: tuple[str, ...] = (LINEAR_UNIT_MM, LINEAR_UNIT_CM)
DEFAULT_LINEAR_UNIT = LINEAR_UNIT_MM

_FIXED_UNITS: Mapping[Quantity, str] = MappingProxyType(
    {
        Quantity.ORIFICE: "cm",
        Quantity.PISA_RADIUS: "cm",
        Quantity.VTI: "cm",
        Quantity.TIME: "ms",
        Quantity.AREA: "cm²",
        Quantity.VOLUME: "mL",
        Quantity.MASS: "g",
        Quantity.INDEXED_VOLUME: "mL/m²",
        Quantity.INDEXED_MASS: "g/m²",
        Quantity.INDEXED_AREA: "cm²/m²",
        Quantity.PRESSURE: "mmHg",
        Quantity.PRESSURE_RATE: "mmHg/s",
        Quantity.RATE: "bpm",
        Quantity.RATIO: "",
        Quantity.PERCENT: "%",
    }
)


def velocity_unit_for_mode(mode: str | None) -> str:
    """Q-02 / D-17: CW in m/s; PW and TDI in cm/s (unknown → cm/s)."""
    return "m/s" if (mode or "").strip().lower() == CTX_CW else "cm/s"


def display_unit(
    quantity: Quantity,
    *,
    linear_unit: str = DEFAULT_LINEAR_UNIT,
    doppler_mode: str | None = None,
) -> str:
    """Display unit of a quantity under the user's unit settings."""
    if quantity is Quantity.LENGTH:
        if linear_unit not in LINEAR_UNIT_OPTIONS:
            raise ValueError(f"unknown linear unit: {linear_unit!r}")
        return linear_unit
    if quantity is Quantity.VELOCITY:
        return velocity_unit_for_mode(doppler_mode)
    return _FIXED_UNITS[quantity]


# ── Records ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Label:
    """Short label for rows/overlay and full name for tooltips and the report."""

    short: str
    full: str


@dataclass(frozen=True)
class ActionPayload:
    """What the panel emits today for a tool (mirrors ``_MenuButton``).

    ``action`` is the ``MeasurementAction`` value (``None`` for buttons that
    only set a caliper/Doppler label).  :attr:`legacy_id` reproduces
    ``_MenuButton.tool_id`` — the id stored in tool layout v2.
    """

    action: str | None = None
    view: str = "A4C"
    phase: str = "ED"
    caliper_label: str = ""
    doppler_peak: str = ""
    doppler_interval: str = ""
    doppler_trace: str = ""
    vessel: bool = False

    @property
    def legacy_id(self) -> str:
        return "|".join(
            (
                str(self.action),
                self.view,
                self.phase,
                self.caliper_label,
                self.doppler_peak,
                self.doppler_interval,
                self.doppler_trace,
            )
        )


@dataclass(frozen=True)
class MeasurementSpec:
    """One result: labels, quantity, rounding and the ASE reference."""

    id: str
    labels: Mapping[str, Label]
    quantity: Quantity
    decimals: int
    doppler_mode: str | None = None  # expected mode of a velocity (cw/pw/tdi)
    ase_ref: str | None = None  # "Table 6", "Table 2", "ASE 2025 DD" …
    ase_row: str | None = None  # row of ASE 2025 Table 6 (see ase_table6)
    verified: bool = False  # reconciled with the ASE source (TP-0 PR-3)
    synonyms: tuple[str, ...] = ()
    indexed: bool = False

    def label(self, language: str) -> Label:
        return self.labels[_language(language)]

    def unit(self, *, linear_unit: str = DEFAULT_LINEAR_UNIT, doppler_mode: str | None = None) -> str:
        return display_unit(self.quantity, linear_unit=linear_unit, doppler_mode=doppler_mode or self.doppler_mode)

    def decimals_for(self, unit: str) -> int:
        """Rounding for the shown unit (linear: mm → 0, cm → 1; m/s → as in ASE)."""
        if self.quantity is Quantity.LENGTH:
            return 0 if unit == LINEAR_UNIT_MM else 1
        if self.quantity is Quantity.VELOCITY and unit == "m/s":
            row = ase_table6_row(self.ase_row)
            if row is not None and row.unit == "m/s":
                return row.decimals
        return self.decimals


def ase_mode_unit(spec: MeasurementSpec) -> str:
    """Unit of a measurement in the «ASE» mode (TP-0 PR-3).

    The mode of the ASE 2025 table: linear dimensions in **cm** (the project
    shows mm by default — D-12), CW velocities in **m/s**, PW and TDI in
    **cm/s** (D-05/D-17).  Used by the reconciliation test: the ASE row of a
    measurement must match this unit, unless the deviation is documented in
    ``ase_table6.ASE_UNIT_DEVIATIONS``.
    """
    if spec.quantity is Quantity.LENGTH:
        return LINEAR_UNIT_CM
    if spec.quantity is Quantity.VELOCITY:
        return velocity_unit_for_mode(spec.doppler_mode)
    return display_unit(spec.quantity, linear_unit=LINEAR_UNIT_CM, doppler_mode=spec.doppler_mode)


@dataclass(frozen=True)
class ToolSpec:
    """Catalog entry of one tool (spec §8.1)."""

    id: str
    kind: ToolKind
    labels: Mapping[str, Label]
    section: str
    payload: ActionPayload
    contexts: frozenset[str]
    result_keys: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    requires: frozenset[str] = frozenset()
    flags: frozenset[str] = frozenset()
    default_key: str | None = None
    label_key: str = ""  # current locale key (menu.*), until TP-1
    reference_id: str | None = None
    legacy_ids: tuple[str, ...] = field(default=())

    def label(self, language: str) -> Label:
        return self.labels[_language(language)]

    @property
    def legacy_id(self) -> str:
        return self.payload.legacy_id


@dataclass(frozen=True)
class SectionSpec:
    id: str
    legacy_key: str  # group key of _MENU / layout v2
    labels: Mapping[str, Label]
    flags: frozenset[str] = frozenset()

    def label(self, language: str) -> Label:
        return self.labels[_language(language)]


def _language(language: str) -> str:
    code = (language or "").strip().lower()[:2]
    return code if code in LANGUAGES else "en"


def _labels(ru: tuple[str, str] | str, en: tuple[str, str] | str) -> Mapping[str, Label]:
    ru_short, ru_full = (ru, ru) if isinstance(ru, str) else ru
    en_short, en_full = (en, en) if isinstance(en, str) else en
    return MappingProxyType({"ru": Label(ru_short, ru_full), "en": Label(en_short, en_full)})


# ── Label validation (A-12) ─────────────────────────────────────────

# Latin tokens allowed in Russian labels: symbols of quantities and waves, and
# the abbreviations kept in English by decision Q-03 (DT, IVRT, VTI, DVI).
# TAPSE, PISA and GLS are international names used as proper names (spec §5.2,
# "как «метод Симпсона»"); listed separately so they can be revisited.
RU_SYMBOLS: frozenset[str] = frozenset({"E", "A", "e′", "a′", "s′", "Vmax", "Vps", "Ved", "dP/dt", "Qp", "Qs", "RR"})
RU_UNTRANSLATED_TERMS: frozenset[str] = frozenset({"DT", "IVRT", "VTI", "DVI"})
RU_PROPER_NAMES: frozenset[str] = frozenset({"TAPSE", "PISA", "GLS"})
RU_LATIN_ALLOWLIST: frozenset[str] = RU_SYMBOLS | RU_UNTRANSLATED_TERMS | RU_PROPER_NAMES

# A Latin "word" in a Russian label: letters plus the prime (e′).  "dP/dt" and
# "Δt" are cut out first; other slashes separate symbols ("E/A", "E/e′").
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z′]*")
_RU_COMPOUND_SYMBOLS: tuple[str, ...] = ("dP/dt", "Δt")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def ru_label_violations(text: str) -> list[str]:
    """Latin tokens of a Russian label that are not in the allowlist."""
    for symbol in _RU_COMPOUND_SYMBOLS:
        text = text.replace(symbol, " ")
    return [token for token in _LATIN_TOKEN_RE.findall(text) if token not in RU_LATIN_ALLOWLIST]


def en_label_violations(text: str) -> list[str]:
    """Cyrillic characters in an English label."""
    return _CYRILLIC_RE.findall(text)


# ── Measurements ────────────────────────────────────────────────────

_T6 = "Table 6"
_T2 = "Table 2"
_DIAS = "ASE 2025 Diastolic"
_RIGHT = "ASE 2025 Right Heart"
_AS2017 = "ASE 2017 AS"
_MS2017 = "ASE 2017 MS"
_AR2017 = "ASE 2017 AR"
_MR2017 = "ASE 2017 MR/TR"
_CH2015 = "ASE 2015 Chambers"


def _m(
    mid: str,
    ru: tuple[str, str],
    en: tuple[str, str],
    quantity: Quantity,
    decimals: int,
    *,
    mode: str | None = None,
    ase: str | None = None,
    ase_row: str | None = None,
    verified: bool = False,
    synonyms: tuple[str, ...] = (),
    indexed: bool = False,
) -> MeasurementSpec:
    return MeasurementSpec(
        id=mid,
        labels=_labels(ru, en),
        quantity=quantity,
        decimals=decimals,
        doppler_mode=mode,
        ase_ref=ase,
        ase_row=ase_row,
        verified=verified,
        synonyms=synonyms,
        indexed=indexed,
    )


_LEN, _ORI, _PIS, _VTI, _VEL, _TIM = (
    Quantity.LENGTH,
    Quantity.ORIFICE,
    Quantity.PISA_RADIUS,
    Quantity.VTI,
    Quantity.VELOCITY,
    Quantity.TIME,
)

_MEASUREMENT_LIST: tuple[MeasurementSpec, ...] = (
    # ── LV linear (protocol «ЛЖ линейно») ──
    _m("lv.ivsd", ("МЖП", "Толщина межжелудочковой перегородки в диастолу"),
       ("IVSD", "Interventricular septal thickness in diastole"), _LEN, 0, ase=_T6, ase_row='lv.ivsd', verified=True, synonyms=("IVSd", "ivs", "межжелудочковая перегородка")),
    _m("lv.lvedd", ("КДР ЛЖ", "Конечно-диастолический размер ЛЖ"),
       ("LVEDD", "LV end-diastolic dimension"), _LEN, 0, ase=_T6, ase_row='lv.lvedd', verified=True, synonyms=("LVIDd", "LVEDD", "lvedd", "edd", "кдр")),
    _m("lv.lvpwd", ("ЗСЛЖ", "Толщина задней стенки ЛЖ в диастолу"),
       ("LVPWD", "LV posterior wall thickness in diastole"), _LEN, 0, ase=_T6, ase_row='lv.lvpwd', verified=True, synonyms=("LVPWd", "pw", "задняя стенка")),
    _m("lv.lvesd", ("КСР ЛЖ", "Конечно-систолический размер ЛЖ"),
       ("LVESD", "LV end-systolic dimension"), _LEN, 0, ase=_T6, ase_row='lv.lvesd', verified=True, synonyms=("LVIDs", "LVESD", "lvesd", "esd", "кср")),
    _m("lv.rwt", ("ОТС", "Относительная толщина стенок ЛЖ"), ("RWT", "Relative wall thickness"),
       Quantity.RATIO, 2, ase=_T6, ase_row='lv.rwt', verified=True),
    _m("lv.mass", ("ММЛЖ", "Масса миокарда ЛЖ"), ("LV mass", "LV mass"), Quantity.MASS, 0, ase=_CH2015, verified=True, synonyms=("LVM", "lvm")),
    _m("lv.mass_i", ("иММЛЖ", "Индекс массы миокарда ЛЖ"), ("LVMi", "LV mass index"),
       Quantity.INDEXED_MASS, 0, ase=_CH2015, verified=True, synonyms=("LVMI", "иммлж", "ИММЛЖ"), indexed=True),
    _m("lv.fs", ("ФУ", "Фракция укорочения ЛЖ"), ("LV FS", "Fractional shortening"), Quantity.PERCENT, 0, ase=_T6, ase_row='lv.fs', verified=True, synonyms=('FS',)),
    _m("lv.ef_teich", ("ФВ ЛЖ по Тейхольцу", "Фракция выброса ЛЖ по Тейхольцу"),
       ("LVEF Teichholz", "LV ejection fraction (Teichholz)"), Quantity.PERCENT, 0),
    _m("lv.edv_teich", ("КДО ЛЖ (Тейхольц)", "Конечно-диастолический объём ЛЖ по Тейхольцу"),
       ("LV EDV (Teichholz)", "LV end-diastolic volume (Teichholz)"), Quantity.VOLUME, 0, synonyms=("КДО ЛЖ (T)", "LV EDV (T)")),
    _m("lv.esv_teich", ("КСО ЛЖ (Тейхольц)", "Конечно-систолический объём ЛЖ по Тейхольцу"),
       ("LV ESV (Teichholz)", "LV end-systolic volume (Teichholz)"), Quantity.VOLUME, 0, synonyms=("КСО ЛЖ (T)", "LV ESV (T)")),
    _m("lv.gls_a4c", ("GLS ЛЖ · 4-кам.", "Глобальная продольная деформация ЛЖ, 4-камерная позиция"),
       ("LV GLS A4C", "LV global longitudinal strain, apical 4-chamber"), Quantity.PERCENT, 0, synonyms=("GLS A4C", "ГлобПродДеф 4C")),
    _m("lv.gls_a2c", ("GLS ЛЖ · 2-кам.", "Глобальная продольная деформация ЛЖ, 2-камерная позиция"),
       ("LV GLS A2C", "LV global longitudinal strain, apical 2-chamber"), Quantity.PERCENT, 0, synonyms=("GLS A2C", "ГлобПродДеф 2C")),
    # ── Simpson (protocol «Симпсон Биплан») ──
    _m("lv.edv_a4c", ("КДО · 4-кам.", "Конечно-диастолический объём ЛЖ, 4-камерная позиция"),
       ("LVEDV A4C", "LV end-diastolic volume, apical 4-chamber"), Quantity.VOLUME, 0, ase=_T6, ase_row='lv.lvedv', verified=True, synonyms=("Simpson 4C EDV", "Simpson 4C КДО", "edv 4c", "кдо 4")),
    _m("lv.esv_a4c", ("КСО · 4-кам.", "Конечно-систолический объём ЛЖ, 4-камерная позиция"),
       ("LVESV A4C", "LV end-systolic volume, apical 4-chamber"), Quantity.VOLUME, 0, ase=_T6, ase_row='lv.lvesv', verified=True, synonyms=("Simpson 4C ESV", "Simpson 4C КСО", "esv 4c", "ксо 4")),
    _m("lv.edv_a2c", ("КДО · 2-кам.", "Конечно-диастолический объём ЛЖ, 2-камерная позиция"),
       ("LVEDV A2C", "LV end-diastolic volume, apical 2-chamber"), Quantity.VOLUME, 0, ase=_T6, ase_row='lv.lvedv', verified=True, synonyms=("Simpson 2C EDV", "Simpson 2C КДО", "edv 2c", "кдо 2")),
    _m("lv.esv_a2c", ("КСО · 2-кам.", "Конечно-систолический объём ЛЖ, 2-камерная позиция"),
       ("LVESV A2C", "LV end-systolic volume, apical 2-chamber"), Quantity.VOLUME, 0, ase=_T6, ase_row='lv.lvesv', verified=True, synonyms=("Simpson 2C ESV", "Simpson 2C КСО", "esv 2c", "ксо 2")),
    _m("lv.edv_bp", ("КДО ЛЖ Биплан", "Конечно-диастолический объём ЛЖ, метод дисков Биплан"),
       ("LVEDV (biplane)", "LV end-diastolic volume, biplane method of disks"), Quantity.VOLUME, 0, ase=_T6, ase_row='lv.lvedv', verified=True, synonyms=("edv", "кдо", "simpson", "симпсон")),
    _m("lv.esv_bp", ("КСО ЛЖ Биплан", "Конечно-систолический объём ЛЖ, метод дисков Биплан"),
       ("LVESV (biplane)", "LV end-systolic volume, biplane method of disks"), Quantity.VOLUME, 0, ase=_T6, ase_row='lv.lvesv', verified=True, synonyms=("esv", "ксо")),
    _m("lv.ef_bp", ("ФВ ЛЖ Биплан", "Фракция выброса ЛЖ, метод дисков Биплан"),
       ("LV EF (biplane)", "LV ejection fraction, biplane method of disks"), Quantity.PERCENT, 0, ase=_T6, ase_row='lv.ef', verified=True, synonyms=('ef', 'lvef', 'фв', 'LVEF', 'LV EF')),
    _m("lv.edvi", ("иКДО", "Индекс конечно-диастолического объёма ЛЖ"),
       ("LVEDVi", "LV end-diastolic volume index"), Quantity.INDEXED_VOLUME, 0, ase=_T6, ase_row='lv.lvedvi', verified=True, synonyms=("EDVi", "ИКДО"), indexed=True),
    _m("lv.edvi_a4c", ("иКДО · 4-кам.", "Индекс конечно-диастолического объёма ЛЖ, 4-камерная позиция"),
       ("LVEDVi A4C", "LV end-diastolic volume index, apical 4-chamber"), Quantity.INDEXED_VOLUME, 0,
       synonyms=("EDVi 4C", "LVEDVi A4C"), indexed=True),
    _m("lv.edvi_a2c", ("иКДО · 2-кам.", "Индекс конечно-диастолического объёма ЛЖ, 2-камерная позиция"),
       ("LVEDVi A2C", "LV end-diastolic volume index, apical 2-chamber"), Quantity.INDEXED_VOLUME, 0,
       synonyms=("EDVi 2C", "LVEDVi A2C"), indexed=True),
    _m("lv.edvi_bp", ("иКДО Биплан", "Индекс конечно-диастолического объёма ЛЖ, метод дисков Биплан"),
       ("LVEDVi (biplane)", "LV end-diastolic volume index, biplane"), Quantity.INDEXED_VOLUME, 0,
       synonyms=("EDVi BP", "EDVi Bi"), indexed=True),
    _m("lv.esvi", ("иКСО", "Индекс конечно-систолического объёма ЛЖ"),
       ("LVESVi", "LV end-systolic volume index"), Quantity.INDEXED_VOLUME, 0, ase=_T6, ase_row='lv.lvesvi', verified=True, synonyms=("ESVi", "ИКСО"), indexed=True),
    _m("lv.esvi_a4c", ("иКСО · 4-кам.", "Индекс конечно-систолического объёма ЛЖ, 4-камерная позиция"),
       ("LVESVi A4C", "LV end-systolic volume index, apical 4-chamber"), Quantity.INDEXED_VOLUME, 0,
       synonyms=("ESVi 4C", "LVESVi A4C"), indexed=True),
    _m("lv.esvi_a2c", ("иКСО · 2-кам.", "Индекс конечно-систолического объёма ЛЖ, 2-камерная позиция"),
       ("LVESVi A2C", "LV end-systolic volume index, apical 2-chamber"), Quantity.INDEXED_VOLUME, 0,
       synonyms=("ESVi 2C", "LVESVi A2C"), indexed=True),
    _m("lv.esvi_bp", ("иКСО Биплан", "Индекс конечно-систолического объёма ЛЖ, метод дисков Биплан"),
       ("LVESVi (biplane)", "LV end-systolic volume index, biplane"), Quantity.INDEXED_VOLUME, 0,
       synonyms=("ESVi BP", "ESVi Bi"), indexed=True),
    _m("lv.sv", ("УО", "Ударный объём"), ("LV SV", "Stroke volume"), Quantity.VOLUME, 0, ase=_T6, ase_row='lv.sv', verified=True, synonyms=('SV',)),
    _m("lv.svi", ("иУО", "Индекс ударного объёма"), ("LV SVi", "Stroke volume index"), Quantity.INDEXED_VOLUME, 0, ase=_T6, ase_row='lv.svi', verified=True, synonyms=('ИУО', 'SVi'), indexed=True),
    # ── LA (protocol «Объём ЛП») ──
    _m("la.lav_a4c", ("ОЛП · 4-кам.", "Объём ЛП, 4-камерная позиция"), ("LAV A4C", "LA volume, apical 4-chamber"),
       Quantity.VOLUME, 0, ase=_T6, ase_row='la.vol', verified=True, synonyms=("LAV 4C", "ОЛП 4C", "lav")),
    _m("la.lav_a2c", ("ОЛП · 2-кам.", "Объём ЛП, 2-камерная позиция"), ("LAV A2C", "LA volume, apical 2-chamber"),
       Quantity.VOLUME, 0, ase=_T6, ase_row='la.vol', verified=True, synonyms=("LAV 2C", "ОЛП 2C")),
    _m("la.lav_bp", ("ОЛП Биплан", "Объём ЛП, метод дисков Биплан"), ("LAV (biplane)", "LA volume, biplane"),
       Quantity.VOLUME, 0, ase=_T6, ase_row='la.vol', verified=True),
    _m("la.lavi", ("иОЛП", "Индекс объёма ЛП"), ("LAVi", "LA volume index"), Quantity.INDEXED_VOLUME, 0, ase=_T6, ase_row='la.voli', verified=True, synonyms=("LAVI", "ИОЛП"), indexed=True),
    _m("la.lavi_a4c", ("иОЛП · 4-кам.", "Индекс объёма ЛП, 4-камерная позиция"),
       ("LAVi A4C", "LA volume index, apical 4-chamber"), Quantity.INDEXED_VOLUME, 0, synonyms=("LAVi 4C",), indexed=True),
    _m("la.lavi_bp", ("иОЛП Биплан", "Индекс объёма ЛП, метод дисков Биплан"),
       ("LAVi (biplane)", "LA volume index, biplane"), Quantity.INDEXED_VOLUME, 0, synonyms=("LAVi BP", "LAVi Bi"), indexed=True),
    _m("la.area", ("Площадь ЛП", "Площадь левого предсердия"), ("LA area", "Left atrial area"), Quantity.AREA, 2,
       synonyms=("S ЛП", "S LA", "LA area 4C")),
    _m("la.ap", ("ЛП ПЗР", "Переднезадний размер ЛП"), ("LA AP", "LA anteroposterior dimension"), _LEN, 0, ase=_T6, ase_row='la.ap', verified=True, synonyms=("LA", "лп")),
    # ── Aorta ──
    _m("av.d", ("АК", "Диаметр аортального клапана"), ("AV diam", "Aortic valve diameter"), _LEN, 0, ase=_AS2017, verified=True, synonyms=("AV",)),
    _m("ao.annulus", ("Кольцо АК", "Диаметр фиброзного кольца аортального клапана"),
       ("AoVAd", "Aortic annulus diameter"), _LEN, 0, ase=_T6, ase_row='aov.annulus_d', verified=True, synonyms=('Annulus', 'кольцо', 'Ao annulus', 'AoV annulus')),
    _m("ao.sinus", ("Синусы аорты", "Диаметр аорты на уровне синусов Вальсальвы"),
       ("AoSoV", "Sinus of Valsalva diameter"), _LEN, 0, ase=_T6, ase_row='ao.sov', verified=True, synonyms=('Ao Sinus', 'синус аорты', 'SoV')),
    _m("ao.stj", ("СТС", "Диаметр аорты на уровне синотубулярного соединения"),
       ("AoSTJ", "Sinotubular junction diameter"), _LEN, 0, ase=_T6, ase_row='ao.stj', verified=True, synonyms=('Ao Junction', 'переход', 'STJ')),
    _m("ao.asc", ("Восх. аорта", "Диаметр проксимального отдела восходящей аорты"),
       ("AoAsc", "Proximal ascending aorta diameter"), _LEN, 0, ase=_T6, ase_row='ao.asc', verified=True, synonyms=('Prox Ao', 'восходящая', 'Asc Ao')),
    # ── RA ──
    _m("ra.d", ("ПП", "Размер правого предсердия"), ("RA minor", "RA minor-axis dimension"), _LEN, 0, ase=_T6, ase_row='ra.minor', verified=True, synonyms=('RA',)),
    _m("ra.vol", ("ОПП", "Объём правого предсердия"), ("RAV", "RA volume"), Quantity.VOLUME, 0, ase=_T6, ase_row='ra.vol', verified=True, synonyms=("RAV",)),
    _m("ra.ravi", ("иОПП", "Индекс объёма правого предсердия"), ("RAVi", "RA volume index"), Quantity.INDEXED_VOLUME, 0,
       synonyms=("RAVi", "RA index"), indexed=True),
    _m("ra.area", ("Площадь ПП", "Площадь правого предсердия"), ("RA area", "Right atrial area"), Quantity.AREA, 2,
       synonyms=("S ПП", "S RA")),
    _m("ra.rap", ("ДПП", "Давление в правом предсердии"), ("RAP", "Right atrial pressure"), Quantity.PRESSURE, 0, ase=_T6, ase_row='ra.rap', verified=True),
    # ── RV ──
    _m("rv.rvot_prox", ("ВТПЖ", "Проксимальный диаметр выносящего тракта ПЖ"),
       ("RVOTd", "Proximal RVOT diameter"), _LEN, 0, ase=_T6, ase_row='rv.rvotd', verified=True, synonyms=('RVOT', 'RVOT prox')),
    _m("rv.basal", ("ПЖ базальный", "Базальный диаметр ПЖ"), ("RV basal", "RV basal diameter"), _LEN, 0, ase=_T6, ase_row='rv.basal', verified=True, synonyms=('RV Basal', 'RVD1', 'RVD basal')),
    _m("rv.mid", ("ПЖ средний", "Средний диаметр ПЖ"), ("RVD mid", "RV mid-cavity diameter"), _LEN, 0,
       synonyms=("RV Mid", "RVD2")),
    _m("rv.tapse", ("TAPSE", "Систолическая экскурсия кольца трикуспидального клапана"),
       ("TAPSE", "Tricuspid annular plane systolic excursion"), _LEN, 0, ase=_T6, ase_row='rv.tapse', verified=True),
    _m("rv.s_prime", ("s′ ПЖ", "Систолическая скорость кольца ТК (тканевой допплер)"),
       ("RV TDI s′", "Tricuspid annular systolic velocity (TDI)"), _VEL, 1, mode=CTX_TDI, ase=_T6, ase_row='rv.tdi_s_prime', verified=True, synonyms=("s' RV", "s' ПЖ", "S'", 'RV s′')),
    _m("rv.fac", ("ФИП ПЖ", "Фракционное изменение площади ПЖ"), ("RV FAC", "RV fractional area change"),
       Quantity.PERCENT, 0, ase=_T6, ase_row='rv.fac', verified=True, synonyms=("FAC", "FAC ПЖ")),
    _m("rv.rvsp", ("Сист. ДПЖ", "Систолическое давление в ПЖ"), ("RVSP", "RV systolic pressure"),
       Quantity.PRESSURE, 0, ase=_T6, ase_row='rv.rvsp', verified=True, synonyms=("СДПЖ",)),
    # ── Mitral inflow / diastolic function ──
    _m("mv.e", ("E", "Пиковая скорость волны E митрального потока"), ("MV E", "Mitral inflow E-wave velocity"), _VEL, 0, mode=CTX_PW, ase=_T6, ase_row='mv.e', verified=True, synonyms=('Peak E', 'пик e', 'E')),
    _m("mv.a", ("A", "Пиковая скорость волны A митрального потока"), ("MV A", "Mitral inflow A-wave velocity"), _VEL, 0, mode=CTX_PW, ase=_T6, ase_row='mv.a', verified=True, synonyms=('Peak A', 'пик a', 'A')),
    _m("mv.ea", ("E/A", "Отношение E/A"), ("MV E/A", "E/A ratio"), Quantity.RATIO,1, ase=_T6, ase_row='mv.ea', verified=True, synonyms=('MV E/A', 'E/A')),
    _m("mv.dt", ("DT", "Время замедления волны E"), ("DT", "E-wave deceleration time"), _TIM, 0, ase=_DIAS, verified=True, synonyms=("ВЗ", "deceleration")),
    _m("tdi.e_sept", ("e′ септ.", "Скорость e′ септальной части кольца МК"), ("e′ septal", "Septal e′ velocity"),
       _VEL, 1, mode=CTX_TDI, ase=_DIAS, verified=True, synonyms=("e'Sept", "e' sept", "e sept")),
    _m("tdi.e_lat", ("e′ лат.", "Скорость e′ латеральной части кольца МК"), ("e′ lateral", "Lateral e′ velocity"),
       _VEL, 1, mode=CTX_TDI, ase=_DIAS, verified=True, synonyms=("e'Lat", "e' lat", "e lat")),
    _m("tdi.e_avg", ("e′ ср.", "Средняя скорость e′"), ("e′ average", "Average e′ velocity"), _VEL, 1, mode=CTX_TDI, ase=_DIAS, verified=True, synonyms=("e' mean",)),
    _m("mv.e_e_avg", ("E/e′ ср.", "Отношение E к средней e′"), ("MV average E/e′", "E/e′ average"), Quantity.RATIO,0, ase=_T6, ase_row='mv.avg_e_e', verified=True, synonyms=("E/e' mean", 'E/e′ average')),
    _m("tdi.e_e_sept", ("E/e′ септ.", "Отношение E к септальной e′"), ("MV E/e′ septal", "E/e′ septal ratio"),
       Quantity.RATIO, 0, synonyms=("E/e' sept", "e/e′ септ")),
    _m("tdi.e_e_lat", ("E/e′ лат.", "Отношение E к латеральной e′"), ("MV E/e′ lateral", "E/e′ lateral ratio"),
       Quantity.RATIO, 0, synonyms=("E/e' lat", "e/e′ лат")),
    _m("tdi.s_prime_sept", ("s′ септ.", "Систолическая скорость септальной части кольца МК"),
       ("Septal s′ velocity", "Septal annular systolic velocity"), _VEL, 1, mode=CTX_TDI, synonyms=("s' sept",)),
    _m("tdi.s_prime_lat", ("s′ лат.", "Систолическая скорость латеральной части кольца МК"),
       ("Lateral s′ velocity", "Lateral annular systolic velocity"), _VEL, 1, mode=CTX_TDI, synonyms=("s' lat",)),
    _m("tdi.e_a_prime", ("e′/a′", "Отношение пиков скоростей e′ и a′"), ("MV e′/a′", "e′/a′ ratio"),
       Quantity.RATIO, 0, synonyms=("e'/a'", "e/a'")),
    _m("lv.ivrt", ("IVRT", "Время изоволюмического расслабления ЛЖ"), ("IVRT", "Isovolumic relaxation time"), _TIM, 0, ase=_DIAS, verified=True, synonyms=("ВИР",)),
    # ── Mitral valve ──
    _m("mv.vmax", ("Vmax МК", "Максимальная скорость через митральный клапан"), ("MV Vmax", "Mitral peak velocity"),
       _VEL, 1, mode=CTX_CW, ase=_MS2017, verified=True, synonyms=("МК Vmax",)),
    _m("mv.vti", ("VTI МК", "VTI митрального потока"), ("MV VTI", "Mitral VTI"), _VTI, 0, mode=CTX_CW, ase=_MS2017, verified=True, synonyms=("МК VTI",)),
    _m("mv.pht", ("ВПД МК", "Время полуспада градиента давления на МК"), ("MV PHT", "Mitral pressure half-time"),
       _TIM, 0, ase=_T6, ase_row='mv.pht', verified=True, synonyms=("МК PHT", "PHT")),
    _m("mv.pisa_r", ("Радиус PISA МС", "Радиус PISA при митральном стенозе"), ("PISA r MS", "PISA radius, MS"),
       _PIS,1, ase=_MS2017, verified=True, synonyms=("PISA MS", "PISA MS (радиус)", "PISA MS (radius)")),
    _m("mv.d", ("Диаметр кольца МК", "Диаметр кольца митрального клапана"), ("MV annulus diam", "Mitral annulus diameter"),
       _ORI,1, ase=_MR2017, verified=True, synonyms=("MVd",)),
    _m("mr.vmax", ("Vmax МР", "Максимальная скорость струи МР"), ("MR peak Vel", "MR peak velocity"), _VEL, 1, mode=CTX_CW, ase=_T6, ase_row='mr.peak_vel', verified=True, synonyms=('МР Vmax', 'MR Vmax')),
    _m("mr.vti", ("VTI МР", "VTI струи МР"), ("MR VTI", "MR VTI"), _VTI, 0, mode=CTX_CW, ase=_T6, ase_row='mr.vti', verified=True, synonyms=("МР VTI",)),
    _m("mr.dpdt", ("dP/dt ЛЖ", "dP/dt ЛЖ по струе МР (Δt 1→3 м/с)"), ("MR dp/dt", "LV dP/dt from the MR jet (Δt 1→3 m/s)"),
       Quantity.PRESSURE_RATE, 0, ase=_T6, ase_row='mr.dpdt', verified=True, synonyms=('MR dP/dt', 'МР dP/dt', 'МР dP/dt (Δt 1→3 м/с)', 'MR dP/dt (Δt 1→3 m/s)', 'LV dP/dt')),
    _m("mr.pisa_r", ("Радиус PISA МР", "Радиус PISA при митральной регургитации"), ("MR PISA r", "PISA radius, MR"),
       _PIS,1, ase=_T6, ase_row='mr.pisa_r', verified=True, synonyms=('PISA MR', 'PISA MR (радиус)', 'PISA MR (radius)', 'PISA r MR')),
    # ── Aortic valve (protocol «Аортальный стеноз») ──
    _m("lvot.d", ("Диаметр ВТЛЖ", "Диаметр выносящего тракта ЛЖ"), ("LVOTd", "LVOT diameter"), _ORI, 1, ase=_T6, ase_row='lv.lvotd', verified=True, synonyms=('LVOTd', 'lvot', 'LVOT diam')),
    _m("lvot.vti", ("VTI ВТЛЖ", "VTI выносящего тракта ЛЖ"), ("LVOT VTI", "LVOT VTI"), _VTI, 0, mode=CTX_PW, ase=_T6, ase_row='lv.lvot_vti', verified=True, synonyms=("ВТЛЖ VTI",)),
    _m("lvot.vmax", ("Vmax ВТЛЖ", "Максимальная скорость в выносящем тракте ЛЖ"), ("LVOT Vmax", "LVOT peak velocity"),
       _VEL, 0, mode=CTX_PW, ase=_AS2017, verified=True, synonyms=("ВТЛЖ Vmax",)),
    _m("av.vmax", ("Vmax АК", "Максимальная скорость через аортальный клапан"), ("AoV peak vel", "Aortic valve peak velocity"),
       _VEL, 1, mode=CTX_CW, ase=_T6, ase_row='aov.peak_vel', verified=True, synonyms=('АК Vmax', 'AVmax Vel', 'AV Vmax')),
    _m("av.vti", ("VTI АК", "VTI аортального клапана"), ("AoV VTI", "Aortic valve VTI"), _VTI, 0, mode=CTX_CW, ase=_T6, ase_row='aov.vti', verified=True, synonyms=('АК VTI', 'AV VTI')),
    _m("av.pg_peak", ("Град. макс. АК", "Максимальный градиент давления на АК"), ("AoV peak PG", "AV peak gradient"),
       Quantity.PRESSURE, 0, ase=_T6, ase_row='aov.peak_pg', verified=True, synonyms=('PGmax', 'AV PGmax', 'AV peak PG')),
    _m("av.pg_mean", ("Град. ср. АК", "Средний градиент давления на АК"), ("AoV mean PG", "AV mean gradient"),
       Quantity.PRESSURE, 0, ase=_T6, ase_row='aov.mean_pg', verified=True, synonyms=('AV Mean Gr', 'PGmean', 'АК сред. градиент', 'AV mean PG')),
    _m("av.ava_vti", ("Площадь АК", "Площадь аортального клапана (уравнение непрерывности, VTI)"),
       ("AVA (continuity)", "Aortic valve area, continuity equation (VTI)"), Quantity.AREA,1, ase=_T6, ase_row='aov.ava_continuity', verified=True, synonyms=('AVA', 'AVA (VTI)')),
    _m("av.avai", ("иПлощадь АК", "Индекс площади аортального клапана"), ("AVAi", "Aortic valve area index"),
       Quantity.INDEXED_AREA, 2, indexed=True, synonyms=("Площадь АК инд.",)),
    _m("av.dvi", ("DVI", "Безразмерный индекс (VTI ВТЛЖ / VTI АК)"), ("AoV DI", "Dimensionless index (LVOT VTI / AV VTI)"),
       Quantity.RATIO, 2, ase=_T6, ase_row='aov.di', verified=True, synonyms=('Безразм. индекс', 'DVI')),
    _m("av.at", ("Время уск. АК", "Время ускорения потока через АК"), ("AV AT", "Aortic acceleration time"), _TIM, 0, ase=_AS2017, verified=True, synonyms=("Время ускорения АК", "AV acceleration time")),
    _m("av.et", ("Время изгн. АК", "Время изгнания ЛЖ"), ("AV ET", "LV ejection time"), _TIM, 0,
       synonyms=("Время изгнания АК", "AV ejection time")),
    _m("ar.vmax", ("Vmax АР", "Максимальная скорость струи АР"), ("AR peak vel", "AR peak velocity"), _VEL, 1, mode=CTX_CW, ase=_T6, ase_row='ar.peak_vel', verified=True, synonyms=('АР Vmax', 'AR Vmax')),
    _m("ar.vti", ("VTI АР", "VTI струи АР"), ("AR VTI", "AR VTI"), _VTI, 0, mode=CTX_CW, ase=_AR2017, verified=True, synonyms=("АР VTI",)),
    _m("ar.pht", ("ВПД АР", "Время полуспада градиента давления АР"), ("AR PHT", "AR pressure half-time"), _TIM, 0, ase=_T6, ase_row='ar.pht', verified=True, synonyms=("АР PHT",)),
    _m("ar.pisa_r", ("Радиус PISA АР", "Радиус PISA при аортальной регургитации"), ("PISA r AR", "PISA radius, AR"),
       _PIS,1, ase=_AR2017, verified=True, synonyms=("PISA AR", "PISA AR (радиус)", "PISA AR (radius)")),
    # ── Tricuspid / pulmonary (protocol «ТР / Сист. ДЛА») ──
    _m("tv.vmax", ("Vmax ТК", "Максимальная скорость через трикуспидальный клапан"), ("TV Vmax", "Tricuspid peak velocity"),
       _VEL, 1, mode=CTX_CW, synonyms=("ТК Vmax",)),
    _m("tv.vti", ("VTI ТК", "VTI трикуспидального потока"), ("TV VTI", "Tricuspid VTI"), _VTI, 0, mode=CTX_CW, ase=_T6, ase_row='tv.vti', verified=True, synonyms=("ТК VTI",)),
    _m("tv.pht", ("ВПД ТК", "Время полуспада градиента давления на ТК"), ("TV PHT", "Tricuspid pressure half-time"),
       _TIM, 0, synonyms=("ТК PHT",)),
    _m("tr.vmax", ("Vmax ТР", "Максимальная скорость струи ТР"), ("TRmax Vel", "Peak TR velocity"), _VEL, 1, mode=CTX_CW, ase=_T6, ase_row='tr.peak_vel', verified=True, synonyms=("TR Vmax", "ТР Vmax", "TRpeak")),
    _m("tr.vti", ("VTI ТР", "VTI струи ТР"), ("TR VTI", "TR VTI"), _VTI, 0, mode=CTX_CW, ase=_T6, ase_row='tr.vti', verified=True, synonyms=("ТР VTI",)),
    _m("tr.pg", ("Град. ТР", "Максимальный градиент давления ТР"), ("TRmax PG", "Peak TR gradient"),
       Quantity.PRESSURE, 0, ase=_T6, ase_row='tr.peak_pg', verified=True, synonyms=("TR PGmax",)),
    _m("tr.dpdt", ("dP/dt ПЖ", "dP/dt ПЖ по струе ТР (Δt 1→2 м/с)"), ("RV dP/dt", "RV dP/dt from the TR jet (Δt 1→2 m/s)"),
       Quantity.PRESSURE_RATE, 0, synonyms=("TR dP/dt", "ТР dP/dt", "ТР dP/dt (Δt 1→2 м/с)", "TR dP/dt (Δt 1→2 m/s)")),
    _m("pa.pasp", ("Сист. ДЛА", "Систолическое давление в лёгочной артерии"), ("PASP", "Pulmonary artery systolic pressure"),
       Quantity.PRESSURE, 0, ase=_T6, ase_row='rv.pasp', verified=True, synonyms=("СДЛА", "pasp", "сдла")),
    _m("pa.mpap", ("Ср. ДЛА", "Среднее давление в лёгочной артерии"), ("mPAP", "Mean pulmonary artery pressure"),
       Quantity.PRESSURE, 0, ase=_RIGHT, verified=True),
    _m("pv.vmax", ("Vmax ЛК", "Максимальная скорость через клапан ЛА"), ("PV peak vel", "Pulmonic valve peak velocity"),
       _VEL, 1, mode=CTX_CW, ase=_T6, ase_row='pv.peak_vel', verified=True, synonyms=('ЛК Vmax', 'PV Vmax')),
    _m("pv.vti", ("VTI ЛК", "VTI клапана ЛА"), ("PV VTI", "Pulmonic valve VTI"), _VTI, 0, mode=CTX_CW, ase=_T6, ase_row='pv.vti', verified=True, synonyms=("ЛК VTI",)),
    _m("rvot.vmax", ("Vmax ВТПЖ", "Максимальная скорость в выносящем тракте ПЖ"), ("RVOT peak vel", "RVOT peak velocity"),
       _VEL, 0, mode=CTX_PW, ase=_T6, ase_row='rv.rvot_peak_vel', verified=True, synonyms=('ВТПЖ Vmax', 'RVOT Vmax')),
    _m("rvot.vti", ("VTI ВТПЖ", "VTI выносящего тракта ПЖ"), ("RVOT VTI", "RVOT VTI"), _VTI, 0, mode=CTX_PW, ase=_T6, ase_row='rv.rvot_vti', verified=True, synonyms=("ВТПЖ VTI",)),
    _m("rvot.d", ("Диаметр ВТПЖ", "Диаметр ВТПЖ в месте измерения VTI (для Qp)"), ("RVOTd", "RVOT diameter (for Qp)"),
       _ORI, 1, ase=_T6, ase_row='rv.rvotd', verified=True, synonyms=('RVOTd', 'RVOTd (для Qp)', 'RVOTd (for Qp)', 'RVOT diam')),
    _m("rvot.at", ("Время уск. ВТПЖ", "Время ускорения потока в ВТПЖ"), ("RVOT AccT", "RVOT acceleration time"), _TIM, 0, ase=_T6, ase_row='rv.rvot_acct', verified=True, synonyms=('PAAT', 'AcT', 'Время ускорения ВТПЖ (PAAT)', 'RVOT acceleration time (PAAT)', 'RVOT AT')),
    _m("pr.vmax", ("Vmax ЛР", "Максимальная скорость струи регургитации на ЛК"), ("PRmax Vel", "PR peak velocity"),
       _VEL, 1, mode=CTX_CW, ase=_T6, ase_row='pr.max_vel_diastolic', verified=True, synonyms=('ПР Vmax', 'PR Vmax')),
    _m("pr.vti", ("VTI ЛР", "VTI струи регургитации на ЛК"), ("PR VTI", "PR VTI"), _VTI, 0, mode=CTX_CW, ase=_RIGHT, verified=True, synonyms=("ПР VTI",)),
    _m("pr.pht", ("ВПД ЛР", "Время полуспада градиента давления регургитации на ЛК"), ("PR PHT", "PR pressure half-time"),
       _TIM, 0, ase=_T6, ase_row='pr.pht', verified=True, synonyms=("ПР PHT",)),
    # ── Strain ──
    _m("lv.gls", ("GLS ЛЖ", "Глобальная продольная деформация ЛЖ"), ("LV GLS", "LV global longitudinal strain"),
       Quantity.PERCENT, 1, ase=_T6, ase_row='lv.gls', verified=True, synonyms=("strain", "стрейн", "speckle")),
    # ── Vessels ──
    _m("vessel.psv", ("Vps", "Пиковая систолическая скорость"), ("PSV", "Peak systolic velocity"), _VEL, 1, mode=CTX_PW,
       synonyms=("PSV", "ПСС")),
    _m("vessel.edv", ("Ved", "Конечная диастолическая скорость"), ("EDV", "End-diastolic velocity"), _VEL, 1, mode=CTX_PW,
       synonyms=("EDV", "КДС")),
    _m("vessel.stenosis_d", ("Стеноз по диаметру", "Степень стеноза по диаметру"), ("Stenosis (diam)", "Diameter stenosis"),
       Quantity.PERCENT, 0, synonyms=("Стеноз по диаметру (%)", "Stenosis by diameter (%)")),
    _m("vessel.stenosis_area", ("Стеноз по площади", "Степень стеноза по площади"), ("Stenosis (area)", "Area stenosis"),
       Quantity.PERCENT, 0, synonyms=("Стеноз по площади (%)", "Stenosis by area (%)")),
    # ── General ──
    _m("hr", ("ЧСС", "Частота сердечных сокращений"), ("HR", "Heart rate"), Quantity.RATE, 0, ase=_T6, ase_row='hr', verified=True),
)  # fmt: skip

MEASUREMENTS: Mapping[str, MeasurementSpec] = MappingProxyType({m.id: m for m in _MEASUREMENT_LIST})

# ── Sections ────────────────────────────────────────────────────────


def _s(sid: str, legacy: str, ru: str, en: str, flags: frozenset[str] = frozenset()) -> SectionSpec:
    return SectionSpec(sid, legacy, _labels(ru, en), flags)


_SECTION_LIST: tuple[SectionSpec, ...] = (
    _s("general", "menu.general", "Общие", "General"),
    _s("lv", "menu.lv_diastole_group", "Левый желудочек", "Left Ventricle"),
    _s("lv_auto", "menu.lv_auto", "ЛЖ авто", "LV Auto", frozenset({FLAG_AI})),
    _s("aorta", "menu.aorta", "Аорта", "Aorta"),
    _s("la", "menu.la_group", "Левое предсердие", "Left Atrium"),
    _s("ra", "menu.ra_group", "Правое предсердие", "Right Atrium"),
    _s("rv", "menu.rv_group", "Правый желудочек", "Right Ventricle"),
    _s("diastolic", "menu.diastolic_group", "Диастолическая функция", "Diastolic Function"),
    _s("mv_av", "menu.mv_group", "Допплер МК/АК", "MV/AV Doppler"),
    _s("tv_pv", "menu.tv_group", "Допплер ТК/ЛК", "TV/PV Doppler"),
    _s("strain", "menu.strain_group", "Стрейн", "Strain", frozenset({FLAG_EXPERIMENTAL, "pref:show_strain"})),
    _s("vessels", "menu.vessels_group", "Сосуды", "Vessels"),
    _s("mmode", "menu.mmode_group", "М-режим", "M-Mode"),
)

SECTIONS: Mapping[str, SectionSpec] = MappingProxyType({s.id: s for s in _SECTION_LIST})
SECTION_BY_LEGACY_KEY: Mapping[str, str] = MappingProxyType({s.legacy_key: s.id for s in _SECTION_LIST})

# ── Tools ───────────────────────────────────────────────────────────

_A = ActionPayload
_2D = frozenset({CTX_2D})
_MM = frozenset({CTX_M})
_PW = frozenset({CTX_PW})
_CW = frozenset({CTX_CW})
_TDI = frozenset({CTX_TDI})
_VES = frozenset({CTX_VESSEL})
_DOP = frozenset(DOPPLER_CONTEXTS)
_SP = frozenset({REQ_SPATIAL})
_DC = frozenset({REQ_DOPPLER})
_MC = frozenset({REQ_MMODE})


def _t(
    tid: str,
    kind: ToolKind,
    section: str,
    label_key: str,
    payload: ActionPayload,
    contexts: frozenset[str],
    *,
    results: tuple[str, ...] | None = None,
    ru: tuple[str, str] | str | None = None,
    en: tuple[str, str] | str | None = None,
    synonyms: tuple[str, ...] = (),
    requires: frozenset[str] = frozenset(),
    flags: frozenset[str] = frozenset(),
    key: str | None = None,
    reference_id: str | None = None,
) -> ToolSpec:
    """A tool whose id is a measurement id inherits that measurement's labels."""
    if results is None:
        results = (tid,) if tid in MEASUREMENTS else ()
    if ru is None or en is None:
        if len(results) != 1:
            raise ValueError(f"{tid}: labels required for a tool with {len(results)} results")
        base = MEASUREMENTS[results[0]]
        ru = ru or (base.labels["ru"].short, base.labels["ru"].full)
        en = en or (base.labels["en"].short, base.labels["en"].full)
    return ToolSpec(
        id=tid,
        kind=kind,
        labels=_labels(ru, en),
        section=section,
        payload=payload,
        contexts=contexts,
        result_keys=results,
        synonyms=synonyms,
        requires=requires,
        flags=flags,
        default_key=key,
        label_key=label_key,
        reference_id=reference_id,
        legacy_ids=(payload.legacy_id,),
    )


_K = ToolKind
_AI = frozenset({FLAG_AI, "profile:full"})
_LA_AUTO = frozenset({FLAG_AI, "profile:full", FLAG_EXPERIMENTAL, "pref:show_la_auto"})
_STRAIN = frozenset({FLAG_EXPERIMENTAL, "pref:show_strain"})
_LV_ED = ("lv.ivsd", "lv.lvedd", "lv.lvpwd")
_MI = ("mv.e", "mv.dt", "mv.a", "mv.ea")

_TOOL_LIST: tuple[ToolSpec, ...] = (
    # ── General ──
    _t("tool.caliper", _K.DISTANCE, "general", "menu.caliper", _A("caliper"), _2D, key="L",
       ru=("Калипер", "Линейное измерение"), en=("Caliper", "Linear caliper"), requires=_SP,
       synonyms=("distance", "линейка", "расстояние")),
    _t("hr.auto", _K.AUTO, "general", "menu.heart_rate", _A("heart_rate"), _2D, results=("hr",),
       ru=("Авто-ЧСС", "ЧСС автоматически по кинопетле"), en=("Auto HR", "Automatic heart rate from the cine loop"), requires=frozenset({REQ_FRAME_TIMING}),
       synonyms=("Auto-HR", "Авто-ЧСС", "hr")),
    _t("hr.doppler", _K.INTERVAL, "general", "menu.doppler_heart_rate", _A(None, doppler_interval="RR"), _DOP,
       results=("hr",), ru=("ЧСС по допплеру", "ЧСС по интервалу RR на спектре"),
       en=("Doppler HR", "Heart rate from the RR interval on the spectrum"), requires=_DC, synonyms=("RR", "Doppler HR")),
    _t("tool.area", _K.AREA, "general", "menu.spline_area", _A("spline_area"), _2D, ru=("Площадь", "Площадь (сплайн)"),
       en=("Area", "Spline area"), requires=_SP, synonyms=("Spline Area", "planimetry", "планиметрия")),
    _t("tool.volume", _K.VOLUME, "general", "menu.spline_volume", _A("spline_volume"), _2D,
       ru=("Объём", "Объём (сплайн, метод дисков)"), en=("Volume", "Spline volume (method of disks)"), requires=_SP,
       synonyms=("Spline Volume",)),
    _t("tool.diameter_compare", _K.DISTANCE, "general", "menu.diameter_compare", _A("diameter_compare"), _2D,
       ru=("Сравнение диаметров", "Сравнение диаметров на двух клипах"),
       en=("Diameter compare", "Diameter comparison across two clips"), requires=_SP,
       flags=frozenset({FLAG_MULTIVIEW}), synonyms=("Diameter Compare",)),
    _t("tool.area_compare", _K.AREA, "general", "menu.area_compare", _A("area_compare"), _2D,
       ru=("Сравнение площадей", "Сравнение площадей на двух клипах"),
       en=("Area compare", "Area comparison across two clips"), requires=_SP,
       flags=frozenset({FLAG_MULTIVIEW}), synonyms=("Area Compare",)),
    # ── Left ventricle ──
    _t("lv.linear_ed", _K.DISTANCE, "lv", "menu.lv2d_all_diastole", _A("lv2d_all_diastole"), _2D, results=_LV_ED,
       ru=("МЖП · КДР ЛЖ · ЗСЛЖ", "МЖП, КДР ЛЖ и ЗСЛЖ в диастолу (В-режим)"),
       en=("IVSD · LVEDD · LVPWD", "IVSD, LVEDD and LVPWD in diastole (2D)"), requires=_SP,
       flags=frozenset({FLAG_SEQUENCE}),
       synonyms=("МЖП-КДР-ЗСЛЖ (2D)", "IVSd-LVIDd-LVPWd (2D)", "lvidd", "lvedd", "кдр", "linear")),
    _t("lv.lvesd", _K.DISTANCE, "lv", "menu.lv2d_es", _A("lv2d_es"), _2D, requires=_SP,
       synonyms=("КСР (2D)", "LVIDs (2D)")),
    _t("lv.edv_a4c", _K.VOLUME, "lv", "menu.simpson_ed_kdo", _A("manual_simpson", view="A4C", phase="ED"), _2D,
       requires=_SP),
    _t("lv.esv_a4c", _K.VOLUME, "lv", "menu.simpson_es_kso", _A("manual_simpson", view="A4C", phase="ES"), _2D,
       requires=_SP),
    _t("lv.edv_a2c", _K.VOLUME, "lv", "menu.simpson_biplane_kdo", _A("manual_simpson", view="A2C", phase="ED"), _2D,
       requires=_SP),
    _t("lv.esv_a2c", _K.VOLUME, "lv", "menu.simpson_biplane_kso", _A("manual_simpson", view="A2C", phase="ES"), _2D,
       requires=_SP),
    # ── LV auto (ONNX) ──
    _t("lv.edv_a4c.auto", _K.AUTO, "lv_auto", "menu.simpson_ed_kdo", _A("mbs_simpson", view="A4C", phase="ED"), _2D,
       results=("lv.edv_a4c",), ru=("КДО · 4-кам. авто", "КДО ЛЖ, 4-камерная позиция — автоконтур (ИИ)"),
       en=("LVEDV A4C auto", "LV end-diastolic volume, apical 4-chamber — auto contour (AI)"), requires=_SP,
       flags=_AI, synonyms=("Simpson 4C EDV", "Simpson 4C КДО", "auto", "авто", "ии")),
    _t("lv.esv_a4c.auto", _K.AUTO, "lv_auto", "menu.simpson_es_kso", _A("mbs_simpson", view="A4C", phase="ES"), _2D,
       results=("lv.esv_a4c",), ru=("КСО · 4-кам. авто", "КСО ЛЖ, 4-камерная позиция — автоконтур (ИИ)"),
       en=("LVESV A4C auto", "LV end-systolic volume, apical 4-chamber — auto contour (AI)"), requires=_SP,
       flags=_AI, synonyms=("Simpson 4C ESV", "Simpson 4C КСО", "auto", "авто", "ии")),
    # ── Aorta ──
    _t("av.d", _K.DISTANCE, "aorta", "menu.av", _A(None, caliper_label="AV"), _2D, requires=_SP),
    _t("ao.annulus", _K.DISTANCE, "aorta", "menu.annulus", _A(None, caliper_label="Annulus"), _2D, requires=_SP),
    _t("ao.sinus", _K.DISTANCE, "aorta", "menu.ao_sinus", _A(None, caliper_label="Ao Sinus"), _2D, requires=_SP),
    _t("ao.stj", _K.DISTANCE, "aorta", "menu.ao_junction", _A(None, caliper_label="Ao Junction"), _2D, requires=_SP),
    _t("ao.asc", _K.DISTANCE, "aorta", "menu.prox_ao", _A(None, caliper_label="Prox Ao"), _2D, requires=_SP),
    # ── Left atrium ──
    _t("la.ap", _K.DISTANCE, "la", "menu.la_lavir", _A("la_diameter"), _2D, requires=_SP),
    _t("la.lav_a4c", _K.VOLUME, "la", "menu.lav_4c", _A("lav_4c"), _2D, requires=_SP),
    _t("la.lav_a4c.ai_plus", _K.AUTO, "la", "menu.lav_4c_ai_plus", _A("lav_4c_ai_plus"), _2D, results=("la.lav_a4c",),
       ru=("ОЛП · 4-кам. ИИ+", "Объём ЛП, 4-камерная позиция — ИИ с уточнением"),
       en=("LAV A4C AI+", "LA volume, apical 4-chamber — AI with refinement"), requires=_SP, flags=_LA_AUTO,
       synonyms=("ОЛП 4C ИИ+", "LAV 4C AI+")),
    _t("la.lav_a4c.auto", _K.AUTO, "la", "menu.lav_4c_auto", _A("lav_4c_auto"), _2D, results=("la.lav_a4c",),
       ru=("ОЛП · 4-кам. ИИ", "Объём ЛП, 4-камерная позиция — ИИ"), en=("LAV A4C AI", "LA volume, apical 4-chamber — AI"),
       requires=_SP, flags=_LA_AUTO, synonyms=("ОЛП 4C ИИ", "LAV 4C AI")),
    _t("la.lav_a2c", _K.VOLUME, "la", "menu.lav_bi", _A("lav_bi"), _2D, requires=_SP),
    # ── Right atrium ──
    _t("ra.d", _K.DISTANCE, "ra", "menu.ra_diameter", _A("ra_diameter"), _2D, requires=_SP),
    _t("ra.vol", _K.VOLUME, "ra", "menu.rav_volume", _A("rav_volume"), _2D, requires=_SP),
    # ── Right ventricle ──
    _t("rv.rvot_prox", _K.DISTANCE, "rv", "menu.rv_rvot", _A(None, caliper_label="RVOT"), _2D, requires=_SP),
    _t("rv.basal", _K.DISTANCE, "rv", "menu.rv_basal", _A("rv_basal"), _2D, requires=_SP),
    _t("rv.mid", _K.DISTANCE, "rv", "menu.rv_mid", _A(None, caliper_label="RV mid"), _2D, requires=_SP),
    _t("rv.tapse", _K.DISTANCE, "rv", "menu.rv_tapse", _A("rv_tapse"), frozenset({CTX_M, CTX_2D}),
       requires=frozenset({REQ_MMODE})),
    _t("rv.s_prime", _K.PEAK, "rv", "menu.s_prime_rv", _A("rv_s_prime"), _TDI, requires=_DC),
    _t("rv.fac", _K.AREA, "rv", "menu.rv_fac", _A("rv_fac", view="A4C"), _2D, requires=_SP),
    # ── Diastolic function ──
    _t("mv.inflow", _K.PEAK, "diastolic", "menu.mitral_inflow", _A("doppler_mitral_inflow"), _PW, results=_MI,
       ru=("Митральный поток", "Митральный поток: E, DT, A"), en=("Mitral inflow", "Mitral inflow: E, DT, A"),
       requires=_DC, flags=frozenset({FLAG_SEQUENCE}), synonyms=("Mitral Inflow", "e/a")),
    _t("mv.e", _K.PEAK, "diastolic", "menu.peak_e", _A(None, doppler_peak="E"), _PW, requires=_DC),
    _t("mv.a", _K.PEAK, "diastolic", "menu.peak_a", _A(None, doppler_peak="A"), _PW, requires=_DC),
    _t("mv.dt", _K.INTERVAL, "diastolic", "menu.dt", _A(None, doppler_interval="DT"), _PW, requires=_DC),
    _t("tdi.e_sept", _K.PEAK, "diastolic", "menu.e_sept", _A(None, doppler_peak="e_sept"), _TDI, requires=_DC),
    _t("tdi.e_lat", _K.PEAK, "diastolic", "menu.e_lat", _A(None, doppler_peak="e_lat"), _TDI, requires=_DC),
    _t("lv.ivrt", _K.INTERVAL, "diastolic", "menu.ivrt", _A(None, doppler_interval="IVRT"), _PW, requires=_DC),
    # ── MV / AV Doppler ──
    _t("mv.vmax", _K.PEAK, "mv_av", "menu.mv_vmax", _A(None, doppler_peak="MV Vmax"), _CW, requires=_DC),
    _t("mv.vti", _K.TRACE, "mv_av", "menu.mv_vti", _A(None, doppler_trace="MV VTI"), _CW, requires=_DC),
    _t("mv.pht", _K.INTERVAL, "mv_av", "menu.mv_pht", _A(None, doppler_interval="MV PHT"), _CW, requires=_DC),
    _t("mv.pisa_r", _K.DISTANCE, "mv_av", "menu.pisa_ms", _A(None, caliper_label="PISA MS"), _2D, requires=_SP),
    _t("mr.vmax", _K.PEAK, "mv_av", "menu.mr_vmax", _A(None, doppler_peak="MR Vmax"), _CW, requires=_DC),
    _t("mr.vti", _K.TRACE, "mv_av", "menu.mr_vti", _A(None, doppler_trace="MR VTI"), _CW, requires=_DC),
    _t("mr.dpdt", _K.INTERVAL, "mv_av", "menu.mr_dpdt", _A(None, doppler_interval="MR dP/dt"), _CW, requires=_DC),
    _t("mr.pisa_r", _K.DISTANCE, "mv_av", "menu.pisa_mr", _A(None, caliper_label="PISA MR"), _2D, requires=_SP),
    _t("av.vmax", _K.PEAK, "mv_av", "menu.av_vmax", _A(None, doppler_peak="AV Vmax"), _CW, requires=_DC),
    _t("av.vti", _K.TRACE, "mv_av", "menu.av_vti", _A(None, doppler_trace="AV VTI"), _CW, requires=_DC),
    _t("av.vti.auto", _K.AUTO, "mv_av", "menu.trace_auto_region_av",
       _A("doppler_trace_auto_region", doppler_trace="AV VTI"), _CW, results=("av.vti",),
       ru=("Автотрасса VTI АК", "Автоматическая трассировка VTI АК в выбранной области"),
       en=("Auto-trace AV VTI", "Automatic AV VTI trace in a selected region"), requires=_DC,
       synonyms=("Автотрассировка АК VTI", "auto")),
    _t("av.at", _K.INTERVAL, "mv_av", "menu.av_at", _A(None, doppler_interval="AV AT"), _CW, requires=_DC),
    _t("av.et", _K.INTERVAL, "mv_av", "menu.av_et", _A(None, doppler_interval="AV ET"), _CW, requires=_DC),
    _t("lvot.vmax", _K.PEAK, "mv_av", "menu.lvot_vmax", _A(None, doppler_peak="LVOT Vmax"), _PW, requires=_DC),
    _t("lvot.vti", _K.TRACE, "mv_av", "menu.lvot_vti", _A(None, doppler_trace="LVOT VTI"), _PW, requires=_DC),
    _t("ar.vmax", _K.PEAK, "mv_av", "menu.ar_vmax", _A(None, doppler_peak="AR Vmax"), _CW, requires=_DC),
    _t("ar.vti", _K.TRACE, "mv_av", "menu.ar_vti", _A(None, doppler_trace="AR VTI"), _CW, requires=_DC),
    _t("ar.pht", _K.INTERVAL, "mv_av", "menu.ar_pht", _A(None, doppler_interval="AR PHT"), _CW, requires=_DC),
    _t("ar.pisa_r", _K.DISTANCE, "mv_av", "menu.pisa_ar", _A(None, caliper_label="PISA AR"), _2D, requires=_SP),
    _t("lvot.d", _K.DISTANCE, "mv_av", "menu.lvotd", _A(None, caliper_label="LVOTd"), _2D, requires=_SP),
    _t("mv.d", _K.DISTANCE, "mv_av", "menu.mvd", _A(None, caliper_label="MVd"), _2D, requires=_SP),
    # ── TV / PV Doppler ──
    _t("tv.vmax", _K.PEAK, "tv_pv", "menu.tv_vmax", _A(None, doppler_peak="TV Vmax"), _CW, requires=_DC),
    _t("tv.vti", _K.TRACE, "tv_pv", "menu.tv_vti", _A(None, doppler_trace="TV VTI"), _CW, requires=_DC),
    _t("tv.pht", _K.INTERVAL, "tv_pv", "menu.tv_pht", _A(None, doppler_interval="TV PHT"), _CW, requires=_DC),
    _t("tr.vmax", _K.PEAK, "tv_pv", "menu.tr_vmax", _A(None, doppler_peak="TR Vmax"), _CW, requires=_DC),
    _t("tr.vti", _K.TRACE, "tv_pv", "menu.tr_vti", _A(None, doppler_trace="TR VTI"), _CW, requires=_DC),
    _t("tr.dpdt", _K.INTERVAL, "tv_pv", "menu.tr_dpdt", _A(None, doppler_interval="TR dP/dt"), _CW, requires=_DC),
    _t("tr.vti.auto", _K.AUTO, "tv_pv", "menu.trace_auto_region_tr",
       _A("doppler_trace_auto_region", doppler_trace="TR VTI"), _CW, results=("tr.vti",),
       ru=("Автотрасса VTI ТР", "Автоматическая трассировка VTI ТР в выбранной области"),
       en=("Auto-trace TR VTI", "Automatic TR VTI trace in a selected region"), requires=_DC,
       synonyms=("Автотрассировка ТР VTI", "auto")),
    _t("pv.vmax", _K.PEAK, "tv_pv", "menu.pv_vmax", _A(None, doppler_peak="PV Vmax"), _CW, requires=_DC),
    _t("pv.vti", _K.TRACE, "tv_pv", "menu.pv_vti", _A(None, doppler_trace="PV VTI"), _CW, requires=_DC),
    _t("rvot.vmax", _K.PEAK, "tv_pv", "menu.rvot_vmax", _A(None, doppler_peak="RVOT Vmax"), _PW, requires=_DC),
    _t("rvot.vti", _K.TRACE, "tv_pv", "menu.rvot_vti", _A(None, doppler_trace="RVOT VTI"), _PW, requires=_DC),
    _t("rvot.d", _K.DISTANCE, "tv_pv", "menu.rvotd", _A(None, caliper_label="RVOTd"), _2D, requires=_SP),
    _t("rvot.at", _K.INTERVAL, "tv_pv", "menu.rvot_at", _A(None, doppler_interval="RVOT AT"), _PW, requires=_DC),
    _t("pr.vmax", _K.PEAK, "tv_pv", "menu.pr_vmax", _A(None, doppler_peak="PR Vmax"), _CW, requires=_DC),
    _t("pr.vti", _K.TRACE, "tv_pv", "menu.pr_vti", _A(None, doppler_trace="PR VTI"), _CW, requires=_DC),
    _t("pr.pht", _K.INTERVAL, "tv_pv", "menu.pr_pht", _A(None, doppler_interval="PR PHT"), _CW, requires=_DC),
    # ── Strain (experimental) ──
    _t("ste.view_a4c", _K.ACTION, "strain", "menu.strain_pos_a4c", _A("ste_view_a4c"), _2D,
       ru=("Позиция 4-кам.", "Стрейн: апикальная 4-камерная позиция"), en=("A4C view", "Strain: apical 4-chamber view"),
       flags=_STRAIN, synonyms=("Позиция A4C", "Position A4C")),
    _t("ste.view_a2c", _K.ACTION, "strain", "menu.strain_pos_a2c", _A("ste_view_a2c"), _2D,
       ru=("Позиция 2-кам.", "Стрейн: апикальная 2-камерная позиция"), en=("A2C view", "Strain: apical 2-chamber view"),
       flags=_STRAIN, synonyms=("Позиция A2C", "Position A2C")),
    _t("ste.view_a3c", _K.ACTION, "strain", "menu.strain_pos_a3c", _A("ste_view_a3c"), _2D,
       ru=("Позиция 3-кам.", "Стрейн: апикальная 3-камерная позиция"), en=("A3C view", "Strain: apical 3-chamber view"),
       flags=_STRAIN, synonyms=("Позиция A3C", "Position A3C")),
    _t("ste.run", _K.AUTO, "strain", "menu.speckle_tracking", _A("speckle_tracking", view="A4C"), _2D,
       results=("lv.gls",), ru=("Спекл-трекинг", "Спекл-трекинг: продольная деформация ЛЖ"),
       en=("Speckle tracking", "Speckle tracking: LV longitudinal strain"), requires=_SP, flags=_STRAIN,
       synonyms=("Speckle Tracking", "ste", "gls", "стрейн")),
    # ── Vessels ──
    _t("vessel.psv_edv", _K.PEAK, "vessels", "menu.vessel_psv_edv", _A("vessel_psv_edv", vessel=True), _VES,
       results=("vessel.psv", "vessel.edv"), ru=("Vps / Ved", "Пиковая систолическая и конечная диастолическая скорость"),
       en=("PSV / EDV", "Peak systolic and end-diastolic velocity"), requires=_DC, flags=frozenset({FLAG_SEQUENCE}),
       synonyms=("PSV/EDV", "ПСС", "КДС")),
    _t("vessel.trace_up", _K.AUTO, "vessels", "menu.vessel_auto_trace_up", _A("vessel_auto_trace_up", vessel=True),
       _VES, results=("vessel.psv", "vessel.edv"), ru=("Автотрасса вверх", "Автотрассировка спектра выше изолинии"),
       en=("Auto-trace up", "Automatic trace above the baseline"), requires=_DC, synonyms=("Auto-Trace Вверх",)),
    _t("vessel.trace_down", _K.AUTO, "vessels", "menu.vessel_auto_trace_down",
       _A("vessel_auto_trace_down", vessel=True), _VES, results=("vessel.psv", "vessel.edv"),
       ru=("Автотрасса вниз", "Автотрассировка спектра ниже изолинии"),
       en=("Auto-trace down", "Automatic trace below the baseline"), requires=_DC, synonyms=("Auto-Trace Вниз",)),
    _t("vessel.average", _K.ACTION, "vessels", "menu.vessel_average", _A("vessel_average", vessel=True), _VES,
       ru=("Среднее по 3 циклам", "Усреднение по трём сердечным циклам"),
       en=("Average 3 cycles", "Average over three cardiac cycles")),
    _t("vessel.stenosis_d", _K.DISTANCE, "vessels", "menu.vessel_stenosis_diameter",
       _A("vessel_stenosis_diameter", vessel=True), _2D, requires=_SP),
    _t("vessel.stenosis_area", _K.AREA, "vessels", "menu.vessel_stenosis_area",
       _A("vessel_stenosis_area", vessel=True), _2D, requires=_SP),
    _t("vessel.clear", _K.ACTION, "vessels", "menu.vessel_clear", _A("vessel_clear", vessel=True), _VES,
       ru=("Очистить", "Очистить измерения сосуда"), en=("Clear", "Clear the vessel measurements")),
    _t("vessel.accept", _K.ACTION, "vessels", "menu.vessel_accept", _A("vessel_accept", vessel=True), _VES,
       ru=("Принять", "Принять измерения сосуда"), en=("Accept", "Accept the vessel measurements")),
    # ── M-mode ──
    _t("mmode.anatomic", _K.ACTION, "mmode", "menu.mmode_anatomic", _A("mmode"), _2D,
       ru=("Анатомический М-режим", "Построить анатомический М-режим по линии"),
       en=("Anatomic M-mode", "Build an anatomic M-mode along a line"), synonyms=("Anatomic M-Mode",)),
    _t("mmode.caliper", _K.DISTANCE, "mmode", "menu.mmode_caliper", _A("mmode_caliper"), _MM,
       ru=("Калипер М-режима", "Линейное измерение в М-режиме"), en=("M-mode caliper", "M-mode linear caliper"),
       requires=_MC, synonyms=("M-Mode Caliper",)),
    _t("mmode.time_hr", _K.INTERVAL, "mmode", "menu.mmode_time_hr", _A("mmode_time_hr"), _MM, results=("hr",),
       ru=("Время / ЧСС", "Интервал времени и ЧСС в М-режиме"), en=("Time / HR", "Time interval and heart rate in M-mode"),
       requires=_MC),
    _t("lv.linear_ed.m", _K.DISTANCE, "mmode", "menu.teichholz_ed", _A("teichholz_ed"), _MM, results=_LV_ED,
       ru=("МЖП · КДР ЛЖ · ЗСЛЖ", "МЖП, КДР ЛЖ и ЗСЛЖ в диастолу (М-режим)"),
       en=("IVSD · LVEDD · LVPWD", "IVSD, LVEDD and LVPWD in diastole (M-mode)"), requires=_MC,
       flags=frozenset({FLAG_SEQUENCE}), synonyms=("МЖП-КДР-ЗСЛЖ", "IVSd-LVIDd-LVPWd", "teichholz", "тейхольц")),
    _t("lv.lvesd.m", _K.DISTANCE, "mmode", "menu.teichholz_es", _A("teichholz_es"), _MM, results=("lv.lvesd",),
       ru=("КСР ЛЖ", "Конечно-систолический размер ЛЖ (М-режим)"), en=("LVESD", "LV end-systolic dimension (M-mode)"),
       requires=_MC, synonyms=("КСР", "LVIDs", "teichholz")),
)  # fmt: skip

CATALOG: Mapping[str, ToolSpec] = MappingProxyType({t.id: t for t in _TOOL_LIST})

#: ``legacy tool_id`` (layout v2) → stable catalog id.
LEGACY_ALIASES: Mapping[str, str] = MappingProxyType(
    {legacy: tool.id for tool in _TOOL_LIST for legacy in tool.legacy_ids}
)


def tools_in_section(section_id: str) -> tuple[ToolSpec, ...]:
    """Tools of a built-in section, in the default order."""
    return tuple(tool for tool in _TOOL_LIST if tool.section == section_id)


def catalog_id_for_legacy(legacy_id: str) -> str | None:
    """Stable id for a layout-v2 ``tool_id``; ``None`` when unknown."""
    return LEGACY_ALIASES.get(legacy_id)


#: Internal caliper label (``LinearMeasurement.label``) → measurement id.
#: The viewer stores fixed labels (``IVSd``/``LVEDD``…); this map is the single
#: source for the projection of protocols and the report (D-11/D-12) so the two
#: directions never drift.
CALIPER_TO_MEASUREMENT: Mapping[str, str] = MappingProxyType(
    {
        "IVSd": "lv.ivsd",
        "IVSD": "lv.ivsd",
        "LVEDD": "lv.lvedd",
        "LVPWd": "lv.lvpwd",
        "LVPWD": "lv.lvpwd",
        "LVESD": "lv.lvesd",
        "LVOTd": "lvot.d",
        "LA": "la.ap",
    }
)


def measurement_for_caliper(label: str) -> str | None:
    """Measurement id of a caliper label; ``None`` when the label is unknown."""
    return CALIPER_TO_MEASUREMENT.get(label)


def tools_for_context(context: str) -> tuple[ToolSpec, ...]:
    """Tools available in a viewer context (``2d``, ``m``, ``pw`` …)."""
    if context not in CONTEXTS:
        raise ValueError(f"unknown context: {context!r}")
    return tuple(tool for tool in _TOOL_LIST if context in tool.contexts)


def validate_catalog() -> list[str]:
    """Consistency problems of the catalog (empty list = consistent)."""
    problems: list[str] = []
    if len(CATALOG) != len(_TOOL_LIST):
        problems.append("duplicate tool ids")
    if len(MEASUREMENTS) != len(_MEASUREMENT_LIST):
        problems.append("duplicate measurement ids")
    if len(LEGACY_ALIASES) != sum(len(t.legacy_ids) for t in _TOOL_LIST):
        problems.append("one legacy id maps to several tools")
    for tool in _TOOL_LIST:
        if tool.section not in SECTIONS:
            problems.append(f"{tool.id}: unknown section {tool.section}")
        if not tool.contexts or not tool.contexts <= set(CONTEXTS):
            problems.append(f"{tool.id}: bad contexts {sorted(tool.contexts)}")
        for key in tool.result_keys:
            if key not in MEASUREMENTS:
                problems.append(f"{tool.id}: unknown result {key}")
        if tool.kind is not ToolKind.ACTION and tool.kind not in (ToolKind.DISTANCE, ToolKind.AREA, ToolKind.VOLUME):
            if not tool.result_keys:
                problems.append(f"{tool.id}: {tool.kind} tool without results")
    return problems
