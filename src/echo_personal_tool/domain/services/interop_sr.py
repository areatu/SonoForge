"""Pure DICOM SR (TID 5200) content model for the echo procedure report (#626).

Builds a neutral SR tree from an :class:`InteropReport` using the Stage-3
terminology dictionary (LOINC + UCUM). ``infrastructure/dicom_sr.py`` serializes
this tree into a pydicom TID 5200 dataset; keeping the model pure lets the
unit tests run without pydicom.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.services.interop_hl7 import InteropObservation, InteropReport
from echo_personal_tool.domain.terminology.codes import code_for
from echo_personal_tool.domain.terminology.units import ConversionError, canonical_ucum_unit, to_canonical_ucum

TID_5200_ROOT_CODE = ("126000", "Adult Echocardiography Procedure Report", "DCM")
TID_5200_SECTION_CODES = {
    "measurements": ("121070", "Findings", "DCM"),
    "conclusion": ("121076", "Conclusions", "DCM"),
}


@dataclass(frozen=True)
class SrCode:
    """A DICOM CODE content item (code value, coding scheme designator, meaning)."""

    value: str
    scheme: str
    meaning: str


@dataclass(frozen=True)
class SrNum:
    """A NUM content item with a UCUM unit code."""

    value: str
    unit_code: str
    unit_meaning: str


@dataclass(frozen=True)
class SrText:
    value: str


@dataclass(frozen=True)
class SrNode:
    """One SR content item; children for CONTAINERs."""

    value_type: str  # CONTAINER | CODE | NUM | TEXT
    concept: SrCode
    children: tuple[SrNode, ...] = ()
    num: SrNum | None = None
    text: SrText | None = None


def _observation_node(obs: InteropObservation) -> SrNode:
    code = code_for(obs.measurement_id)
    loinc = code.loinc or obs.measurement_id
    try:
        canonical = to_canonical_ucum(obs.value, obs.unit, obs.quantity) if obs.unit else (obs.value, "")
        unit_code = canonical[1] or canonical_ucum_unit(obs.quantity)
    except (ConversionError, ValueError):
        canonical = (obs.value, "")
        unit_code = obs.unit
    children: list[SrNode] = [
        SrNode(
            value_type="NUM",
            concept=SrCode(loinc, "LN", code.text or obs.label),
            num=SrNum(value=canonical[0], unit_code=unit_code, unit_meaning=unit_code),
        )
    ]
    if obs.norm:
        children.append(
            SrNode(
                value_type="TEXT",
                concept=SrCode("363812007", "SCT", "Reference range"),
                text=SrText(obs.norm),
            )
        )
    if obs.pathological:
        children.append(
            SrNode(
                value_type="CODE",
                concept=SrCode("263654008", "SCT", "Abnormal"),
            )
        )
    return SrNode(
        value_type="CONTAINER",
        concept=SrCode(loinc, "LN", code.text or obs.label),
        children=tuple(children),
    )


def build_sr_tree(report: InteropReport) -> SrNode:
    """Build the TID 5200 content tree for one report."""
    measurements = TID_5200_SECTION_CODES["measurements"]
    conclusion = TID_5200_SECTION_CODES["conclusion"]
    sections: list[SrNode] = [
        SrNode(
            value_type="CONTAINER",
            concept=SrCode(*measurements),
            children=tuple(_observation_node(obs) for obs in report.observations),
        ),
        SrNode(
            value_type="CONTAINER",
            concept=SrCode(*conclusion),
            children=(
                SrNode(
                    value_type="TEXT",
                    concept=SrCode("121076", "DCM", "Conclusion"),
                    text=SrText(report.conclusion),
                ),
            )
            if report.conclusion
            else (),
        ),
    ]
    return SrNode(
        value_type="CONTAINER",
        concept=SrCode(*TID_5200_ROOT_CODE),
        children=tuple(sections),
    )
