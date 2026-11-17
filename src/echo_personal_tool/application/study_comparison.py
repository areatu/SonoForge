"""Build comparison candidates from the studies already open in tabs (issue 562).

The comparison never scans the disk or registers two studies automatically:
the physician opens the other study in a tab first, and this module turns the
open tabs into identifiable choices.  A study without a decodable clip is not
offered, and the active study is never its own comparison target.

Qt-free; the dialog in ``presentation`` only renders these values.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from echo_personal_tool.domain.models.metadata import InstanceMetadata, StudyMetadata
from echo_personal_tool.domain.services.study_comparison import StudyIdentity

#: Preference order of clips inside a study: 2D cine first, then any clip.
_CLIP_MODES = ("2d",)


@dataclass(frozen=True)
class ComparisonCandidate:
    """One other study the physician may put beside the current one."""

    identity: StudyIdentity
    instance: InstanceMetadata
    study: StudyMetadata
    tab_id: str
    tab_number: int

    @property
    def label(self) -> str:
        return f"{self.identity.date_text} · {self.identity.patient_text} · {self.identity.study_ref}"


def first_clip(study: StudyMetadata) -> InstanceMetadata | None:
    """First decodable clip of a study, preferring a 2D cine on disk."""
    clips = [
        instance
        for series in study.series
        for instance in series.instances
        if instance.path is not None and int(instance.number_of_frames or 0) > 0
    ]
    for mode in _CLIP_MODES:
        match = next((clip for clip in clips if getattr(clip, "clip_mode", "") == mode), None)
        if match is not None:
            return match
    return clips[0] if clips else None


def _single_text(values: Iterable[str], *, casefold: bool = True) -> str:
    """One unambiguous non-empty value of a study.

    Instances of one study normally repeat the same patient fields.  If they
    disagree, the field is empty («not proven»), never the first or the most
    common value: an identity check must not guess.  PatientID/issuer keep
    their case because identifiers are case-sensitive (562).
    """
    seen: dict[str, str] = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            seen.setdefault(text.casefold() if casefold else text, text)
    return next(iter(seen.values())) if len(seen) == 1 else ""


def _study_field(study: StudyMetadata, attribute: str, *, casefold: bool = True) -> str:
    return _single_text(
        (getattr(instance, attribute, "") for series in study.series for instance in series.instances),
        casefold=casefold,
    )


def _patient_identity_uncertain(study: StudyMetadata) -> bool:
    """Do not combine partial or contradictory headers into a trusted identity."""
    instances = [instance for series in study.series for instance in series.instances]
    if not instances:
        return True
    for instance in instances:
        if not str(instance.patient_id or "").strip() or not str(instance.issuer_of_patient_id or "").strip():
            return True
    for attribute in ("patient_id", "issuer_of_patient_id", "patient_surname", "patient_birth_date", "patient_sex"):
        values = [str(getattr(instance, attribute, "") or "").strip() for instance in instances]
        if any(values) and not _single_text(values, casefold=attribute not in ("patient_id", "issuer_of_patient_id")):
            return True
    return False


def study_identity(
    study: StudyMetadata,
    *,
    source: str = "",
    tab_id: str = "",
    tab_number: int = 0,
) -> StudyIdentity:
    """Identity fields the metadata can actually prove for one study."""
    modality = next((series.modality for series in study.series if series.modality), "")
    return StudyIdentity(
        study_uid=study.study_uid,
        study_datetime=study.study_datetime,
        # A conflicting name is not a patient identity: keep it empty.
        patient_surname=_study_field(study, "patient_surname"),
        patient_id=_study_field(study, "patient_id", casefold=False),
        issuer_of_patient_id=_study_field(study, "issuer_of_patient_id", casefold=False),
        patient_birth_date=_study_field(study, "patient_birth_date"),
        patient_sex=_study_field(study, "patient_sex"),
        patient_identity_uncertain=_patient_identity_uncertain(study),
        modality=modality,
        source=source,
        tab_id=tab_id,
        tab_number=tab_number,
        clip_count=sum(len(series.instances) for series in study.series),
    )


def current_study_identity(
    tabs: tuple,
    *,
    active_tab_id: str | None,
    study_uid: str | None,
) -> StudyIdentity | None:
    """Identity of the study the main viewer shows, if it is one of the tabs.

    A UID can occur in more than one tab (a folder opened twice); the active
    tab wins, because its metadata is the one the physician is looking at.
    """
    fallback: StudyIdentity | None = None
    for number, tab in enumerate(tabs, start=1):
        for study in tab.studies:
            if not study_uid or study.study_uid != study_uid:
                continue
            identity = study_identity(study, source=tab.root, tab_id=tab.tab_id, tab_number=number)
            if tab.tab_id == active_tab_id:
                return identity
            fallback = fallback or identity
    return fallback


def comparison_candidates(
    tabs: tuple,
    *,
    active_tab_id: str | None,
    current_study_uid: str | None,
) -> tuple[ComparisonCandidate, ...]:
    """Every other open study with a decodable clip, newest first.

    The active study is excluded by UID, not by tab: one tab may contain a
    folder with several studies, and any of the others is a valid target.
    """
    if not current_study_uid:
        return ()
    candidates: list[ComparisonCandidate] = []
    for number, tab in enumerate(tabs, start=1):
        for study in tab.studies:
            if study.study_uid == current_study_uid:
                continue
            clip = first_clip(study)
            if clip is None:
                continue
            identity = study_identity(study, source=tab.root, tab_id=tab.tab_id, tab_number=number)
            candidates.append(
                ComparisonCandidate(
                    identity=identity,
                    instance=clip,
                    study=study,
                    tab_id=tab.tab_id,
                    tab_number=number,
                )
            )
    candidates.sort(key=lambda candidate: _candidate_order(candidate, active_tab_id))
    return tuple(candidates)


def _candidate_order(candidate: ComparisonCandidate, active_tab_id: str | None) -> tuple[int, int, int, int, str]:
    """Newest first; inside one date, the active tab's folder comes first.

    Ordinals, not POSIX timestamps: DICOM dates can predate 1970 and Windows
    cannot convert those to a timestamp.
    """
    date = candidate.identity.study_datetime or datetime.min
    return (
        1 if candidate.identity.study_datetime is None else 0,
        -date.toordinal(),
        0 if candidate.tab_id == active_tab_id else 1,
        candidate.tab_number,
        candidate.study.study_uid,
    )
