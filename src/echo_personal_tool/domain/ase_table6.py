"""ASE 2025 «Measurement dictionary» (Table 6) as reference data (TP-0 PR-3).

Source: Taub CC, Stainback RF et al. *Guidelines for the Standardization of
Adult Echocardiography Reporting.* J Am Soc Echocardiogr 2025;38(9):735–774,
doi:10.1016/j.echo.2025.06.001 — Table 6 «Measurement dictionary»
(название, сокращение, единица, рекомендуемое число знаков).

The module is **pure data** (no Qt, no imports from the application): the
catalog (:mod:`echo_personal_tool.domain.measurement_catalog`) points at the
rows it uses, and the test suite checks that every pointer is consistent.

Notation: units are written as in the catalog (``mL``, ``mmHg``, ``cm²``,
``mL/m²``); ASE prints ``ml``, ``mm Hg``, ``cm^2``, ``ml/m^2``.  A row without
an abbreviation in ASE (the table prints ``N/A``) has an empty
:attr:`Table6Row.abbreviation`.

The table is a *reference*, not the display rule of the application:

* linear dimensions are shown in **mm** by default (D-12) — the ASE unit
  (``cm``) is the «см (ASE)» mode of TP-1;
* spectral velocities are **cm/s** for PW and TDI, **m/s** for CW (D-05/D-17) —
  ASE writes ``m/s`` for the mitral/tricuspid inflow velocities;
* the deviations of the project from the table are listed in
  :data:`ASE_UNIT_DEVIATIONS` with a reason — nothing deviates silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Table6Row:
    """One row of the ASE 2025 measurement dictionary."""

    id: str
    name: str
    abbreviation: str
    unit: str
    decimals: int
    section: str


def _rows(items: tuple[tuple[str, str, str, str, int, str], ...]) -> tuple[Table6Row, ...]:
    return tuple(Table6Row(*item) for item in items)


TABLE6_ROWS: tuple[Table6Row, ...] = _rows(
    (
        # ── Left ventricle ──
        ("lv.lvedd", "LV end-diastolic dimension", "LVEDD", "cm", 1, "lv"),
        ("lv.lvesd", "LV end-systolic dimension", "LVESD", "cm", 1, "lv"),
        ("lv.ivsd", "Interventricular septal wall diastolic dimension", "IVSD", "cm", 1, "lv"),
        ("lv.lvpwd", "LV posterior wall diastolic dimension", "LVPWD", "cm", 1, "lv"),
        ("lv.rwt", "Relative wall thickness", "RWT", "", 2, "lv"),
        ("lv.lvedv", "LV end-diastolic volume", "LVEDV", "mL", 0, "lv"),
        ("lv.lvedvi", "LV end-diastolic volume index", "LVEDVi", "mL/m²", 0, "lv"),
        ("lv.lvesv", "LV end-systolic volume", "LVESV", "mL", 0, "lv"),
        ("lv.lvesvi", "LV end-systolic volume index", "LVESVi", "mL/m²", 0, "lv"),
        ("lv.ef", "LV ejection fraction", "LV EF", "%", 0, "lv"),
        ("lv.fs", "LV fractional shortening", "LV FS", "%", 0, "lv"),
        ("lv.lvotd", "Left ventricular outflow tract diameter", "LVOTd", "cm", 1, "lv"),
        ("lv.lvot_vti", "Left ventricular outflow tract velocity time integral", "LVOT VTI", "cm", 0, "lv"),
        ("lv.lvot_peak_pg_rest", "LVOT peak gradient at rest", "LVOT peak PG (rest)", "mmHg", 0, "lv"),
        ("lv.lvot_peak_pg_valsalva", "LVOT peak gradient (Valsalva)", "LVOT peak PG (Valsalva)", "mmHg", 0, "lv"),
        ("lv.lvot_mean_pg", "LVOT mean gradient", "LVOT mean PG", "mmHg", 0, "lv"),
        ("lv.sv", "LV stroke volume", "LV SV", "mL", 0, "lv"),
        ("lv.svi", "LV stroke volume index", "LV SVi", "mL/m²", 0, "lv"),
        ("lv.co", "Cardiac output", "CO", "l/min", 1, "lv"),
        ("lv.ci", "Cardiac index", "CI", "l/min/m²", 1, "lv"),
        ("lv.gls", "Left ventricular global longitudinal strain", "LV GLS", "%", 1, "lv"),
        # ── Mitral valve ──
        ("mv.e", "MV E wave velocity", "MV E", "m/s", 2, "mv"),
        ("mv.a", "MV A wave velocity", "MV A", "m/s", 2, "mv"),
        ("mv.ea", "MV E/A ratio", "MV E/A", "", 1, "mv"),
        ("mv.pwd_annulus", "MV PWD velocity at annulus", "", "m/s", 2, "mv"),
        ("mv.medial_e_e", "MV wave velocity to medial (septal) e′ velocity ratio", "MV medial E/e′", "", 0, "mv"),
        ("mv.avg_e_e", "MV average lateral E/e′ and medial E/e′", "MV average E/e′", "", 0, "mv"),
        ("mv.peak_pg", "MV peak pressure gradient", "MV peak PG", "mmHg", 0, "mv"),
        ("mv.mean_pg", "MV mean pressure gradient", "MV mean PG", "mmHg", 0, "mv"),
        ("mv.pht", "MV pressure half-time", "MV PHT", "ms", 0, "mv"),
        ("mv.eroa_3d", "3D MR EROA", "3D MR EROA", "cm²", 2, "mv"),
        # ── Mitral regurgitation ──
        ("mr.peak_vel", "MR peak velocity", "MR peak Vel", "m/s", 1, "mr"),
        ("mr.vti", "MR velocity time integral", "MR VTI", "cm", 0, "mr"),
        ("mr.peak_pg", "MR peak pressure gradient", "MR peak PG", "mmHg", 0, "mr"),
        ("mr.dpdt", "MR dp/dt", "MR dp/dt", "mmHg/s", 0, "mr"),
        ("mr.vc", "MR vena contracta", "MR VC", "cm", 1, "mr"),
        ("mr.vca_3d", "3D MR vena contracta area", "3D MR VCA", "cm²", 2, "mr"),
        ("mr.pisa_r", "MR PISA radius", "MR PISA r", "cm", 1, "mr"),
        ("mr.pisa_aliasing_vel", "MR PISA aliasing velocity", "MR PISA aliasing vel", "cm/s", 1, "mr"),
        ("mr.pisa_eroa", "MR PISA EROA", "MR PISA EROA", "cm²", 2, "mr"),
        # ── Aortic valve / aortic regurgitation ──
        ("aov.peak_vel", "AoV peak velocity", "AoV peak vel", "m/s", 1, "aov"),
        ("aov.peak_pg", "AoV peak gradient", "AoV peak PG", "mmHg", 0, "aov"),
        ("aov.mean_pg", "AoV mean gradient", "AoV mean PG", "mmHg", 0, "aov"),
        ("aov.ava_continuity", "AoV area (continuity equation)", "AVA (continuity)", "cm²", 1, "aov"),
        ("aov.annulus_area_planimetry", "AoV annulus area (planimetry)", "AoVAA (planimetry)", "cm²", 1, "aov"),
        ("aov.annulus_d", "AoV annulus diameter", "AoVAd", "cm", 1, "aov"),
        ("aov.vti", "AoV velocity time integral", "AoV VTI", "cm", 0, "aov"),
        ("aov.di", "AoV dimensionless index (either by velocity or by VTI)", "AoV DI", "", 2, "aov"),
        ("aov.acct", "AoV prosthesis acceleration time", "AoV AccT", "ms", 0, "aov"),
        ("ar.vc", "AR vena contracta", "AR VC", "cm", 1, "ar"),
        ("ar.vca_3d", "3D AR vena contracta area", "3D AR VCA", "cm²", 2, "ar"),
        ("ar.peak_vel", "AR peak velocity", "AR peak vel", "m/s", 1, "ar"),
        ("ar.pht", "AR pressure half-time", "AR PHT", "ms", 0, "ar"),
        # ── Tricuspid valve / tricuspid regurgitation ──
        ("tv.e", "TV peak E-wave velocity", "TV E", "m/s", 2, "tv"),
        ("tv.a", "TV peak A-wave velocity", "TV A", "m/s", 2, "tv"),
        ("tv.ea", "TV E/A ratio", "TV E/A", "", 1, "tv"),
        ("tv.pwd_annulus", "TV PWD velocity at annulus", "", "m/s", 2, "tv"),
        ("tv.e_prime", "Tricuspid lateral annulus e′ velocity", "TV e′", "cm/s", 1, "tv"),
        ("tv.e_e_prime", "TV E/e′ ratio", "TV E/e′", "", 1, "tv"),
        ("tv.peak_pg", "TV peak pressure gradient", "TV peak PG", "mmHg", 0, "tv"),
        ("tv.mean_pg", "TV mean pressure gradient", "TV mean PG", "mmHg", 0, "tv"),
        ("tv.vti", "TV velocity time integral", "TV VTI", "cm", 0, "tv"),
        ("tv.oa_pisa", "TV orifice area (PISA)", "TVOA (PISA)", "cm²", 1, "tv"),
        ("tv.oa_continuity", "TV orifice area (continuity equation)", "TVOA (continuity)", "cm²", 1, "tv"),
        ("tv.oa_planimetry", "TV orifice area (planimetry)", "TVOA (planimetry)", "cm²", 1, "tv"),
        ("tv.oa_3d", "3D TV orifice area", "3D TVOA", "cm²", 1, "tv"),
        ("tv.annulus_area", "TV annulus area", "TVAA", "cm²", 1, "tv"),
        ("tv.annulus_area_3d", "3D TV annulus area", "3D TVAA", "cm²", 1, "tv"),
        ("tr.peak_vel", "TR peak velocity", "TRmax Vel", "m/s", 1, "tr"),
        ("tr.peak_pg", "TR peak pressure gradient", "TRmax PG", "mmHg", 0, "tr"),
        ("tr.pisa_r", "TR PISA radius", "TR PISA r", "cm", 1, "tr"),
        ("tr.pisa_aliasing_vel", "TR PISA aliasing velocity", "TR PISA aliasing vel", "cm/s", 1, "tr"),
        ("tr.vti", "TR velocity time integral", "TR VTI", "cm", 0, "tr"),
        # ── Right ventricle ──
        ("rv.rvedv", "RV end-diastolic volume", "RVEDV", "mL", 0, "rv"),
        ("rv.rvedvi", "RV end-diastolic volume index", "RVEDVi", "mL/m²", 0, "rv"),
        ("rv.rvesv", "RV end-systolic volume", "RVESV", "mL", 0, "rv"),
        ("rv.rvesvi", "RV end-systolic volume index", "RVESVi", "mL/m²", 0, "rv"),
        ("rv.wall_thickness", "RV wall thickness", "RV wall thickness", "cm", 1, "rv"),
        ("rv.rvsp", "RV systolic pressure", "RVSP", "mmHg", 0, "rv"),
        ("rv.pasp", "Pulmonary artery systolic pressure", "PASP", "mmHg", 0, "rv"),
        ("rv.tapse", "Tricuspid annular plane systolic excursion", "TAPSE", "cm", 1, "rv"),
        ("rv.tdi_s_prime", "RV TDI s′", "RV TDI s′", "cm/s", 1, "rv"),
        ("rv.ef", "RV ejection fraction", "RV EF", "%", 0, "rv"),
        ("rv.fac", "RV fractional area change", "RV FAC", "%", 0, "rv"),
        ("rv.rvotd", "RVOT diameter", "RVOTd", "cm", 1, "rv"),
        ("rv.basal", "RV basal dimension", "RV basal dimension", "cm", 1, "rv"),
        ("rv.rvot_vti", "RVOT velocity time integral", "RVOT VTI", "cm", 0, "rv"),
        ("rv.sv", "RV stroke volume", "RV SV", "mL", 0, "rv"),
        ("rv.svi", "RV stroke volume index", "RV SVi", "mL/m²", 0, "rv"),
        ("rv.rvot_peak_vel", "RVOT peak velocity", "RVOT peak vel", "m/s", 1, "rv"),
        ("rv.rvot_peak_pg", "RVOT peak pressure gradient", "RVOT peak PG", "mmHg", 0, "rv"),
        ("rv.rvot_mean_pg", "RVOT mean pressure gradient", "RVOT mean PG", "mmHg", 0, "rv"),
        ("rv.rvot_acct", "RVOT acceleration time", "RVOT AccT", "ms", 0, "rv"),
        ("rv.fwvs", "RV fractional wall thickening", "RVFWS", "%", 1, "rv"),
        ("rvgls", "RV global longitudinal strain", "RVGLS", "%", 1, "rv"),
        # ── Right atrium ──
        ("ra.area", "RA area", "RA area", "cm²", 1, "ra"),
        ("ra.rap", "Right atrial pressure", "RAP", "mmHg", 0, "ra"),
        ("ra.posterior_to_annulus", "RA posterior-to-annulus dimension", "", "cm", 1, "ra"),
        ("ra.major", "RA major dimension", "", "cm", 1, "ra"),
        ("ra.minor", "RA minor dimension", "", "cm", 1, "ra"),
        ("ra.vol", "RA volume", "RAV", "mL", 0, "ra"),
        ("ra.voli", "RA volume index", "RAVi", "mL/m²", 0, "ra"),
        # ── Left atrium ──
        ("la.vol", "LA volume", "LAV", "mL", 0, "la"),
        ("la.voli", "LA volume index", "LAVi", "mL/m²", 0, "la"),
        ("la.area", "LA area", "LA area", "cm²", 1, "la"),
        ("la.ap", "LA anteroposterior dimension", "LA AP", "cm", 1, "la"),
        ("la.medial_to_lateral", "LA medial-to-lateral dimension (length)", "", "cm", 1, "la"),
        ("la.lap", "Left atrial pressure", "LAP", "mmHg", 0, "la"),
        ("la.las", "LA strain (LASr, LAScd, LASct)", "LAS", "%", 1, "la"),
        # ── Pulmonic valve / pulmonary regurgitation ──
        ("pv.stj", "Pulmonary sinotubular junction", "Pulmonary STJ", "cm", 1, "pv"),
        ("pv.vaj", "Pulmonary ventriculoarterial junction", "Pulmonary VAJ", "cm", 1, "pv"),
        ("pv.peak_vel", "PV peak velocity", "PV peak vel", "m/s", 1, "pv"),
        ("pv.peak_pg", "PV peak pressure gradient", "PV peak PG", "mmHg", 0, "pv"),
        ("pv.vti", "PV velocity time integral", "PV VTI", "cm", 0, "pv"),
        ("pr.pht", "PR pressure half-time", "PR PHT", "ms", 0, "pr"),
        ("pr.max_vel_diastolic", "PR peak velocity (diastolic)", "PRmax Vel diastolic", "m/s", 1, "pr"),
        # ── Pulmonary artery ──
        ("pa.mpa", "Main pulmonary artery diameter", "mPA", "cm", 1, "pa"),
        ("pa.rpa", "Right pulmonary artery diameter", "rPA", "cm", 1, "pa"),
        ("pa.lpa", "Left pulmonary artery diameter", "lPA", "cm", 1, "pa"),
        # ── Aorta ──
        ("ao.sov", "Aortic root sinus of Valsalva", "AoSoV", "cm", 1, "ao"),
        ("ao.stj", "Aortic sinotubular junction", "AoSTJ", "cm", 1, "ao"),
        ("ao.asc", "Ascending aorta", "AoAsc", "cm", 1, "ao"),
        ("ao.arch", "Aortic arch", "AoArch", "cm", 1, "ao"),
        ("ao.desc", "Descending aorta", "AoDesc", "cm", 1, "ao"),
        ("ao.abd", "Abdominal aorta", "AoAbd", "cm", 1, "ao"),
        # ── Other ──
        ("hr", "Heart rate", "HR", "bpm", 0, "other"),
        ("rpp", "Rate-pressure product", "RPP", "mmHg×bpm", 0, "other"),
    )
)

TABLE6_BY_ID: Mapping[str, Table6Row] = MappingProxyType({row.id: row for row in TABLE6_ROWS})
TABLE6_BY_ABBREVIATION: Mapping[str, Table6Row] = MappingProxyType(
    {row.abbreviation: row for row in TABLE6_ROWS if row.abbreviation}
)


def table6_row(row_id: str) -> Table6Row:
    """One row by id; raises ``KeyError`` for an unknown id."""
    return TABLE6_BY_ID[row_id]


# ── Reconciliation with the catalog (TP-0 PR-3) ─────────────────────
#
# Everything below is a *decision* of the reconciliation, not a coincidence:
# each list is checked by ``tests/unit/test_ase_table6.py``.

ASE_UNIT_DEVIATIONS: Mapping[str, str] = MappingProxyType(
    {
        "mv.e": "ASE: м/с; в приложении PW — см/с (D-05/D-17). Число знаков берётся из строки ASE.",
        "mv.a": "ASE: м/с; в приложении PW — см/с (D-05/D-17). Число знаков берётся из строки ASE.",
        "rvot.vmax": "ASE: м/с; в приложении PW — см/с (D-05/D-17). Число знаков берётся из строки ASE.",
    }
)
"""Catalog id → reason why its unit differs from the ASE row.

