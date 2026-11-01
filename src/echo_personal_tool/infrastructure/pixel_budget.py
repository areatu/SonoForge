"""Decode budget for DICOM pixel data (S3-04, #313).

A pathological study (huge ``Rows × Columns`` combined with many frames) can make
the decoder allocate gigabytes before anything reaches the screen. The budget is
checked from the header alone, *before* any pixel byte is mapped or read, so an
oversized study is refused while only its metadata is in memory.

The error carries numbers only — never a path or a patient identifier — so the
message is safe to show in the UI and in the status bar.
"""

from __future__ import annotations

from typing import Any

#: 200 megapixels of decoded samples, checked for the *whole* study at open.
#: At 8 bits that caps one decode at ~200 MB, at 16 bits at ~400 MB — the point
#: where one ``decode_all_frames()`` array stops fitting a workstation budget.
#: Real echocardiographic clips sit orders of magnitude below it (a 512×512 cine
#: of 300 frames is 79 Mpx); the threshold exists for pathological headers, not
#: for long legitimate loops.
MAX_DECODED_PIXELS = 200_000_000


class StudyTooLargeError(Exception):
    """Refusal raised before an oversized study allocates pixel memory.

    ``code`` is the stable, UI-safe identifier used by the workers; the message
    names only the measured and allowed budgets.
    """

    code = "study_too_large"

    def __init__(
        self,
        rows: int,
        columns: int,
        frames: int,
        samples: int = 1,
        limit: int = MAX_DECODED_PIXELS,
    ) -> None:
        self.rows = int(rows)
        self.columns = int(columns)
        self.frames = int(frames)
        self.samples = int(samples)
        self.limit = int(limit)
        self.pixels = decoded_pixels(self.rows, self.columns, self.frames, self.samples)
        super().__init__(self._describe())

    @property
    def megapixels(self) -> float:
        return self.pixels / 1_000_000

    @property
    def limit_megapixels(self) -> float:
        return self.limit / 1_000_000

    def _describe(self) -> str:
        return (
            f"Study exceeds the decode budget: {self.megapixels:.1f} Mpx "
            f"(rows={self.rows}, columns={self.columns}, frames={self.frames}, "
            f"samples={self.samples}) > {self.limit_megapixels:.0f} Mpx"
        )

    def __str__(self) -> str:  # pragma: no cover - documented, message never shown raw
        return self._describe()


def decoded_pixels(rows: Any, columns: Any, frames: Any, samples: Any = 1) -> int:
    """Return ``rows × columns × frames × samples`` as an int, tolerant of junk.

    Missing or non-numeric DICOM attributes become ``0`` here: the budget must
    never turn a malformed header into an exception other than its own refusal,
    and the decoders below already report a missing geometry themselves.
    """

    def _as_int(value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return max(number, 0)

    return _as_int(rows) * _as_int(columns) * _as_int(frames) * _as_int(samples)


def check_pixel_budget(
    rows: Any,
    columns: Any,
    frames: Any,
    *,
    samples: Any = 1,
    limit: int = MAX_DECODED_PIXELS,
) -> int:
    """Raise :class:`StudyTooLargeError` when the decoded sample count is over *limit*.

    Returns the decoded sample count so callers can log it without recomputing.
    """
    pixels = decoded_pixels(rows, columns, frames, samples)
    if pixels > limit:
        raise StudyTooLargeError(int(rows or 0), int(columns or 0), int(frames or 0), int(samples or 1), limit)
    return pixels


def check_dataset_budget(dataset: Any, frames: Any, *, limit: int = MAX_DECODED_PIXELS) -> int:
    """Budget check for a parsed pydicom dataset and an explicit frame count.

    ``SamplesPerPixel`` is included because the decoder allocates per sample
    (an RGB frame of the same ``Rows × Columns`` costs three times the memory),
    and ``NumberOfFrames`` is *not* read here — the caller owns the frame count
    and passes what it actually intends to decode.
    """
    return check_pixel_budget(
        getattr(dataset, "Rows", 0),
        getattr(dataset, "Columns", 0),
        frames,
        samples=getattr(dataset, "SamplesPerPixel", 1) or 1,
        limit=limit,
    )


__all__ = [
    "MAX_DECODED_PIXELS",
    "StudyTooLargeError",
    "check_dataset_budget",
    "check_pixel_budget",
    "decoded_pixels",
]
