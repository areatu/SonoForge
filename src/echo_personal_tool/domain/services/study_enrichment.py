"""Aggregation decisions for per-study metadata enrichment (loader dialog).

Pure helpers shared by the DICOM JSON parser (incremental merge of QIDO-RS
instance pages) and the dialog (merging progressive batch results).
"""

from __future__ import annotations

from collections.abc import Iterable

from echo_personal_tool.domain.models.orthanc import StudyEnrichment

#: ProtocolName markers of dobutamine stress-echo studies (Latin + Cyrillic).
STRESS_PROTOCOL_MARKERS = ("dobutamin", "добутамин")


def is_stress_study(protocol_name: str, stage_names: Iterable[str] = ()) -> bool:
    """True for dobutamine/stress studies: protocol marker or named stages."""
    text = (protocol_name or "").casefold()
    if any(marker in text for marker in STRESS_PROTOCOL_MARKERS):
        return True
    return any(str(stage).strip() for stage in stage_names)


def device_kind(model_name: str) -> str:
    """Normalise ManufacturerModelName into a short device-family label."""
    model = (model_name or "").strip()
    upper = model.upper()
    if "RS85" in upper:
        return "RS85"
    if "ELVIS" in upper:
        return "ELVIS"
    if "GE " in upper or upper.startswith("GE") or "OEC" in upper or "CARDIAC" in upper:
        return "GE OEC"
    return model


def is_ste_candidate(
    *,
    modality: str,
    has_regions: bool,
    number_of_frames: int | None,
) -> bool:
    """Heuristic for exported strain/quantification clips.

    Samsung RS85 STE exports land as short multi-frame US clips *without*
    SequenceOfUltrasoundRegions (regular cine loops always carry regions),
    see the strain file notes in ``infrastructure.phi_mask_profiles``.
    """
    if (modality or "").strip().upper() != "US":
        return False
    if has_regions:
        return False
    return int(number_of_frames or 0) > 1


def merge_enrichment(
    first: StudyEnrichment | None,
    second: StudyEnrichment | None,
) -> StudyEnrichment | None:
    """Union two partial enrichment slices of the same study."""
    if first is None:
        return second
    if second is None:
        return first
    return StudyEnrichment(
        study_uid=first.study_uid or second.study_uid,
        modes=first.modes | second.modes,
        is_stress=first.is_stress or second.is_stress,
        stress_stages=tuple(sorted({*first.stress_stages, *second.stress_stages})),
        stress_views=tuple(sorted({*first.stress_views, *second.stress_views})),
        device_model=first.device_model or second.device_model,
        device_kind=first.device_kind or second.device_kind,
        device_serial=first.device_serial or second.device_serial,
        software_version=first.software_version or second.software_version,
        patient_size=first.patient_size or second.patient_size,
        patient_weight=first.patient_weight or second.patient_weight,
        patient_age=first.patient_age or second.patient_age,
        ste_candidate=first.ste_candidate or second.ste_candidate,
    )


def merge_enrichment_map(
    target: dict[str, StudyEnrichment],
    incoming: dict[str, StudyEnrichment],
) -> None:
    """Merge ``incoming`` slices into ``target`` in place (union semantics)."""
    for study_uid, enrich in incoming.items():
        merged = merge_enrichment(target.get(study_uid), enrich)
        if merged is not None:
            target[study_uid] = merged
