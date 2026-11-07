"""Report formats — the study type the physician picks in the sheet header.

Item 7 of the 2026-11-06 list: the report sheet is not always an echocardiogram.
The owner works with abdominal, thyroid and precerebral ultrasound in the same
application, and a protocol titled «Протокол ЭхоКГ» with cardiology norm dots on
an abdominal study is simply wrong.  The format is therefore *content*, not a
view: it changes the title of the document and the groups that belong to it, so
the preview, the PDF, the CSV and the JSON export all follow it — what is on
screen is what the file holds.

The first slice has two formats: the echocardiography one (the behaviour of the
application before this item) and a generic ultrasound protocol.  More formats
(abdomen, thyroid, precerebral arteries) are a data change here, not a code
change: add a :class:`ReportProfile` with its own ``title_key`` and group filter.

Auto-selection is only a *starting value*: the window asks
:func:`profile_for_study` for the study on screen, and the physician may switch
at any time — a cardiac-named clip that is really an abdominal scan must not be
locked into the cardiology template.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final, Protocol, TypeVar

from echo_personal_tool.domain.services.report_groups import (
    GROUP_ABDOMEN,
    GROUP_AORTIC_VALVE,
    GROUP_KIDNEY,
    GROUP_LEFT_ATRIUM,
    GROUP_LEFT_VENTRICLE,
    GROUP_MITRAL_VALVE,
    GROUP_OTHER,
    GROUP_PRECEREBRAL,
    GROUP_RIGHT_ATRIUM,
    GROUP_RIGHT_VENTRICLE,
    GROUP_THYROID,
    GROUP_TRICUSPID_VALVE,
)


class PrintedGroup(Protocol):
    """What a report format needs from a group of the sheet: which group it is.

    The format filters groups and does not build them, so it names the shape it
    reads instead of importing the builder's dataclass — the builder resolves a
    ``profile_id`` from here, and a mutual import would be a circle (issue 328).
    The ids themselves come from the leaf :mod:`report_groups` both sides share.
    Read-only on purpose: the builder's group is a frozen dataclass.
    """

    @property
    def key(self) -> str:
        """The vocabulary id of the group (``lv``, ``calculations``, ...)."""
        ...


#: The group type the caller handed in comes back out, unchanged.
_GroupT = TypeVar("_GroupT", bound=PrintedGroup)

#: Format id of the echocardiography protocol — the pre-item-7 behaviour.
PROFILE_ECHO: Final[str] = "echo"

#: Format id of the generic ultrasound protocol: the same measurements, no
#: cardiology chambers and valves, no indexed cardiac groups.
PROFILE_ULTRASOUND: Final[str] = "ultrasound_generic"

#: Format ids of the organ protocols (item 11): a kidney study prints a kidney
#: protocol — its own title and its own conclusion templates — instead of the
#: generic ultrasound sheet.  The ids are short on purpose: they key the report
#: header buttons and scope the conclusion phrases.
PROFILE_VASCULAR: Final[str] = "vascular"
PROFILE_ABDOMEN: Final[str] = "abdomen"
PROFILE_KIDNEY: Final[str] = "kidney"
PROFILE_THYROID: Final[str] = "thyroid"


@dataclass(frozen=True)
class ReportProfile:
    """One report format: a title and the groups that belong to it.

    ``excluded_groups`` is a deny-list rather than an allow-list on purpose: a
    new measurement group added to the builder appears in every profile until
    somebody says it is cardiology-specific, which is the safe direction — a
    measurement the physician took should not silently vanish from a report.
    """

    id: str
    title_key: str
    excluded_groups: frozenset[str] = frozenset()

    @property
    def label_key(self) -> str:
        """Localisation key of the header button."""
        return f"report.profile.{self.id}"

    def groups(self, groups: Iterable[_GroupT]) -> tuple[_GroupT, ...]:
        """The groups of *groups* this format prints, order preserved."""
        if not self.excluded_groups:
            return tuple(groups)
        return tuple(group for group in groups if group.key not in self.excluded_groups)


#: The cardiology groups that mean nothing on a non-cardiac ultrasound report.
_CARDIAC_GROUPS: Final[frozenset[str]] = frozenset(
    {
        GROUP_LEFT_VENTRICLE,
        GROUP_LEFT_ATRIUM,
        GROUP_RIGHT_VENTRICLE,
        GROUP_RIGHT_ATRIUM,
        GROUP_MITRAL_VALVE,
        GROUP_AORTIC_VALVE,
        GROUP_TRICUSPID_VALVE,
    }
)

#: The organ blocks of the four organ studies.  A report keeps its own and
#: drops the rest: a thyroid protocol must not print the renal rows that a
#: shared study snapshot may still carry.
_ORGAN_GROUPS: Final[frozenset[str]] = frozenset(
    {GROUP_PRECEREBRAL, GROUP_ABDOMEN, GROUP_KIDNEY, GROUP_THYROID}
)

PROFILES: Final[tuple[ReportProfile, ...]] = (
    ReportProfile(id=PROFILE_ECHO, title_key="report.title"),
    # The organ protocols print their own organ block (an abdominal study also
    # includes the renal one) plus whatever the physician measured anyway —
    # vessels, planimetry stay for the same reason the generic protocol keeps
    # them.
    ReportProfile(
        id=PROFILE_VASCULAR,
        title_key="report.title.vascular",
        excluded_groups=_CARDIAC_GROUPS | {GROUP_OTHER} | (_ORGAN_GROUPS - {GROUP_PRECEREBRAL}),
    ),
    ReportProfile(
        id=PROFILE_ABDOMEN,
        title_key="report.title.abdomen",
        excluded_groups=_CARDIAC_GROUPS | {GROUP_OTHER} | (_ORGAN_GROUPS - {GROUP_ABDOMEN, GROUP_KIDNEY}),
    ),
    ReportProfile(
        id=PROFILE_KIDNEY,
        title_key="report.title.kidney",
        excluded_groups=_CARDIAC_GROUPS | {GROUP_OTHER} | (_ORGAN_GROUPS - {GROUP_KIDNEY}),
    ),
    ReportProfile(
        id=PROFILE_THYROID,
        title_key="report.title.thyroid",
        excluded_groups=_CARDIAC_GROUPS | {GROUP_OTHER} | (_ORGAN_GROUPS - {GROUP_THYROID}),
    ),
    # The generic protocol keeps the planimetry, the vessels and the derived
    # calculations; only the cardiology chamber/valve rows and the «прочие»
    # catch-all go, because that is where cardiac labels land.  It is also what
    # a saved tab of an older build opens with.
    ReportProfile(
        id=PROFILE_ULTRASOUND,
        title_key="report.title.ultrasound",
        excluded_groups=_CARDIAC_GROUPS | {GROUP_OTHER},
    ),
)

_BY_ID: Final[dict[str, ReportProfile]] = {profile.id: profile for profile in PROFILES}

#: The formats in the order the header shows them.  The first one is the
#: fallback for an unknown id — a saved tab of an older build must open.
PROFILE_ORDER: Final[tuple[str, ...]] = tuple(profile.id for profile in PROFILES)

DEFAULT_PROFILE_ID: Final[str] = PROFILE_ECHO


def normalize_profile_id(profile_id: str | None) -> str:
    """A known format id, or the default one (never an unknown string)."""
    if profile_id in _BY_ID:
        return str(profile_id)
    return DEFAULT_PROFILE_ID


def profile(profile_id: str | None) -> ReportProfile:
    """The format named by *profile_id*, or the default one."""
    return _BY_ID[normalize_profile_id(profile_id)]


def profile_for_study(*, cardiac: bool) -> str:
    """The format a study starts with.

    ``cardiac`` is the answer of the positive cardiac classifier
    (:func:`echo_personal_tool.domain.services.cardiac_study.is_cardiac_study`).
    A cardiac study opens as «ЭхоКГ», anything else as the generic protocol; the
    physician can override either way in the header.
    """
    return PROFILE_ECHO if cardiac else PROFILE_ULTRASOUND


def profile_title(profile_id: str | None, translate: Callable[[str], str]) -> str:
    """Localised title of the document for this format."""
    return translate(profile(profile_id).title_key)
