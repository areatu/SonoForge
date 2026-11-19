"""LOINC / SNOMED CT / DICOM CID mapping for app measurement ids (#625).

Pure domain module (standard library only).  One :class:`TerminologyCode` per
measurement-catalog id (``lv.lvedd`` …) and per ASE Table 6 row; ids without a
reconciled standard code fall back to the local code system so an outbound
message always carries *some* code and never silently drops a value.

``verified`` marks codes reconciled against the published LOINC/SNOMED
lists; unverified entries keep the code with the flag down (same convention
as :mod:`echo_personal_tool.domain.ase_table6`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

#: Coding-system identifiers used in HL7 v2 (OBX-3) and FHIR (CodeableConcept).
LOINC_SYSTEM = "LN"  # HL7 table 0396 name for LOINC
LOINC_SYSTEM_URI = "http://loinc.org"
SNOMED_SYSTEM = "SCT"  # HL7 table 0396 name for SNOMED CT
SNOMED_SYSTEM_URI = "http://snomeda.info/sct"
#: Local codes (app-internal ids) travel under this private system.
LOCAL_CODE_SYSTEM = "99SONOFORGE"
LOCAL_CODE_SYSTEM_URI = "https://sonoforge.local/codes"


@dataclass(frozen=True)
class TerminologyCode:
    """Standard codes of one measurement; at least one of them is always set."""

    measurement_id: str
    loinc: str | None = None
    snomed: str | None = None
    dicom_cid: str | None = None  # DICOM Context Identifier, e.g. "CID 7603"
    verified: bool = False
    text: str = ""

    def coding_systems(self) -> tuple[tuple[str, str, str], ...]:
        """``(system, code, uri)`` triples for HL7/FHIR, local code last."""
        triples: list[tuple[str, str, str]] = []
        if self.loinc:
            triples.append((LOINC_SYSTEM, self.loinc, LOINC_SYSTEM_URI))
        if self.snomed:
            triples.append((SNOMED_SYSTEM, self.snomed, SNOMED_SYSTEM_URI))
        triples.append((LOCAL_CODE_SYSTEM, self.measurement_id, LOCAL_CODE_SYSTEM_URI))
        return tuple(triples)


def _c(
    mid: str,
    loinc: str | None = None,
    snomed: str | None = None,
    cid: str | None = None,
    verified: bool = False,
    text: str = "",
) -> TerminologyCode:
    return TerminologyCode(measurement_id=mid, loinc=loinc, snomed=snomed, dicom_cid=cid, verified=verified, text=text)


#: Measurement-catalog id → terminology.  Verified codes are the widely
#: published echo LOINC set; everything else carries the local code only.
CODES_BY_MEASUREMENT: Mapping[str, TerminologyCode] = MappingProxyType(
    {
        "hr": _c("hr", loinc="8867-4", verified=True, text="Heart rate"),
        "patient.bsa": _c("patient.bsa", loinc="8287-5", verified=True, text="Body surface area"),
        "lv.lvedd": _c("lv.lvedd", loinc="8625-6", verified=True, text="Left ventricular end-diastolic diameter"),
        "lv.lvesd": _c("lv.lvesd", loinc="8626-4", verified=True, text="Left ventricular end-systolic diameter"),
        "lv.ivsd": _c("lv.ivsd", loinc="8619-9", text="Interventricular septum thickness, end-diastole"),
        "lv.lvpwd": _c("lv.lvpwd", loinc="8622-5", text="Left ventricular posterior wall thickness, end-diastole"),
        "lv.rwt": _c("lv.rwt", text="Relative wall thickness"),
        "lv.mass": _c("lv.mass", loinc="8624-9", text="Left ventricular mass"),
        "lv.mass_i": _c("lv.mass_i", loinc="76521-3", text="Left ventricular mass index"),
        "lv.fs": _c("lv.fs", text="Left ventricular fractional shortening"),
        "lv.ef_teich": _c("lv.ef_teich", text="Left ventricular ejection fraction (Teichholz)"),
        "lv.ef_bp": _c("lv.ef_bp", text="Left ventricular ejection fraction (biplane Simpson)"),
        "lv.ef_a4c": _c("lv.ef_a4c", text="Left ventricular ejection fraction (apical 4-chamber)"),
        "lv.ef_a2c": _c("lv.ef_a2c", text="Left ventricular ejection fraction (apical 2-chamber)"),
        "lv.edv_teich": _c("lv.edv_teich", text="Left ventricular end-diastolic volume (Teichholz)"),
        "lv.esv_teich": _c("lv.esv_teich", text="Left ventricular end-systolic volume (Teichholz)"),
        "lv.edv_a4c": _c("lv.edv_a4c", loinc="79068-9", text="Left ventricular end-diastolic volume (4-chamber)"),
        "lv.esv_a4c": _c("lv.esv_a4c", loinc="79069-7", text="Left ventricular end-systolic volume (4-chamber)"),
        "lv.edv_a2c": _c("lv.edv_a2c", text="Left ventricular end-diastolic volume (2-chamber)"),
        "lv.esv_a2c": _c("lv.esv_a2c", text="Left ventricular end-systolic volume (2-chamber)"),
        "lv.edv_bp": _c("lv.edv_bp", loinc="79068-9", text="Left ventricular end-diastolic volume (biplane)"),
        "lv.esv_bp": _c("lv.esv_bp", loinc="79069-7", text="Left ventricular end-systolic volume (biplane)"),
        "lv.sv": _c("lv.sv", loinc="8748-8", text="Stroke volume"),
        "lv.svi": _c("lv.svi", text="Stroke volume index"),
        "lv.edvi": _c("lv.edvi", text="LV end-diastolic volume index"),
        "lv.esvi": _c("lv.esvi", text="LV end-systolic volume index"),
        "lv.gls_a4c": _c("lv.gls_a4c", text="Global longitudinal strain (4-chamber)"),
        "lv.gls_a2c": _c("lv.gls_a2c", text="Global longitudinal strain (2-chamber)"),
        "lv.gls_a3c": _c("lv.gls_a3c", text="Global longitudinal strain (3-chamber)"),
        "la.lav_a4c": _c("la.lav_a4c", text="Left atrial volume (4-chamber)"),
        "la.lav_a2c": _c("la.lav_a2c", text="Left atrial volume (2-chamber)"),
        "la.lav_bp": _c("la.lav_bp", text="Left atrial volume (biplane)"),
        "la.lavi": _c("la.lavi", text="Left atrial volume index"),
        "la.area": _c("la.area", text="Left atrial area"),
        "la.ap": _c("la.ap", loinc="8645-4", text="Left atrial anteroposterior diameter"),
        "la.length": _c("la.length", text="Left atrial length"),
        "ao.annulus": _c("ao.annulus", text="Aortic annulus diameter"),
        "ao.sinus": _c("ao.sinus", text="Aortic sinus diameter"),
        "ao.stj": _c("ao.stj", text="Sinotubular junction diameter"),
        "ao.asc": _c("ao.asc", text="Ascending aorta diameter"),
        "av.d": _c("av.d", text="Aortic valve diameter"),
        "ra.d": _c("ra.d", text="Right atrial minor diameter"),
        "ra.vol": _c("ra.vol", text="Right atrial volume"),
        "ra.ravi": _c("ra.ravi", text="Right atrial volume index"),
        "ra.area": _c("ra.area", text="Right atrial area"),
        "ra.rap": _c("ra.rap", text="Right atrial pressure"),
        "ivc.d": _c("ivc.d", text="IVC diameter"),
        "ivc.d_exp": _c("ivc.d_exp", text="IVC diameter, expiration"),
        "ivc.d_insp": _c("ivc.d_insp", text="IVC diameter, inspiration"),
        "rv.rvot_prox": _c("rv.rvot_prox", text="RVOT proximal diameter"),
        "rv.basal": _c("rv.basal", text="RV basal diameter"),
        "rv.mid": _c("rv.mid", text="RV mid diameter"),
        "rv.tapse": _c("rv.tapse", text="Tricuspid annular plane systolic excursion"),
        "rv.s_prime": _c("rv.s_prime", text="RV S′ (TDI)"),
        "rv.fac": _c("rv.fac", text="RV fractional area change"),
        "rv.rvsp": _c("rv.rvsp", text="RV systolic pressure"),
        "mv.e": _c("mv.e", loinc="8633-0", text="Mitral E-wave velocity"),
        "mv.a": _c("mv.a", loinc="8634-8", text="Mitral A-wave velocity"),
        "mv.ea": _c("mv.ea", text="E/A ratio"),
        "mv.dt": _c("mv.dt", text="Mitral E-wave deceleration time"),
        "mv.e_e_avg": _c("mv.e_e_avg", text="E/e′ (average)"),
        "tdi.e_sept": _c("tdi.e_sept", text="e′ septal"),
        "tdi.e_lat": _c("tdi.e_lat", text="e′ lateral"),
        "tdi.e_avg": _c("tdi.e_avg", text="e′ average"),
        "tdi.e_e_sept": _c("tdi.e_e_sept", text="E/e′ septal"),
        "tdi.e_e_lat": _c("tdi.e_e_lat", text="E/e′ lateral"),
        "tdi.s_prime_sept": _c("tdi.s_prime_sept", text="s′ septal"),
        "tdi.s_prime_lat": _c("tdi.s_prime_lat", text="s′ lateral"),
        "doppler.vmax": _c("doppler.vmax", text="Peak velocity"),
        "doppler.vmean": _c("doppler.vmean", text="Mean velocity"),
        "doppler.pg_peak": _c("doppler.pg_peak", text="Peak pressure gradient"),
        "doppler.pg_mean": _c("doppler.pg_mean", text="Mean pressure gradient"),
        "doppler.vti": _c("doppler.vti", text="Velocity-time integral"),
        "doppler.pht": _c("doppler.pht", text="Pressure half-time"),
        "doppler.at": _c("doppler.at", text="Acceleration time"),
        "doppler.et": _c("doppler.et", text="Ejection time"),
        "doppler.time": _c("doppler.time", text="Doppler time interval"),
        "planimeter.area": _c("planimeter.area", text="Planimeter area"),
        "planimeter.volume": _c("planimeter.volume", text="Planimeter volume"),
        "planimeter.length": _c("planimeter.length", text="Planimeter length"),
        "caliper.length": _c("caliper.length", text="Linear measurement"),
        "caliper.area": _c("caliper.area", text="Caliper area"),
        "caliper.stenosis_pct": _c("caliper.stenosis_pct", text="Stenosis, percent"),
        "vessel.ri": _c("vessel.ri", text="Resistivity index"),
        "vessel.sd": _c("vessel.sd", text="Systolic/diastolic ratio"),
        "vessel.mv": _c("vessel.mv", text="Mean velocity (vessel)"),
        "cca.imt_right": _c("cca.imt_right", text="IMT right CCA"),
        "cca.imt_left": _c("cca.imt_left", text="IMT left CCA"),
    }
)

#: ASE Table 6 row id → measurement id (rows that exist in the catalog).
_ASE_ROW_TO_MEASUREMENT: Mapping[str, str] = MappingProxyType(
    {
        "lv.ivsd": "lv.ivsd",
        "lv.lvedd": "lv.lvedd",
        "lv.lvpwd": "lv.lvpwd",
        "lv.lvesd": "lv.lvesd",
        "lv.rwt": "lv.rwt",
        "lv.fs": "lv.fs",
        "lv.ef": "lv.ef_bp",
        "lv.lvedv": "lv.edv_bp",
        "lv.lvesv": "lv.esv_bp",
        "lv.lvedvi": "lv.edvi",
        "lv.lvesvi": "lv.esvi",
        "lv.sv": "lv.sv",
        "lv.svi": "lv.svi",
        "la.vol": "la.lav_bp",
        "la.voli": "la.lavi",
        "la.ap": "la.ap",
        "aov.annulus_d": "ao.annulus",
        "ao.sov": "ao.sinus",
        "ao.stj": "ao.stj",
        "ao.asc": "ao.asc",
        "ra.minor": "ra.d",
        "ra.vol": "ra.vol",
        "rv.rvotd": "rv.rvot_prox",
        "rv.basal": "rv.basal",
        "rv.tapse": "rv.tapse",
        "rv.tdi_s_prime": "rv.s_prime",
        "rv.fac": "rv.fac",
        "rv.rvsp": "rv.rvsp",
        "mv.e": "mv.e",
        "mv.a": "mv.a",
        "mv.ea": "mv.ea",
        "mv.avg_e_e": "mv.e_e_avg",
        "hr": "hr",
    }
)


def code_for(measurement_id: str) -> TerminologyCode:
    """Terminology of a measurement-catalog id; unknown ids get a local-only code."""
    code = CODES_BY_MEASUREMENT.get(measurement_id)
    if code is not None:
        return code
    return TerminologyCode(measurement_id=measurement_id, text=measurement_id)


def code_for_ase_row(ase_row: str | None) -> TerminologyCode | None:
    """Terminology via the ASE Table 6 row id, when the row maps to a catalog id."""
    if not ase_row:
        return None
    measurement_id = _ASE_ROW_TO_MEASUREMENT.get(ase_row)
    return code_for(measurement_id) if measurement_id else None
