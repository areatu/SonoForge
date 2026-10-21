"""Where a report value came from (UI-4 PR-4, spec §4.6).

The report mode answers «откуда значение» from the document itself: every
:class:`~echo_personal_tool.domain.services.report_builder.ReportValue` may
carry a :class:`ValueOrigin` — the clip and frame a caliper was drawn on, the
measurement identity with its revision, and the inputs a calculator consumed.

The rule of the spec is honesty, not completeness (QH §5.3, items 3 and 6):
where the source was never recorded, the value has **no** origin and the card
says «происхождение не записано» with the ``unverified`` status.  Nothing is
guessed from the current study state — a value that cannot prove its lineage
must not look as if it could.

Pure: no Qt, no infrastructure.  ``freshness`` values are the ones of
:mod:`echo_personal_tool.domain.models.result_provenance`.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.models.result_provenance import Freshness

#: A direct measurement drawn by the user (primary data).
KIND_MEASUREMENT = "measurement"
#: A value computed from other values (Simpson, Teichholz, strain…).
KIND_DERIVED = "derived"
#: A calculator output (Э11) over study inputs.
KIND_CALCULATOR = "calculator"
#: An explicit user mark, not a measurement («не оценивалось»).
KIND_MANUAL = "manual"

#: Stable method ids; the presentation layer translates them (never prose here).
METHOD_LINEAR_CALIPER = "linear_caliper"
METHOD_DOPPLER_CALIPER = "doppler_caliper"
METHOD_VESSEL = "vessel"
METHOD_PLANIMETER = "planimeter"
METHOD_CALCULATOR = "calculator"
METHOD_NOT_EVALUATED = "not_evaluated"

#: The value has no recorded lineage (shown as «происхождение не записано»).
REASON_NOT_RECORDED = "provenance_not_recorded"

#: Input source codes of the calculator engine, kept as codes for the card.
INPUT_SOURCES: tuple[str, ...] = (
    "measured",
    "dicom",
    "estimate",
    "patient",
    "derived",
    "manual",
    "missing",
)


@dataclass(frozen=True)
class ClipSource:
    """One clip (and optionally one frame) a value was taken from.

    ``sop_instance_uid`` is the DICOM identity, not a file name: the window
    translates it into the clip label it shows in the gallery.
    """

    sop_instance_uid: str = ""
    frame_index: int | None = None

    @property
    def has_clip(self) -> bool:
        return bool(self.sop_instance_uid)


@dataclass(frozen=True)
class OriginInput:
    """One input a derived value or a calculator output was computed from."""

    id: str
    value: str = ""
    source: str = ""


@dataclass(frozen=True)
class ValueOrigin:
    """Recorded lineage of one report value.

    ``method_id`` is a stable code (:data:`METHOD_LINEAR_CALIPER` …), so the
    card can be re-translated on a language switch without rebuilding the
    document.  ``sources`` is empty when the method records no clip (a
    planimeter contour, a calculator output) — that is a fact, not a gap.
    """

    kind: str
    method_id: str
    measurement_id: str = ""
    revision: int = 0
    sources: tuple[ClipSource, ...] = ()
    inputs: tuple[OriginInput, ...] = ()
    freshness: str = Freshness.UNVERIFIED.value
    reason: str = ""

    @property
    def recorded(self) -> bool:
        """Whether anything beyond the method was actually recorded."""
        return bool(self.measurement_id or self.sources or self.inputs)

    @property
    def clips(self) -> tuple[ClipSource, ...]:
        return tuple(source for source in self.sources if source.has_clip)


def measurement_origin(
    method_id: str,
    *,
    measurement_id: str = "",
    revision: int = 0,
    sop_instance_uid: str = "",
    frame_index: int | None = None,
) -> ValueOrigin:
    """Origin of a value read off the image by the user (fresh, primary data).

    A caliper without a stored clip keeps the method and the measurement id
    but no source: older documents carry an empty ``sop_instance_uid`` and the
    card must not invent one.
    """
    sources = (ClipSource(sop_instance_uid, frame_index),) if sop_instance_uid else ()
    return ValueOrigin(
        kind=KIND_MEASUREMENT,
        method_id=method_id,
        measurement_id=measurement_id,
        revision=revision,
        sources=sources,
        freshness=Freshness.FRESH.value,
    )


def calculator_origin(
    calculator_id: str,
    *,
    inputs: tuple[OriginInput, ...] = (),
) -> ValueOrigin:
    """Origin of a calculator output: the inputs it consumed, with sources."""
    return ValueOrigin(
        kind=KIND_CALCULATOR,
        method_id=METHOD_CALCULATOR,
        inputs=inputs,
        freshness=Freshness.FRESH.value if inputs else Freshness.UNVERIFIED.value,
        reason="" if inputs else REASON_NOT_RECORDED,
    )


def unrecorded_origin(method_id: str, *, kind: str = KIND_DERIVED) -> ValueOrigin:
    """A known method whose input lineage was not stored (``unverified``)."""
    return ValueOrigin(
        kind=kind,
        method_id=method_id,
        freshness=Freshness.UNVERIFIED.value,
        reason=REASON_NOT_RECORDED,
    )
