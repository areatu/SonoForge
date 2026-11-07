"""Report template: which header fields print, in what order, and how.

The owner asked for a form («бланк») of the report: his clinic prints its own
set of header fields, and a field the study does not use should not take a line
of the sheet (item 12 of the 2026-11-06 list).

This is an **in-application** template, not a template language.  A PDF is
assembled by reportlab, and letting a file describe arbitrary layout would mean
running arbitrary layout code with none of the guarantees of the sheet (the
preview is the exact exported bytes).  So the template is a small
versioned dataclass: the ordered list of header fields, three visibility
switches and the column count.  It is serialised to JSON for
``UserPreferences.report_template_json`` and can be moved to another computer
as a file; anything unreadable decodes to the default template instead of
producing a half-printed sheet.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

#: Version of the stored template document.
TEMPLATE_VERSION = 1

#: Header fields, in the order the default template prints them.  The ids are
#: stable: a stored template names them, and a renamed label must not lose the
#: physician's choice.
FIELD_NAME = "name"
FIELD_PATIENT_ID = "patient_id"
FIELD_SEX = "sex"
FIELD_BIRTH_DATE = "birth_date"
FIELD_AGE = "age"
FIELD_STUDY_DATE = "study_date"
FIELD_HEIGHT = "height"
FIELD_WEIGHT = "weight"
FIELD_BSA = "bsa"
FIELD_INSTITUTION = "institution"
FIELD_EQUIPMENT = "equipment"
FIELD_PHYSICIAN = "physician"
FIELD_INDICATION = "indication"

HEADER_FIELDS: tuple[str, ...] = (
    FIELD_NAME,
    FIELD_PATIENT_ID,
    FIELD_SEX,
    FIELD_BIRTH_DATE,
    FIELD_AGE,
    FIELD_STUDY_DATE,
    FIELD_HEIGHT,
    FIELD_WEIGHT,
    FIELD_BSA,
    FIELD_INSTITUTION,
    FIELD_EQUIPMENT,
    FIELD_PHYSICIAN,
    FIELD_INDICATION,
)

#: Localisation key of every field label.
FIELD_LABEL_KEYS: Mapping[str, str] = {
    FIELD_NAME: "report.patient_name",
    FIELD_PATIENT_ID: "report.patient_id",
    FIELD_SEX: "report.sex",
    FIELD_BIRTH_DATE: "report.birth_date",
    FIELD_AGE: "report.age",
    FIELD_STUDY_DATE: "report.study_date",
    FIELD_HEIGHT: "report.height",
    FIELD_WEIGHT: "report.weight",
    FIELD_BSA: "report.bsa",
    FIELD_INSTITUTION: "report.institution",
    FIELD_EQUIPMENT: "report.equipment",
    FIELD_PHYSICIAN: "report.physician",
    FIELD_INDICATION: "report.indication",
}

COLUMNS_ONE = 1
COLUMNS_TWO = 2


@dataclass(frozen=True)
class ReportTemplate:
    """The printable form of the protocol."""

    #: Header fields to print, in print order.  A field missing from the list
    #: is not printed even when the study has a value for it.
    header_fields: tuple[str, ...] = HEADER_FIELDS
    #: Print the group footnotes (assumptions, warnings, the RUO statement).
    show_notes: bool = True
    #: Print the conclusion block at the end of the sheet.
    show_conclusion: bool = True
    #: Print the signature block.
    show_signature: bool = True
    #: ``1`` or ``2``: one column of groups, or two side-by-side columns.
    columns: int = COLUMNS_ONE
    #: Human-readable name of the form; it travels with an exported file so a
    #: clinic can keep several forms as files and import the one it needs.
    name: str = ""
    version: int = TEMPLATE_VERSION

    def prints_field(self, field_id: str) -> bool:
        return field_id in self.header_fields

    @property
    def normalized_columns(self) -> int:
        return COLUMNS_TWO if self.columns == COLUMNS_TWO else COLUMNS_ONE

    def with_field_order(self, fields: Sequence[str]) -> ReportTemplate:
        """Reorder (or trim) the printed fields, keeping only known ids."""
        seen: list[str] = []
        for field_id in fields:
            if field_id in FIELD_LABEL_KEYS and field_id not in seen:
                seen.append(field_id)
        return replace(self, header_fields=tuple(seen))

    def as_dict(self) -> dict[str, object]:
        return {
            "version": TEMPLATE_VERSION,
            "name": self.name,
            "header_fields": list(self.header_fields),
            "show_notes": bool(self.show_notes),
            "show_conclusion": bool(self.show_conclusion),
            "show_signature": bool(self.show_signature),
            "columns": self.normalized_columns,
        }


def default_template(*, name: str = "") -> ReportTemplate:
    """The template of older builds: every field, one column, everything on."""
    return ReportTemplate(name=name)


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    if value is None:
        return default
    return default


def decode_template(raw: object, *, name: str = "") -> ReportTemplate:
    """Read a stored template; garbage decodes to the default one.

    Never raises and never returns a half-valid form: an unreadable settings
    value must give the physician the standard sheet, not a truncated header.
    Where the caller must *tell* the physician that the file was unreadable
    (an imported form), :func:`read_template_document` reports ``None``
    instead of silently substituting the default.
    """
    parsed = read_template_document(raw, name=name)
    return parsed if parsed is not None else default_template(name=name)


def read_template_document(raw: object, *, name: str = "") -> ReportTemplate | None:
    """Read a template document, ``None`` when it is not one.

    Unlike :func:`decode_template`, this makes «the file cannot be read» a
    distinct answer from «the file says: the standard form».
    """
    if isinstance(raw, ReportTemplate):
        return raw
    data: object = raw
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(data, Mapping):
        return None
    stored_version = data.get("version")
    if isinstance(stored_version, int) and stored_version > TEMPLATE_VERSION:
        # A newer build wrote this file: the fields we do not know could be
        # anything, so the safe answer is the standard form.
        return None

    template = default_template(name=str(data.get("name") or name))
    fields_raw = data.get("header_fields")
    if isinstance(fields_raw, list):
        trimmed = template.with_field_order([item for item in fields_raw if isinstance(item, str)])
        # An empty list is a real choice («no header fields at all»), so it is
        # kept; only a list with no known id at all falls back to the default.
        if fields_raw and not trimmed.header_fields:
            return template
        template = trimmed
    return replace(
        template,
        show_notes=_as_bool(data.get("show_notes"), template.show_notes),
        show_conclusion=_as_bool(data.get("show_conclusion"), template.show_conclusion),
        show_signature=_as_bool(data.get("show_signature"), template.show_signature),
        columns=COLUMNS_TWO if data.get("columns") == COLUMNS_TWO else COLUMNS_ONE,
    )


def encode_template(template: ReportTemplate) -> str:
    """Serialise a template for the settings store or a file."""
    return json.dumps(template.as_dict(), ensure_ascii=False, sort_keys=False)
