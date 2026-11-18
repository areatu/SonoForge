"""The printable report shared by the sheet and all export formats."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from echo_personal_tool.domain.models.report_repeat import ReportRepeat
from echo_personal_tool.domain.models.value_origin import ValueOrigin
from echo_personal_tool.domain.services.report_groups import GROUP_OTHER
from echo_personal_tool.domain.translation import tr


@dataclass(frozen=True)
class ReportValue:
    """One measured parameter as the report shows it."""

    label: str
    value: str
    unit: str = ""
    norm: str = ""
    pathological: bool = False
    group: str = GROUP_OTHER
    #: Number of repeats that actually contributed to an averaged value (D-23).
    #: Kept separate from ``value`` so norms and machine consumers still see
    #: the unannotated numeric result.
    sample_count: int | None = None
    #: Recorded lineage for the «откуда значение» card (UI-4 PR-4).  ``None``
    #: means nothing was recorded: the card says so instead of guessing.
    origin: ValueOrigin | None = None
    #: Stable identifier of this row inside the document (item 9 of the
    #: 2026-11-06 list): ``group:parameter-id:ordinal``.  Hiding a row is addressed by
    #: this key, not by its position, so the choice survives other rows being
    #: hidden or restored.  Empty for rows the builder does not own (the
    #: «не оценивалось» marks appended by the window).
    key: str = ""
    #: Sample SD and coefficient of variation of the selected repeats
    #: (issue 559).  Kept as strings so the machine-readable ``value`` stays
    #: the plain mean; the human value adds them after the ``n`` suffix.
    repeat_sd: str = ""
    repeat_cv: str = ""
    #: Untranslated parameter name, distinct from the acquisition identity.
    parameter_id: str = ""
    #: Interactive source choices, not additional printable rows.
    repeat: ReportRepeat | None = None

    @property
    def display_value(self) -> str:
        """Value plus the localized count of samples entering a repeat mean."""
        text = self.value
        if self.sample_count is not None and self.sample_count > 1:
            text += tr("domain.report.repeat_suffix", count=self.sample_count)
        if self.repeat_sd:
            text += tr("domain.report.repeat_sd", sd=self.repeat_sd)
        if self.repeat_cv:
            text += tr("domain.report.repeat_cv", cv=self.repeat_cv)
        return text


@dataclass(frozen=True)
class ReportGroup:
    title: str
    key: str
    values: tuple[ReportValue, ...]
    #: Footnotes printed under the group table (calculations: provenance of
    #: the inputs, assumptions, warnings and the RUO statement).
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatientInfo:
    """Editable report header; empty strings mean "not filled in"."""

    name: str = ""
    patient_id: str = ""
    birth_date: str = ""
    age: str = ""
    sex: str = ""
    study_date: str = ""
    height_cm: float | None = None
    weight_kg: float | None = None
    bsa_m2: float | None = None
    physician: str = ""
    institution: str = ""
    indication: str = ""
    conclusion: str = ""
    equipment: str = ""


@dataclass(frozen=True)
class ReportDocument:
    patient: PatientInfo = field(default_factory=PatientInfo)
    groups: tuple[ReportGroup, ...] = ()
    #: Printed title of the sheet (item 7 of the 2026-11-06 list).  Empty means
    #: the default «Протокол ЭхоКГ», so a document built before the report
    #: formats existed still prints exactly what it printed then.
    title: str = ""
    #: Format id the document was built for (``echo`` / ``ultrasound_generic``).
    #: Kept in the document so CSV/JSON exports and the header of the sheet name
    #: the same thing as the PDF.
    profile_id: str = ""
    #: Export status (#555): a draft is not a signed-off protocol. The JSON
    #: and CSV exports and the report-mode status banner print it; the PDF
    #: sheet does not (2026-11-16 list, item 5) — protocols may be focused
    #: and partial, and the printed sheet is the protocol itself.
    draft: bool = False
    #: Export-level warnings (no scale, stale record, unreviewed contours),
    #: already localized. Kept in the document so the banner and the machine
    #: exports say the same thing.
    notices: tuple[str, ...] = ()

    @property
    def status_text(self) -> str:
        """Localized export status, the same words in PDF, JSON and CSV."""
        return tr("report.status.draft" if self.draft else "report.status.final")

    @property
    def has_measurements(self) -> bool:
        return any(group.values for group in self.groups)

    @property
    def pathological_values(self) -> tuple[ReportValue, ...]:
        return tuple(value for group in self.groups for value in group.values if value.pathological)


def without_values(document: ReportDocument, hidden_keys: Iterable[str]) -> ReportDocument:
    """Drop the rows the physician hid from the sheet (item 9).

    The filter works on the built document, once, so the preview, the PDF, the
    CSV and the JSON all lose the same rows; a group that becomes empty
    disappears with its notes.  Unknown keys are ignored, which keeps a study
    reload from resurrecting a row that no longer exists.
    """
    hidden = frozenset(key for key in hidden_keys if key)
    if not hidden:
        return document
    groups: list[ReportGroup] = []
    dropped = False
    for group in document.groups:
        values = tuple(value for value in group.values if value.key not in hidden)
        if not values:
            dropped = True
            continue
        if len(values) != len(group.values):
            dropped = True
            groups.append(replace(group, values=values))
        else:
            groups.append(group)
    return replace(document, groups=tuple(groups)) if dropped else document
