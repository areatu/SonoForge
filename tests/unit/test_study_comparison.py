"""Identity, candidate and budget rules of the previous-study comparison (562)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from echo_personal_tool.application.study_comparison import (
    comparison_candidates,
    current_study_identity,
    first_clip,
    study_identity,
)
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.services.study_comparison import (
    ComparisonIdentity,
    ComparisonMemoryBudget,
    PatientMatch,
    StudyIdentity,
    StudyOrder,
)


def _instance(
    uid: str,
    *,
    surname: str = "",
    patient_id: str = "",
    issuer: str = "",
    birth_date: str = "",
    sex: str = "",
    frames: int = 30,
    path: str | None = "/data/a.dcm",
) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="series",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=Path(path) if path else None,
        patient_surname=surname,
        patient_id=patient_id,
        issuer_of_patient_id=issuer,
        patient_birth_date=birth_date,
        patient_sex=sex,
    )


def _study(uid: str, date: datetime, *instances: InstanceMetadata) -> StudyMetadata:
    return StudyMetadata(
        study_uid=uid, study_datetime=date, series=(SeriesMetadata("series", uid, "US", "A4C", instances),)
    )


def _identity(
    uid: str,
    date: datetime,
    surname: str,
    *,
    patient_id: str = "",
    issuer: str = "",
    birth_date: str = "",
    sex: str = "",
) -> StudyIdentity:
    return StudyIdentity(
        study_uid=uid,
        study_datetime=date,
        patient_surname=surname,
        patient_id=patient_id,
        issuer_of_patient_id=issuer,
        patient_birth_date=birth_date,
        patient_sex=sex,
    )


def test_the_same_patient_is_proven_by_patient_id_and_issuer() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), " Ivanov ", patient_id=" MRN-1 ", issuer="HOSP-A"),
        _identity("previous", datetime(2026, 1, 1), "IVANOV", patient_id="MRN-1", issuer="HOSP-A"),
    )
    assert pair.patient_match is PatientMatch.SAME
    assert pair.needs_patient_confirmation is False


def test_a_matching_surname_without_patient_id_is_unverified() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), "Ivanov"),
        _identity("previous", datetime(2026, 1, 1), "Ivanov"),
    )
    assert pair.patient_match is PatientMatch.UNVERIFIED
    assert pair.needs_patient_confirmation is False


def test_patient_id_is_compared_case_sensitively() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), "Ivanov", patient_id="MRN-1", issuer="HOSP-A"),
        _identity("previous", datetime(2026, 1, 1), "Ivanov", patient_id="mrn-1", issuer="HOSP-A"),
    )
    assert pair.patient_match is PatientMatch.DIFFERENT, "identifiers are not case-folded"


def test_same_patient_id_without_the_issuer_is_unverified() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), "Ivanov", patient_id="MRN-1"),
        _identity("previous", datetime(2026, 1, 1), "Ivanov", patient_id="MRN-1"),
    )
    assert pair.patient_match is PatientMatch.UNVERIFIED


def test_the_same_patient_id_in_different_issuers_is_unverified() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), "Ivanov", patient_id="MRN-1", issuer="HOSP-A"),
        _identity("previous", datetime(2026, 1, 1), "Ivanov", patient_id="MRN-1", issuer="HOSP-B"),
    )
    assert pair.patient_match is PatientMatch.UNVERIFIED


def test_a_conflicting_patient_id_inside_one_issuer_is_different() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), "Ivanov", patient_id="MRN-1", issuer="HOSP-A"),
        _identity("previous", datetime(2026, 1, 1), "Ivanov", patient_id="MRN-2", issuer="HOSP-A"),
    )
    assert pair.patient_match is PatientMatch.DIFFERENT
    assert pair.needs_patient_confirmation is True


def test_a_birth_date_conflict_proves_different_patients_without_ids() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), "Ivanov", birth_date="19800517"),
        _identity("previous", datetime(2026, 1, 1), "Ivanov", birth_date="19751203"),
    )
    assert pair.patient_match is PatientMatch.DIFFERENT


def test_conflicting_corroborating_data_makes_a_strong_id_unverified() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), "Ivanov", patient_id="MRN-1", issuer="HOSP-A", sex="M"),
        _identity("previous", datetime(2026, 1, 1), "Ivanov", patient_id="MRN-1", issuer="HOSP-A", sex="F"),
    )
    assert pair.patient_match is PatientMatch.UNVERIFIED


def test_different_patients_need_explicit_confirmation() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), "Ivanov"),
        _identity("previous", datetime(2026, 1, 1), "Petrov"),
    )
    assert pair.patient_match is PatientMatch.DIFFERENT
    assert pair.needs_patient_confirmation is True


def test_a_missing_name_is_unverified_not_the_same_patient() -> None:
    pair = ComparisonIdentity(
        _identity("current", datetime(2026, 2, 1), ""),
        _identity("previous", datetime(2026, 1, 1), "Ivanov"),
    )
    assert pair.patient_match is PatientMatch.UNVERIFIED
    assert pair.needs_patient_confirmation is False


def test_the_order_is_by_explicit_date() -> None:
    current = _identity("current", datetime(2026, 2, 10), "Ivanov")
    assert ComparisonIdentity(current, _identity("p", datetime(2026, 1, 1), "Ivanov")).order is StudyOrder.PREVIOUS
    assert ComparisonIdentity(current, _identity("p", datetime(2026, 2, 10), "Ivanov")).order is StudyOrder.SAME_DAY
    assert ComparisonIdentity(current, _identity("p", datetime(2026, 3, 1), "Ivanov")).order is StudyOrder.NEXT
    unknown = StudyIdentity(study_uid="p", study_datetime=None, patient_surname="Ivanov")
    assert ComparisonIdentity(current, unknown).order is StudyOrder.UNKNOWN


def test_identifiers_are_not_exposed_in_repr() -> None:
    identity = _identity(
        "current",
        datetime(2026, 2, 1),
        "Ivanov",
        patient_id="MRN-1",
        issuer="HOSP-A",
        birth_date="19800517",
        sex="M",
    )
    rendered = repr(identity)
    assert "MRN-1" not in rendered
    assert "HOSP-A" not in rendered
    assert "19800517" not in rendered


def test_a_study_cannot_be_compared_with_itself() -> None:
    current = _identity("same", datetime(2026, 2, 1), "Ivanov")
    assert ComparisonIdentity(current, current).same_study is True
    assert ComparisonIdentity(current, current).can_start is False


def test_study_metadata_builds_the_identity_and_keeps_a_conflict_honest() -> None:
    study = _study(
        "uid-1",
        datetime(2026, 1, 2),
        _instance(
            "sop-1",
            surname="Ivanov",
            patient_id="MRN-1",
            issuer="HOSP-A",
            birth_date="19800517",
            sex="M",
        ),
    )
    identity = study_identity(study, source="/data", tab_id="tab-1", tab_number=2)

    assert identity.date_text == "02.01.2026"
    assert identity.patient_text == "Ivanov"
    assert identity.patient_id == "MRN-1"
    assert identity.issuer_of_patient_id == "HOSP-A"
    assert identity.patient_birth_date == "19800517"
    assert identity.patient_sex == "M"
    assert identity.study_ref == "uid-1"
    assert identity.clip_count == 1

    conflicting = _study(
        "uid-2",
        datetime(2026, 1, 3),
        _instance("sop-2", surname="Ivanov", patient_id="MRN-1", issuer="HOSP-A"),
        _instance("sop-3", surname="Petrov", patient_id="MRN-2", issuer="HOSP-B"),
    )
    conflicting_identity = study_identity(conflicting)
    assert conflicting_identity.patient_text == "—"
    assert conflicting_identity.patient_id == ""
    assert conflicting_identity.issuer_of_patient_id == ""

    mixed_case = _study(
        "uid-3",
        datetime(2026, 1, 4),
        _instance("sop-4", patient_id="MRN-1", issuer="HOSP-A"),
        _instance("sop-5", patient_id="mrn-1", issuer="HOSP-A"),
    )
    assert study_identity(mixed_case).patient_id == "", "identifiers are case-sensitive, not merged"


def test_first_clip_prefers_a_2d_cine() -> None:
    doppler = _instance("doppler", frames=1)
    doppler = doppler.__class__(**{**doppler.__dict__, "clip_mode": "doppler"})
    cine = _instance("cine", frames=30)
    study = _study("uid", datetime(2026, 1, 1), doppler, cine)

    assert first_clip(study) is cine
    assert first_clip(_study("empty", datetime(2026, 1, 1), _instance("none", path=None))) is None


class _Tab:
    def __init__(self, tab_id: str, root: str, studies: list[StudyMetadata]) -> None:
        self.tab_id = tab_id
        self.root = root
        self.studies = studies


def test_candidates_exclude_the_current_study_and_studies_without_clips() -> None:
    current = _study("current", datetime(2026, 3, 1), _instance("sop-current"))
    older = _study("older", datetime(2026, 1, 1), _instance("sop-old", surname="Ivanov"))
    newer = _study("newer", datetime(2026, 4, 1), _instance("sop-new", surname="Ivanov"))
    empty = _study("empty", datetime(2026, 2, 1), _instance("sop-empty", path=None))
    tabs = (
        _Tab("tab-1", "/first", [current, older]),
        _Tab("tab-2", "/second", [empty, newer]),
    )

    identities = current_study_identity(tabs, active_tab_id="tab-1", study_uid="current")
    assert identities is not None and identities.patient_text == "—"

    candidates = comparison_candidates(tabs, active_tab_id="tab-1", current_study_uid="current")
    assert [candidate.identity.study_uid for candidate in candidates] == ["newer", "older"]
    assert candidates[0].tab_id == "tab-2"


def test_the_active_tab_wins_when_a_uid_is_open_twice() -> None:
    first = _study("uid", datetime(2026, 1, 1), _instance("a", surname="Ivanov"))
    second = _study("uid", datetime(2026, 1, 1), _instance("b", surname="Petrov"))
    tabs = (_Tab("tab-1", "/first", [first]), _Tab("tab-2", "/second", [second]))

    identity = current_study_identity(tabs, active_tab_id="tab-2", study_uid="uid")

    assert identity is not None
    assert identity.patient_text == "Petrov"
    assert identity.source == "/second"


def test_no_current_study_means_no_candidates() -> None:
    tabs = (_Tab("tab-1", "/first", [_study("current", datetime(2026, 3, 1), _instance("sop-current"))]),)
    assert comparison_candidates(tabs, active_tab_id="tab-1", current_study_uid=None) == ()


def test_the_budget_charges_one_frame_per_pane_and_rolls_back() -> None:
    budget = ComparisonMemoryBudget(cap_bytes=100)

    assert budget.reserve("left", 40) is True
    assert budget.reserve("right", 50) is True
    assert budget.total_bytes == 90
    assert budget.reserve("right", 70) is False
    assert budget.reserved_for("right") == 50, "a refused frame must not evict the last good one"
    assert budget.reserve("left", 40) is True, "replacing a frame releases its old charge first"

    budget.release("right")
    assert budget.total_bytes == 40
    budget.clear()
    assert budget.total_bytes == 0


def test_an_unknown_budget_does_not_block_the_pair() -> None:
    budget = ComparisonMemoryBudget(cap_bytes=None)
    assert budget.enforced is False
    assert budget.reserve("left", 10**12) is True
