"""Identity and memory policy of a two-study comparison (issue 562).

The comparison shows two studies side by side without automatic registration:
the physician chooses the other study explicitly, and the application only
checks what the metadata can actually prove.  Study UIDs must differ.

A patient is *proven the same* only when both studies carry a non-empty
``PatientID`` **and** the same non-empty ``IssuerOfPatientID``.  A matching
family name alone is not proof: the same surname is common, so without matching
PatientID/issuer the result is *unverified*.  Corroborating fields
(``PatientBirthDate``, ``PatientSex``, family name) can prove a mismatch, but
never establish identity on their own.  An empty, ambiguous or contradictory
value is always *unverified*, never silently treated as the same patient.

The module is Qt-free so the rules can be tested without a window.  The
presentation layer owns the wording; these values are stable identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

#: Longest UID tail shown in a comparison badge/dialog (the full UID is noise).
UID_TAIL = 8


class PatientMatch(str, Enum):
    """What the metadata prove about the two patients."""

    SAME = "same"
    DIFFERENT = "different"
    #: The metadata cannot prove either way: no matching PatientID + issuer,
    #: a missing field, or a contradiction that does not prove a mismatch.
    #: Not a synonym of ``SAME``: the UI asks the physician to verify.
    UNVERIFIED = "unverified"


class StudyOrder(str, Enum):
    """Chronological relation of the two studies (date granularity)."""

    PREVIOUS = "previous"
    SAME_DAY = "same_day"
    NEXT = "next"
    UNKNOWN = "unknown"


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _clean_identifier(value: str) -> str:
    """Trim an identifier without changing its case: PatientID is case-sensitive."""
    return " ".join(str(value or "").split())


def _clean_date(value: str) -> str:
    """Normalise a DICOM DA (YYYYMMDD) or a display date for comparison."""
    text = str(value or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits if len(digits) == 8 else _clean_text(text)


def _clean_sex(value: str) -> str:
    return str(value or "").strip().upper()


@dataclass(frozen=True)
class StudyIdentity:
    """Displayable identity of one study in a comparison.

    Every patient field is the single unambiguous value of the study; an empty
    value means «not recorded or conflicting», not «no patient».  PatientID and
    its issuer are the only fields that can prove two studies are the same
    patient; surname, birth date and sex are corroborating evidence.
    """

    study_uid: str
    study_datetime: datetime | None = None
    patient_surname: str = ""
    patient_id: str = field(default="", repr=False)
    issuer_of_patient_id: str = field(default="", repr=False)
    patient_birth_date: str = field(default="", repr=False)
    patient_sex: str = field(default="", repr=False)
    modality: str = ""
    source: str = ""
    tab_id: str = ""
    tab_number: int = 0
    clip_count: int = 0

    @property
    def study_ref(self) -> str:
        """Short tail of the study UID for unambiguous references."""
        return self.study_uid[-UID_TAIL:] if self.study_uid else "—"

    @property
    def date_text(self) -> str:
        """Explicit study date, never an empty separator or a guess."""
        return self.study_datetime.strftime("%d.%m.%Y") if self.study_datetime is not None else "—"

    @property
    def patient_text(self) -> str:
        """Patient context: the known family name or an honest «—»."""
        return self.patient_surname.strip() or "—"

    @property
    def has_clip(self) -> bool:
        return self.clip_count > 0


def _corroborating_conflict(left: StudyIdentity, right: StudyIdentity) -> bool:
    """True when both sides carry the field and the values disagree."""
    pairs = (
        (_clean_text(left.patient_surname), _clean_text(right.patient_surname)),
        (_clean_date(left.patient_birth_date), _clean_date(right.patient_birth_date)),
        (_clean_sex(left.patient_sex), _clean_sex(right.patient_sex)),
    )
    return any(a and b and a != b for a, b in pairs)


@dataclass(frozen=True)
class ComparisonIdentity:
    """The checked pair: current study and the explicitly chosen other one."""

    current: StudyIdentity
    previous: StudyIdentity

    @property
    def same_study(self) -> bool:
        return bool(self.current.study_uid) and self.current.study_uid == self.previous.study_uid

    @property
    def patient_match(self) -> PatientMatch:
        """Identity evidence, not a surname guess.

        A strong identifier (``PatientID`` + ``IssuerOfPatientID``) is compared
        first.  With the same issuer, equal IDs prove the same patient and
        different IDs prove different patients.  Without a comparable strong
        identifier, only a conflict in corroborating fields proves a mismatch;
        everything else stays *unverified*.
        """
        current = self.current
        previous = self.previous
        current_id = _clean_identifier(current.patient_id)
        previous_id = _clean_identifier(previous.patient_id)
        current_issuer = _clean_identifier(current.issuer_of_patient_id)
        previous_issuer = _clean_identifier(previous.issuer_of_patient_id)
        same_issuer = bool(current_issuer and previous_issuer and current_issuer == previous_issuer)

        if same_issuer and current_id and previous_id:
            if current_id != previous_id:
                return PatientMatch.DIFFERENT
            if _corroborating_conflict(current, previous):
                # The strong ID agrees, but the rest of the header contradicts
                # itself: report unverified instead of silently choosing a side.
                return PatientMatch.UNVERIFIED
            return PatientMatch.SAME

        if _corroborating_conflict(current, previous):
            return PatientMatch.DIFFERENT
        return PatientMatch.UNVERIFIED

    @property
    def order(self) -> StudyOrder:
        left = self.current.study_datetime
        right = self.previous.study_datetime
        if left is None or right is None:
            return StudyOrder.UNKNOWN
        if right.date() < left.date():
            return StudyOrder.PREVIOUS
        if right.date() > left.date():
            return StudyOrder.NEXT
        return StudyOrder.SAME_DAY

    @property
    def can_start(self) -> bool:
        """A comparison needs two distinct, non-empty studies."""
        return bool(self.current.study_uid and self.previous.study_uid) and not self.same_study

    @property
    def needs_patient_confirmation(self) -> bool:
        """Only a proven mismatch blocks until the physician confirms."""
        return self.patient_match is PatientMatch.DIFFERENT


@dataclass
class ComparisonMemoryBudget:
    """Byte ceiling shared by the two decoded comparison frames.

    The active study's frame cache has its own byte ceiling; the parked frame
    of the other study is decoded on demand and is not stored in that cache.
    This reservation keeps the *pair* inside the same process budget: each pane
    owns at most one frame, and replacing a frame releases the old reservation
    before the new one is charged.
    """

    cap_bytes: int | None = None
    _reserved: dict[str, int] = field(default_factory=dict, repr=False)

    @property
    def enforced(self) -> bool:
        return self.cap_bytes is not None and self.cap_bytes > 0

    @property
    def total_bytes(self) -> int:
        return sum(self._reserved.values())

    def reserved_for(self, pane: str) -> int:
        return self._reserved.get(pane, 0)

    def reserve(self, pane: str, frame_bytes: int) -> bool:
        """Charge one pane's frame; return False and roll back when over budget."""
        frame_bytes = max(int(frame_bytes), 0)
        previous = self._reserved.get(pane, 0)
        if frame_bytes:
            self._reserved[pane] = frame_bytes
        else:
            self._reserved.pop(pane, None)
        if self.enforced and self.total_bytes > int(self.cap_bytes or 0):
            if previous:
                self._reserved[pane] = previous
            else:
                self._reserved.pop(pane, None)
            return False
        return True

    def release(self, pane: str) -> None:
        self._reserved.pop(pane, None)

    def clear(self) -> None:
        self._reserved.clear()
