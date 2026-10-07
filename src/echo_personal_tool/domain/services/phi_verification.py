"""Verification of a masked / de-identified result (design doc §8, layers 1-2).

Two independent checks live here, both pure and both PHI-free by construction:

* **Bytes (layer 1).**  The identifiers that were in the source — name, patient
  ID, the ``OtherPatientIDs*`` duplicates, study IDs, the file name — are
  searched in the produced bytes (tags, private blocks, container metadata).
  The result names the *fields* that leaked, never their values, so the report
  can be logged or shown without becoming a new leak.
* **Pixels (layer 2).**  The text detector is run on the masked frame: inside
  the masked band (did the fill really erase the glyphs?) and just below it
  (was the band too small?).  This is the only automated check that catches the
  main failure mode of the whole feature, because burned-in text is not
  present in the bytes and a substring test cannot see it (§8).

The pixel check needs the detector, which is behind a setting; the byte check is
always cheap enough to run.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.services.phi_mask import MaskPlan
from echo_personal_tool.domain.services.phi_text_detector import (
    TextReport,
    detect_text_rows,
)

#: Portion of the frame below the masked band that is checked for leftover text.
#: The band is clamped to the first ultrasound panel row, so "just below" is the
#: row that a too-small band would leave behind.
DEFAULT_MARGIN_RATIO = 1.0

#: Hard cap on that margin, so a narrow band on a huge frame cannot make the
#: check walk into the sector and report anatomy as text.
MAX_MARGIN_ROWS = 320

#: A string shorter than this is not searched for in the bytes: "US" or "1"
#: would match everywhere and turn the check into noise.
MIN_IDENTIFIER_LENGTH = 4

#: DICOM strings reach the file in the encoding of the producer.  Russian
#: scanners of the corpus are cp1251/UTF-8, some tools write Latin-1, and a few
#: put UTF-16 in private blocks.
_ENCODINGS = ("utf-8", "cp1251", "latin-1", "utf-16-le")

#: Reasons a pixel check can be inconclusive rather than clean.
_PIXEL_OK = "ok"


@dataclass(frozen=True)
class ByteVerification:
    """Result of searching the produced bytes for the source identifiers."""

    ok: bool
    #: Names of the fields whose value was still found (never the values).
    leaked_fields: tuple[str, ...] = ()
    #: Fields that were searched and found, but which the chosen options keep
    #: on purpose (quasi-identifiers, private blocks): informational only.
    kept_fields: tuple[str, ...] = ()
    checked_fields: tuple[str, ...] = ()
    reason: str = ""

    @property
    def summary(self) -> str:
        """Short, PHI-free description for logs and the status bar."""
        if not self.ok:
            return f"bytes: {len(self.leaked_fields)} identifier field(s) survived: {', '.join(self.leaked_fields)}"
        text = f"bytes: clean ({len(self.checked_fields)} identifier(s) checked)"
        if self.kept_fields:
            text += f", kept by option: {', '.join(self.kept_fields)}"
        return text


@dataclass(frozen=True)
class MaskVerification:
    """Result of running the text detector over a masked frame."""

    ok: bool
    #: Vertical extent of the mask that was verified, half-open.
    band: tuple[int, int] | None = None
    #: Detector on the *original* frame over the analysed region (diagnostics).
    detected: TextReport | None = None
    #: Detector on the masked frame *inside* the band.
    leftover: TextReport | None = None
    #: Detector on the masked frame *below* the band.
    outside: TextReport | None = None
    reason: str = ""

    @property
    def residual_rows(self) -> tuple[int, ...]:
        """Rows (y0) of everything that still looks like text."""
        rows: list[int] = []
        for report in (self.leftover, self.outside):
            if report is not None:
                rows.extend(row.y0 for row in report.rows)
        return tuple(sorted(rows))

    @property
    def summary(self) -> str:
        """Short, PHI-free description for logs and the status bar."""
        if self.reason and self.reason != _PIXEL_OK:
            return f"pixels: not verified ({self.reason})"
        if self.ok:
            return "pixels: clean"
        return f"pixels: {len(self.residual_rows)} text-like row(s) survived at y={list(self.residual_rows)}"


def identifier_variants(value: str) -> tuple[str, ...]:
    """Spellings of one identifier worth searching for in the bytes.

    Case variants because scanners write the name in capitals while the header
    may keep the original spelling, and DICOM name components separately, so a
    name stored as ``IVANOV^IVAN`` is still found when only the surname row is
    burned in.
    """
    text = str(value or "").strip()
    if not text:
        return ()

    variants: list[str] = []
    for candidate in (text, text.upper(), text.casefold()):
        for part in (candidate, *candidate.split("^")):
            part = part.strip()
            if len(part) >= MIN_IDENTIFIER_LENGTH and part not in variants:
                variants.append(part)
    return tuple(variants)


def verify_bytes(
    identifiers: dict[str, str],
    data: bytes,
    *,
    allowed_fields: tuple[str, ...] = (),
) -> ByteVerification:
    """Search ``data`` for the values of ``identifiers`` (layer 1).

    ``identifiers`` maps a field name to its source value.  Fields listed in
    ``allowed_fields`` are expected to be there — a quasi-identifier the user
    chose to keep is not a leak — and are only reported as kept.  The returned
    object carries field names only: a report that says "PatientName survived"
    is actionable, one that repeats the name is a second copy of the leak.
    """
    checked: list[str] = []
    leaked: list[str] = []
    kept: list[str] = []
    for field, value in identifiers.items():
        variants = identifier_variants(value)
        if not variants:
            continue
        checked.append(field)
        for variant in variants:
            if any(_encoded(variant, encoding) in data for encoding in _ENCODINGS):
                if field in allowed_fields:
                    kept.append(field)
                else:
                    leaked.append(field)
                break
    if not checked:
        return ByteVerification(ok=True, reason="nothing-to-check")
    return ByteVerification(
        ok=not leaked,
        leaked_fields=tuple(leaked),
        kept_fields=tuple(kept),
        checked_fields=tuple(checked),
        reason=_PIXEL_OK if not leaked else "leak",
    )


def _encoded(text: str, encoding: str) -> bytes:
    try:
        return text.encode(encoding)
    except (UnicodeEncodeError, LookupError):  # pragma: no cover - defensive
        return b"\x00never-matches\x00"


def top_band_rows(plan: MaskPlan) -> tuple[int, int] | None:
    """Vertical extent of the plan's top band, ``None`` when it has none.

    Only rectangles that start at the first row are considered the header band;
    a bottom or side band is verified separately by its own geometry.
    """
    tops = [rect for rect in plan.rects if rect.y0 == 0 and not rect.is_empty]
    if not tops:
        return None
    return (0, max(rect.y1 for rect in tops))


def verify_masked_frame(
    original: np.ndarray,
    masked: np.ndarray,
    plan: MaskPlan,
    *,
    margin_ratio: float = DEFAULT_MARGIN_RATIO,
) -> MaskVerification:
    """Compare a masked frame with what the plan promised (layer 2).

    Three detector runs, all on the same analysed region — the band plus a
    margin below it: the original (what was there), the masked band (did the
    fill erase it) and the margin (does text continue below the band, which is
    what a too-small profile looks like).
    """
    frames = (np.asarray(original), np.asarray(masked))
    if frames[0].ndim < 2 or frames[0].size == 0 or frames[1].shape != frames[0].shape:
        return MaskVerification(ok=False, reason="no-frame")

    band = top_band_rows(plan)
    if band is None:
        return MaskVerification(ok=True, reason="no-top-band")

    height = int(frames[0].shape[0])
    margin = min(MAX_MARGIN_ROWS, max(1, int(round((band[1] - band[0]) * margin_ratio))))
    region_end = min(height, band[1] + margin)

    detected = detect_text_rows(frames[0], rows=(band[0], region_end))
    leftover = detect_text_rows(frames[1], rows=band)
    outside = detect_text_rows(frames[1], rows=(band[1], region_end))

    return MaskVerification(
        ok=not leftover.found and not outside.found,
        band=band,
        detected=detected,
        leftover=leftover,
        outside=outside,
        reason=_PIXEL_OK,
    )
