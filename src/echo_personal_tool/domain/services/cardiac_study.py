"""Does this clip come from an echocardiographic study? (ТЗ 2026-10-23, п. 1).

The viewer offers to *name* a free caliper after it is drawn («Подписать
измерение»): a list of the measurements of the catalog, searchable, five quick
numbers.  That is a cardiology affordance — in a cardiac study a distance almost
always *is* one of a known set (КДР, ЗСЛЖ, ЛП), and the label feeds the
calculators and the report.

In general ultrasound (abdomen, thyroid, kidneys) the set is open-ended: there
are dozens of distances per organ and no catalog to name them from, so the
window turns a two-click measurement into a dialog with a search field.  The
window is therefore shown **only for a study that is positively identified as
cardiac**, and never when the identification fails: a wrong guess costs more
than a missing convenience, and a missing guess is what a general-ultrasound
user would call a defect.

Positive evidence comes from the DICOM header, in this order:

* ``BodyPartExamined`` (0018,0015) — ``HEART`` / ``CARDIAC``;
* ``SeriesDescription`` / ``StudyDescription`` — the scanner's own preset name
  (``Adult Echo``, ``ЭхоКГ``, ``A4C``, ``Apical 4 chamber`` …).

The probe is **not** a usable signal: a cardiac preset and an abdominal preset
can be driven by the same transducer, and the DICOM header does not carry the
preset in a standard field.  That is why the rule is "yes only on positive
evidence" rather than "no on negative evidence".

The module is Qt-free and takes plain strings, so the rule is testable without
a viewer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: Body parts that mean "cardiac" on their own.
CARDIAC_BODY_PARTS = frozenset({"HEART", "CARDIAC"})

#: Single tokens that only occur in a cardiac study.
#:
#: Deliberately narrow: «эхо» alone is Russian shorthand for *any* ultrasound
#: («эхо-признаки»), and «US» is the modality, so neither is evidence.
CARDIAC_WORDS = frozenset(
    {
        "echo",
        "echocardiography",
        "echocardiogram",
        "cardiac",
        "cardio",
        "heart",
        "tte",
        "tee",
        # Russian / Ukrainian spellings of «эхокардиография».
        "эхокг",
        "эхокардиография",
        "эхокардиограммы",
        "ехокг",
        "кардио",
        "кардиальная",
        "сердце",
        # Cardiac views, as scanners spell them in the preset name.
        "a2c",
        "a3c",
        "a4c",
        "a5c",
        "apical",
        "plax",
        "psax",
        "parasternal",
        "subcostal",
        "suprasternal",
        "4ch",
        "2ch",
        "3ch",
        "lvot",
        "rvot",
        "tee-me",
    }
)

#: Two-word phrases (tokens joined by a space) that carry the same meaning as a
#: single word but are split by the tokeniser.
CARDIAC_PHRASES = (
    ("apical", "4", "chamber"),
    ("apical", "2", "chamber"),
    ("apical", "3", "chamber"),
    ("four", "chamber"),
    ("two", "chamber"),
    ("left", "ventricle"),
    ("right", "ventricle"),
    ("left", "atrium"),
    ("right", "atrium"),
    ("mitral", "valve"),
    ("aortic", "valve"),
    ("tricuspid", "valve"),
    ("pulmonary", "valve"),
    ("diastolic", "function"),
    ("systolic", "function"),
    ("cardiac", "output"),
    ("lv", "function"),
)

_TOKEN_SPLIT = re.compile(r"[^\w]+", re.UNICODE)

#: Filler words that scanners insert between the meaningful tokens
#: («Adult Echo — 2D», «Echo/Cardiac/2D»).
_FILLER = frozenset({"adult", "pediatric", "paediatric", "2d", "3d", "us", "1", "2", "3", "4", "5"})


def _tokens(text: str) -> list[str]:
    lowered = str(text or "").casefold().replace("ё", "е")
    return [token for token in _TOKEN_SPLIT.split(lowered) if token]


def _content_tokens(tokens: Iterable[str]) -> list[str]:
    return [token for token in tokens if token not in _FILLER]


def text_marks_cardiac(text: str) -> bool:
    """True when this single DICOM string is positive evidence of a cardiac study."""
    tokens = _tokens(text)
    if not tokens:
        return False
    if any(token in CARDIAC_WORDS for token in tokens):
        return True
    content = _content_tokens(tokens)
    for phrase in CARDIAC_PHRASES:
        size = len(phrase)
        for index in range(len(content) - size + 1):
            if tuple(content[index : index + size]) == phrase:
                return True
    return False


def body_part_marks_cardiac(body_part: str) -> bool:
    """True when ``BodyPartExamined`` says the study is cardiac."""
    return str(body_part or "").strip().upper() in CARDIAC_BODY_PARTS


def is_cardiac_study(
    *,
    body_part: str = "",
    series_description: str = "",
    study_description: str = "",
) -> bool:
    """Should the study be treated as echocardiography?

    Answers ``True`` only on positive evidence — see the module docstring.  An
    empty header (a plain folder of MP4/JPEG clips, a DICOM without descriptions)
    is ``False``: the naming window stays out of the way of general ultrasound.
    """
    if body_part_marks_cardiac(body_part):
        return True
    return text_marks_cardiac(series_description) or text_marks_cardiac(study_description)
