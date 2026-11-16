"""Identity and memory policy of a two-study comparison (issue 562).

The comparison shows two studies side by side without automatic registration:
the physician chooses the other study explicitly, and the application only
checks what the metadata can actually prove.  Study UIDs must differ; the
patient is considered the same only when both studies carry exactly one
non-empty family name and those names match.  An empty or ambiguous name is
reported as *unverified* — never silently treated as the same patient.

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
    #: One or both studies have no unambiguous family name.  Not a synonym of
    #: ``SAME``: the UI asks the physician to verify the identity.
    UNVERIFIED = "unverified"


class StudyOrder(str, Enum):
    """Chronological relation of the two studies (date granularity)."""

    PREVIOUS = "previous"
    SAME_DAY = "same_day"
    NEXT = "next"
    UNKNOWN = "unknown"


def _clean_name(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class StudyIdentity:
    """Displayable identity of one study in a comparison.

    ``patient_surname`` is the single unambiguous family name of the study;
    an empty value means «not recorded or conflicting», not «no patient».
    """

    study_uid: str
    study_datetime: datetime | None = None
    patient_surname: str = ""
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
        left = _clean_name(self.current.patient_surname)
        right = _clean_name(self.previous.patient_surname)
        if not left or not right:
            return PatientMatch.UNVERIFIED
        return PatientMatch.SAME if left == right else PatientMatch.DIFFERENT

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
