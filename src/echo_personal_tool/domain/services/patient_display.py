"""Human-readable formatting of DICOM patient/study attributes (pure helpers).

The Orthanc loader shows a dense list of studies; raw DICOM values such as
``"ИВАНОВ^ИВАН^ИВАНОВИЧ"``, ``"20240404"`` or ``"67"`` age codes are hostile to
reading.  Everything in this module is a pure function with no Qt dependency so
it can be unit-tested and reused by any presentation layer.
"""

from __future__ import annotations

from datetime import date, datetime

__all__ = [
    "format_person_name",
    "format_dicom_date",
    "format_dicom_time",
    "format_patient_age",
    "format_patient_sex",
    "format_size_mb",
    "format_patient_header",
    "format_relative_day",
    "plural_ru",
]


def _titlecase_word(word: str) -> str:
    """Capitalise a DICOM name component, tolerating ``-``/``'`` and spaces.

    All-uppercase input (the DICOM norm) is lowered first, so "ИВАНОВ-СМИРНОВ"
    becomes "Иванов-Смирнов"; mixed-case input such as "van der Berg" only gets
    its first letter (and hyphen/apostrophe parts) raised, so the author's
    capitalisation survives.
    """
    if not word:
        return word
    normalised = word.lower() if word.isupper() else word
    out: list[str] = []
    capitalise_next = True
    for char in normalised:
        if char in ("-", "'"):
            out.append(char)
            capitalise_next = True
            continue
        if char == " ":
            # Spaces inside a family name ("van der Berg") are never promoted.
            out.append(char)
            continue
        out.append(char.upper() if capitalise_next else char)
        capitalise_next = False
    return "".join(out)


def format_person_name(raw: str, *, fallback: str = "") -> str:
    """Convert a DICOM PN value into a readable "Фамилия Имя Отчество".

    DICOM stores person names as ``family^given^middle^prefix^suffix`` (PS3.5
    :term:`PN`), usually in upper case.  Values that already look like a plain
    human name (no ``^``) are returned unchanged apart from whitespace cleanup.

    >>> format_person_name("ИВАНОВ^ИВАН^ИВАНОВИЧ")
    'Иванов Иван Иванович'
    >>> format_person_name("Smith^John")
    'Smith John'
    >>> format_person_name("")
    '—'
    """
    text = (raw or "").strip().strip("^")
    if not text:
        return fallback
    if "^" not in text:
        return " ".join(text.split())
    components = [part.strip() for part in text.split("^")]
    while components and not components[-1]:
        components.pop()
    if not components:
        return fallback
    family = components[0]
    given = components[1] if len(components) > 1 else ""
    middle = components[2] if len(components) > 2 else ""
    prefix = components[3] if len(components) > 3 else ""
    suffix = components[4] if len(components) > 4 else ""
    ordered = [f"{prefix} {given}".strip() if prefix else given, middle]
    words = [_titlecase_word(family)] if family else []
    words += [_titlecase_word(w) for w in ordered if w]
    if suffix:
        words.append(suffix.upper())
    result = " ".join(words).strip()
    return result or fallback


def format_dicom_date(raw: str, *, fallback: str = "") -> str:
    """``"20240404"`` → ``"04.04.2024"``; anything else is returned as-is."""
    text = (raw or "").strip()
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[6:8]}.{text[4:6]}.{text[:4]}"
    return text or fallback


def format_dicom_time(raw: str) -> str:
    """``"113045.123"`` → ``"11:30"`` (best effort, never raises)."""
    text = (raw or "").strip().split("+")[0].split("-")[0]
    if len(text) < 4 or not text[:4].isdigit():
        return ""
    return f"{text[:2]}:{text[2:4]}"


def _parse_dicom_date(raw: str) -> date | None:
    text = (raw or "").strip()
    if len(text) < 8 or not text[:8].isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def format_patient_age(
    birth_date: str,
    study_date: str,
    *,
    year_forms: tuple[str, str, str] = ("год", "года", "лет"),
) -> str:
    """Return the patient's age at the study date ("67 лет", "3 мес.")."""
    birth = _parse_dicom_date(birth_date)
    study = _parse_dicom_date(study_date)
    if birth is None or study is None:
        # Without both dates the age is unknowable — never guess.
        return ""
    if study < birth:
        return ""
    years = study.year - birth.year - ((study.month, study.day) < (birth.month, birth.day))
    if years >= 1:
        return f"{years} {plural_ru(years, *year_forms)}"
    months = (study.year - birth.year) * 12 + study.month - birth.month
    months -= 1 if study.day < birth.day else 0
    months = max(months, 0)
    if months >= 1:
        return f"{months} мес."
    days = (study - birth).days
    return f"{days} дн."


def plural_ru(count: int, one: str, few: str, many: str) -> str:
    """Pick the Russian plural form for *count* (10-19 always take "many")."""
    remainder_100 = count % 100
    if 11 <= remainder_100 <= 14:
        return many
    remainder = count % 10
    if remainder == 1:
        return one
    if 2 <= remainder <= 4:
        return few
    return many


def format_patient_sex(raw: str) -> str:
    """``"M"``/``"F"``/``"O"`` → ``"М"``/``"Ж"`` (empty for unknown)."""
    value = (raw or "").strip().upper()[:1]
    return {"M": "М", "F": "Ж", "O": "Д"}.get(value, "")


def format_size_mb(size_mb: float | int | None, *, mb: str = "МБ", gb: str = "ГБ") -> str:
    """Compact size label: ``0.4 МБ``, ``42 МБ``, ``1.2 ГБ``."""
    try:
        value = float(size_mb)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    if value >= 1024:
        return f"{value / 1024:.1f} {gb}"
    if value >= 10:
        return f"{value:.0f} {mb}"
    return f"{value:.1f} {mb}"


def format_patient_header(study: object, *, age_year_forms: tuple[str, str, str] | None = None) -> str:
    """One-line patient banner for the series pane header.

    ``Иванов Иван Иванович · М · 67 лет · ID 1234567``
    """
    name = format_person_name(getattr(study, "patient_name", "") or "", fallback="—")
    parts = [name]
    sex = format_patient_sex(getattr(study, "patient_sex", "") or "")
    age = format_patient_age(
        getattr(study, "patient_birth_date", "") or "",
        getattr(study, "study_date", "") or "",
        **({"year_forms": age_year_forms} if age_year_forms else {}),
    )
    demographics = " · ".join(part for part in (sex, age) if part)
    if demographics:
        parts.append(demographics)
    patient_id = (getattr(study, "patient_id", "") or "").strip()
    if patient_id:
        parts.append(f"ID {patient_id}")
    return " · ".join(parts)


def format_relative_day(
    raw_date: str,
    *,
    today_label: str = "",
    yesterday_label: str = "",
    now: datetime | None = None,
) -> str:
    """``"12.03.2024"`` — or today's/yesterday's label when provided.

    Labels come from the caller (i18n) so this module stays language-neutral.
    """
    parsed = _parse_dicom_date(raw_date)
    if parsed is None:
        return (raw_date or "").strip()
    delta = ((now or datetime.now()).date() - parsed).days
    if delta == 0 and today_label:
        return today_label
    if delta == 1 and yesterday_label:
        return yesterday_label
    return format_dicom_date(raw_date)
