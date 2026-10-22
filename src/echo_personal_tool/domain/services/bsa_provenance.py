"""Record-level BSA provenance: one wording for panel, report and PDF (QH-1b.2, slice 2).

Slice 1 answered "is this derived result still based on the BSA it was computed
with?" for values the application recomputes. The stored record answers a
different question: *which* BSA were the results it carries normalised by, and
is that still what the open study provides? This module turns the two bases
into that verdict and into the single human sentence the three surfaces show —
the calculators panel, the text report and the PDF must never word it
differently (spec §5.2, "одна application-проекция feeds UI/text/PDF").

Freshness stays separate from QC: ``fresh`` means the record and the study
agree on the BSA, not that the number is clinically valid.
"""

from __future__ import annotations

from echo_personal_tool.domain.models.result_provenance import (
    BSA_SOURCE_DERIVED,
    BSA_SOURCE_MANUAL,
    REASON_INPUT_CHANGED,
    REASON_INPUT_MISSING,
    REASON_LEGACY_NO_PROVENANCE,
    BsaBasis,
    BsaRecordStatus,
    Freshness,
)
from echo_personal_tool.domain.services.bsa_freshness import evaluate_bsa_freshness
from echo_personal_tool.domain.translation import tr

#: Reason codes that explain a stale record, in the order they are shown.
_REASON_KEYS = {
    "manual_override": "provenance.bsa_reason_manual",
    "height_weight_changed": "provenance.bsa_reason_height_weight",
    "input_changed": "provenance.bsa_reason_input",
}


def evaluate_bsa_record_status(recorded: BsaBasis | None, current: BsaBasis | None) -> BsaRecordStatus | None:
    """Freshness of the stored record against the open study, or ``None``.

    ``None`` means "nothing to report", which keeps two common situations free
    of warnings: a study with no BSA at all (nothing is indexed, nothing was
    recorded) and a record whose results were never BSA-normalised.

    The full rule set:

    - the study has no BSA now and the record had none either → nothing to say;
    - the study has no BSA now but the record was normalised → ``unavailable``
      (the stored numbers cannot be reproduced from the present inputs);
    - the record carries no basis (v1–v3 document) → ``unverified``; the origin
      is not guessed, which is exactly what the spec asks for legacy records;
    - the record was written without a BSA, the study has one now → ``stale``
      (its inputs changed since the write);
    - otherwise → the verdict of :func:`evaluate_bsa_freshness`.
    """
    has_current = current is not None and current.value is not None
    if not has_current:
        if recorded is not None and recorded.value is not None:
            return BsaRecordStatus(Freshness.UNAVAILABLE.value, (REASON_INPUT_MISSING,), recorded, current)
        return None
    if recorded is None:
        return BsaRecordStatus(Freshness.UNVERIFIED.value, (REASON_LEGACY_NO_PROVENANCE,), recorded, current)
    if recorded.value is None:
        return BsaRecordStatus(Freshness.STALE.value, (REASON_INPUT_CHANGED,), recorded, current)
    verdict = evaluate_bsa_freshness(recorded, current)
    return BsaRecordStatus(verdict.freshness, verdict.reasons, recorded, current)


def bsa_source_label(basis: BsaBasis | None) -> str:
    """Where the BSA came from: manual entry, Du Bois estimate, or nothing."""
    if basis is None or basis.value is None:
        return tr("provenance.bsa_source_missing")
    if basis.source == BSA_SOURCE_MANUAL:
        return tr("provenance.bsa_source_manual")
    if basis.source == BSA_SOURCE_DERIVED:
        return tr("provenance.bsa_source_derived")
    return tr("provenance.bsa_source_missing")


def bsa_record_note(status: BsaRecordStatus | None) -> str | None:
    """The one sentence about the record's BSA, or ``None`` when it is fresh."""
    if status is None or not status.needs_attention:
        return None
    if status.freshness == "unavailable":
        return tr("provenance.bsa_record_unavailable")
    if status.freshness == "unverified":
        return tr("provenance.bsa_record_unverified")

    recorded = status.recorded.value if status.recorded is not None else None
    current = status.current.value if status.current is not None else None
    if recorded is None or current is None:
        return tr("provenance.bsa_record_unavailable")
    reasons = "; ".join(tr(_REASON_KEYS[code]) for code in status.reasons if code in _REASON_KEYS)
    note = tr("provenance.bsa_record_stale").format(
        recorded=f"{recorded:.2f}",
        source=bsa_source_label(status.recorded),
        current=f"{current:.2f}",
    )
    return tr("provenance.bsa_record_reasons").format(note=note, reasons=reasons) if reasons else note
