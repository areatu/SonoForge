"""Study profiles: what kind of examination the physician is working on.

The owner works with echocardiography *and* with vascular, abdominal and
thyroid ultrasound in the same application, and asked for buttons that switch
the study type (item 11 of the 2026-11-06 list).  A profile is exactly that
kind of statement, and it is a statement about the *study*, not about the
frame: the panel contexts (2D / M / Doppler / vessels) describe how the picture
was acquired, while a study profile decides which parts of the tool catalog are
relevant at all and which report format the protocol uses.

The profile never rewrites the stored layout.  It is a *filter* applied when
the panel is built (:func:`echo_personal_tool.domain.tool_panel_view.panel_view`),
so switching profiles loses nothing: a measurement made before the switch, a
hidden tool and a user section all survive, and switching back brings the old
set of sections back unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from echo_personal_tool.domain.services.report_profiles import PROFILE_ECHO, PROFILE_ULTRASOUND

#: Every catalog section that exists today.  A study profile lists the ones it
#: wants; sections of other profiles are simply not shown.
SECTION_GENERAL = "general"
SECTION_LV = "lv"
SECTION_LV_AUTO = "lv_auto"
SECTION_AORTA = "aorta"
SECTION_LA = "la"
SECTION_RA = "ra"
SECTION_RV = "rv"
SECTION_DIASTOLIC = "diastolic"
SECTION_MV_AV = "mv_av"
SECTION_TV_PV = "tv_pv"
SECTION_STRAIN = "strain"
SECTION_VESSELS = "vessels"
SECTION_MMODE = "mmode"
SECTION_PRECEREBRAL = "precerebral"
SECTION_ABDOMEN = "abdomen"
SECTION_KIDNEY = "kidney"
SECTION_THYROID = "thyroid"

#: The sections of a cardiac study: everything but the vascular block, which
#: moved to its own profile (the owner's complaint — «Сосуды» crowded the echo
#: panel).
_CARDIAC_SECTIONS: tuple[str, ...] = (
    SECTION_GENERAL,
    SECTION_LV,
    SECTION_LV_AUTO,
    SECTION_AORTA,
    SECTION_LA,
    SECTION_RA,
    SECTION_RV,
    SECTION_DIASTOLIC,
    SECTION_MV_AV,
    SECTION_TV_PV,
    SECTION_STRAIN,
    SECTION_MMODE,
)

#: The sections of a precerebral-artery study: calipers, the vascular block,
#: the named-artery measurements (БЦС, ОСА/ВСА/НСА/позвоночные) and the
#: spectral modes the flow measurements are taken in.
_VASCULAR_SECTIONS: tuple[str, ...] = (
    SECTION_GENERAL,
    SECTION_VESSELS,
    SECTION_PRECEREBRAL,
    SECTION_MMODE,
)

#: Abdominal ultrasound: the generic calipers and planimetry polygons plus the
#: organ measurements (liver, gallbladder, vessels, pancreas, aorta) and the
#: renal block (kidneys and bladder).
_ABDOMINAL_SECTIONS: tuple[str, ...] = (
    SECTION_GENERAL,
    SECTION_ABDOMEN,
    SECTION_KIDNEY,
)

#: Renal ultrasound: the generic tools and the renal block only.
_KIDNEY_SECTIONS: tuple[str, ...] = (
    SECTION_GENERAL,
    SECTION_KIDNEY,
)

#: Thyroid ultrasound: the generic tools and the gland block (lobes, isthmus).
_THYROID_SECTIONS: tuple[str, ...] = (
    SECTION_GENERAL,
    SECTION_THYROID,
)

STUDY_PROFILE_ECHO = "builtin.adult_echo"
STUDY_PROFILE_VASCULAR = "builtin.vascular"
STUDY_PROFILE_ABDOMEN = "builtin.abdomen"
STUDY_PROFILE_KIDNEY = "builtin.kidney"
STUDY_PROFILE_THYROID = "builtin.thyroid"


@dataclass(frozen=True)
class StudyProfile:
    """One examination type: its panel sections and its report format."""

    id: str
    title_key: str
    #: Catalog sections the panel shows, in catalog order.
    sections: tuple[str, ...]
    #: Report format of the protocol (item 7).  ``echo`` prints the cardiac
    #: groups, ``ultrasound_generic`` drops them.
    report_profile_id: str
    #: Whether a cardiac *DICOM* study should preselect this profile.  Only the
    #: echocardiography profile answers yes; the others are the physician's
    #: explicit choice.
    cardiac: bool = False

    def allows(self, section_key: str) -> bool:
        """Whether the section belongs to this study.

        User sections (``custom.*``) always belong: they are the physician's
        own, and a profile switch must not hide work they arranged themselves.
        """
        if section_key.startswith("custom."):
            return True
        return section_key in self.sections

    def filter_sections(self, keys: Iterable[str]) -> tuple[str, ...]:
        return tuple(key for key in keys if self.allows(key))


PROFILES: dict[str, StudyProfile] = {
    STUDY_PROFILE_ECHO: StudyProfile(
        id=STUDY_PROFILE_ECHO,
        title_key="study_profile.adult_echo",
        sections=_CARDIAC_SECTIONS,
        report_profile_id=PROFILE_ECHO,
        cardiac=True,
    ),
    STUDY_PROFILE_VASCULAR: StudyProfile(
        id=STUDY_PROFILE_VASCULAR,
        title_key="study_profile.vascular",
        sections=_VASCULAR_SECTIONS,
        report_profile_id=PROFILE_ULTRASOUND,
    ),
    STUDY_PROFILE_ABDOMEN: StudyProfile(
        id=STUDY_PROFILE_ABDOMEN,
        title_key="study_profile.abdomen",
        sections=_ABDOMINAL_SECTIONS,
        report_profile_id=PROFILE_ULTRASOUND,
    ),
    STUDY_PROFILE_KIDNEY: StudyProfile(
        id=STUDY_PROFILE_KIDNEY,
        title_key="study_profile.kidney",
        sections=_KIDNEY_SECTIONS,
        report_profile_id=PROFILE_ULTRASOUND,
    ),
    STUDY_PROFILE_THYROID: StudyProfile(
        id=STUDY_PROFILE_THYROID,
        title_key="study_profile.thyroid",
        sections=_THYROID_SECTIONS,
        report_profile_id=PROFILE_ULTRASOUND,
    ),
}

#: Display order of the switch — the order the owner listed the buttons in.
PROFILE_ORDER: tuple[str, ...] = (
    STUDY_PROFILE_ECHO,
    STUDY_PROFILE_VASCULAR,
    STUDY_PROFILE_ABDOMEN,
    STUDY_PROFILE_KIDNEY,
    STUDY_PROFILE_THYROID,
)

DEFAULT_PROFILE_ID = STUDY_PROFILE_ECHO


def normalize_profile_id(profile_id: str | None) -> str:
    """A known study profile; an unknown id reads as the default one."""
    value = (profile_id or "").strip()
    return value if value in PROFILES else DEFAULT_PROFILE_ID


def study_profile(profile_id: str | None) -> StudyProfile:
    """The profile for *profile_id* (the default for an unknown id)."""
    return PROFILES[normalize_profile_id(profile_id)]


def is_explicit(profile_id: str | None) -> bool:
    """Whether *profile_id* is a real choice the physician made.

    An empty value means «not chosen»: the study is classified from its DICOM
    header and the default profile applies.  The distinction matters for the
    report (item 7): a stored profile overrides the automatic format, a
    missing one must not.
    """
    return bool((profile_id or "").strip()) and normalize_profile_id(profile_id) == (profile_id or "").strip()


def profile_ids() -> tuple[str, ...]:
    """Every study profile id, in display order."""
    return PROFILE_ORDER


def section_keys(profile_id: str | None) -> tuple[str, ...]:
    """Catalog sections of a study profile, in catalog order."""
    return study_profile(profile_id).sections