Linear dimensions are **not** listed: the project shows mm by default and
switches to «см (ASE)» in TP-1 (D-12), so the ASE unit is reachable.
"""

EN_LABEL_EXCEPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "lv.edv_a4c": "в проекте уточняется позиция съёмки (4-камерная), в ASE строка одна — LVEDV.",
        "lv.esv_a4c": "в проекте уточняется позиция съёмки (4-камерная), в ASE строка одна — LVESV.",
        "lv.edv_a2c": "в проекте уточняется позиция съёмки (2-камерная), в ASE строка одна — LVEDV.",
        "lv.esv_a2c": "в проекте уточняется позиция съёмки (2-камерная), в ASE строка одна — LVESV.",
        "lv.edv_bp": "в проекте уточняется метод (Биплан), в ASE строка одна — LVEDV.",
        "lv.esv_bp": "в проекте уточняется метод (Биплан), в ASE строка одна — LVESV.",
        "lv.ef_bp": "в проекте уточняется метод (Биплан), в ASE строка одна — LV EF.",
        "la.lav_a4c": "в проекте уточняется позиция съёмки (4-камерная), в ASE строка одна — LAV.",
        "la.lav_a2c": "в проекте уточняется позиция съёмки (2-камерная), в ASE строка одна — LAV.",
        "la.lav_bp": "в проекте уточняется метод (Биплан), в ASE строка одна — LAV.",
        "ra.d": "краткая форма «RA minor» вместо «RA minor dimension» (ASE 2025 Right Heart).",
        "rv.basal": "краткая форма «RV basal» вместо «RV basal dimension».",
        "pr.vmax": "в ASE строка диастолической скорости PR («PRmax Vel diastolic»); подпись короче.",
    }
)
"""Catalog id → why its EN short label differs from the ASE abbreviation."""

TABLE6_NOT_IN_CATALOG: Mapping[str, str] = MappingProxyType(
    {
        "lv.co": "сердечный выброс — вне 94 кнопок панели.",
        "lv.ci": "сердечный индекс — вне 94 кнопок панели.",
        "lv.lvot_peak_pg_rest": "градиент ВТЛЖ в покое — вне панели.",
        "lv.lvot_peak_pg_valsalva": "градиент ВТЛЖ при пробе Вальсальвы — вне панели.",
        "lv.lvot_mean_pg": "средний градиент ВТЛЖ — вне панели.",
        "mv.pwd_annulus": "скорость PW на кольце МК — вне панели.",
        "mv.medial_e_e": "E/e′ медиальное — вне панели (в панели только среднее).",
        "mv.peak_pg": "пиковый градиент МК — вне панели.",
        "mv.mean_pg": "средний градиент МК — вне панели.",
        "mv.eroa_3d": "EROA МР по 3D — вне панели.",
        "mr.peak_pg": "пиковый градиент МР — вне панели.",
        "mr.vc": "vena contracta МР — вне панели.",
        "mr.vca_3d": "3D vena contracta МР — вне панели.",
        "mr.pisa_aliasing_vel": "скорость aliasing PISA МР — вне панели.",
        "mr.pisa_eroa": "EROA по PISA МР — вне панели.",
        "aov.annulus_area_planimetry": "площадь кольца АК по планиметрии — вне панели.",
        "aov.acct": "время ускорения — только для протеза АК; для нативного клапана ASE 2017.",
        "ar.vc": "vena contracta АР — вне панели.",
        "ar.vca_3d": "3D vena contracta АР — вне панели.",
        "tv.e": "скорость E трикуспидального притока — вне панели.",
        "tv.a": "скорость A трикуспидального притока — вне панели.",
        "tv.ea": "отношение E/A трикуспидального притока — вне панели.",
        "tv.pwd_annulus": "скорость PW на кольце ТК — вне панели.",
        "tv.e_prime": "e′ трикуспидального кольца — вне панели.",
        "tv.e_e_prime": "E/e′ трикуспидального — вне панели.",
        "tv.peak_pg": "пиковый градиент ТК — вне панели.",
        "tv.mean_pg": "средний градиент ТК — вне панели.",
        "tv.oa_pisa": "площадь ТК по PISA — вне панели.",
        "tv.oa_continuity": "площадь ТК по уравнению непрерывности — вне панели.",
        "tv.oa_planimetry": "площадь ТК по планиметрии — вне панели.",
        "tv.oa_3d": "3D площадь ТК — вне панели.",
        "tv.annulus_area": "площадь кольца ТК — вне панели.",
        "tv.annulus_area_3d": "3D площадь кольца ТК — вне панели.",
        "tr.pisa_r": "радиус PISA ТР — вне панели.",
        "tr.pisa_aliasing_vel": "скорость aliasing PISA ТР — вне панели.",
        "rv.rvedv": "конечно-диастолический объём ПЖ — вне панели.",
        "rv.rvedvi": "индекс конечно-диастолического объёма ПЖ — вне панели.",
        "rv.rvesv": "конечно-систолический объём ПЖ — вне панели.",
        "rv.rvesvi": "индекс конечно-систолического объёма ПЖ — вне панели.",
        "rv.wall_thickness": "толщина стенки ПЖ — вне панели.",
        "rv.ef": "ФВ ПЖ — вне панели.",
        "rv.sv": "ударный объём ПЖ — вне панели.",
        "rv.svi": "индекс ударного объёма ПЖ — вне панели.",
        "rv.rvot_peak_pg": "пиковый градиент ВТПЖ — вне панели.",
        "rv.rvot_mean_pg": "средний градиент ВТПЖ — вне панели.",
        "rv.fwvs": "доля утолщения стенки ПЖ — вне панели.",
        "rvgls": "GLS ПЖ — вне панели.",
        "ra.area": "площадь ПП — вне панели.",
        "ra.posterior_to_annulus": "размер ПП от задней стенки к кольцу — вне панели.",
        "ra.major": "большой размер ПП — вне панели.",
        "ra.voli": "индекс объёма ПП — вне панели.",
        "la.area": "площадь ЛП — вне панели.",
        "la.medial_to_lateral": "медиально-латеральный размер ЛП — вне панели.",
        "la.lap": "давление в ЛП — вне панели.",
        "la.las": "деформация ЛП — вне панели.",
        "pv.stj": "синотубулярное соединение ЛА — вне панели.",
        "pv.vaj": "желудочно-артериальное соединение ЛА — вне панели.",
        "pv.peak_pg": "пиковый градиент ЛА — вне панели.",
        "pa.mpa": "диаметр главной лёгочной артерии — вне панели.",
        "pa.rpa": "диаметр правой лёгочной артерии — вне панели.",
        "pa.lpa": "диаметр левой лёгочной артерии — вне панели.",
        "ao.arch": "диаметр дуги аорты — вне панели.",
        "ao.desc": "диаметр нисходящей аорты — вне панели.",
        "ao.abd": "диаметр брюшной аорты — вне панели.",
        "rpp": "произведение давление × ЧСС — вне панели.",
    }
)
"""Table 6 row id → why the row has no counterpart in the catalog.

The list is exhaustive: every row of the table is either used by the catalog
or listed here, so a new row cannot be forgotten silently.
"""


def validate_table6() -> list[str]:
    """Problems in the table itself (empty list = consistent)."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for row in TABLE6_ROWS:
        if row.id in seen:
            problems.append(f"duplicate row id: {row.id}")
        seen[row.id] = row.abbreviation
        if not row.name:
            problems.append(f"{row.id}: empty name")
        if row.decimals < 0 or row.decimals > 3:
            problems.append(f"{row.id}: implausible number of decimals: {row.decimals}")
        if row.abbreviation:
            for other in TABLE6_ROWS:
                if other.id != row.id and other.abbreviation == row.abbreviation:
                    problems.append(f"{row.id}: duplicate abbreviation {row.abbreviation!r} (also {other.id})")
    for row_id in TABLE6_NOT_IN_CATALOG:
        if row_id not in TABLE6_BY_ID:
            problems.append(f"TABLE6_NOT_IN_CATALOG: unknown row {row_id!r}")
    return problems
