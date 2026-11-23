"""Z-score machinery for paediatric and fetal echo (plan А.12, issue #650).

A Z-score answers «how far is this child's measurement from the expected one
for their body size (or gestational age)» — it is the *only* honest way to
quote a paediatric reference: an adult millimetre range misreads a toddler.

Two model shapes cover the norm database:

* :class:`BsaBandModel` — mean and SD per BSA anchor (piecewise-linear
  interpolation between anchors; classic growth-table form);
* :class:`GaBandModel` — the same keyed by gestational weeks (fetal).

Both return a :class:`ZScoreResult` with the Z value and its percentile.
The percentile uses the standard normal curve (:class:`statistics.NormalDist`).
Outside the anchored range the models answer ``None`` — extrapolating a
growth reference is exactly the kind of invented number this tool refuses.

The shipped tables are *seeds*: approximate, clearly labelled, editable in
``resources/references/pediatric_norms.yaml`` (see :mod:`pediatric_norms`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

__all__ = [
    "BsaBandModel",
    "BsaBand",
    "GaBandModel",
    "GaBand",
    "ZScoreResult",
    "format_z",
    "percentile_label",
    "z_to_percentile",
]

_NORMAL = NormalDist()


def z_to_percentile(z: float) -> float:
    """Percentile (0–100) of a standard-normal Z value."""
    return _NORMAL.cdf(z) * 100.0


def percentile_to_z(percentile: float) -> float:
    """Inverse of :func:`z_to_percentile` (growth-chart curves)."""
    return _NORMAL.inv_cdf(min(max(percentile, 0.01), 99.99) / 100.0)


def format_z(z: float) -> str:
    """«+1.2 / −0.8» — the report prints the sign, it is clinically meaningful."""
    return f"{z:+.2f}".replace("-0.00", "+0.00")


def percentile_label(percentile: float) -> str:
    """«P11» — the compact percentile tag next to a Z value."""
    rounded = int(round(percentile))
    return f"P{max(1, min(99, rounded))}"


@dataclass(frozen=True)
class ZScoreResult:
    """One computed Z-score plus what it was computed against."""

    z: float
    #: Standard-normal percentile (0–100).
    percentile: float
    #: The norm table that produced it (shown in the report and the chart so
    #: a seed table can never pass for a verified source).
    source: str
    #: ``True`` when the value sat on the first/last anchor — the table has no
    #: band coverage there and both neighbours are outside.  The report marks
    #: such a row, the physician decides.
    on_edge: bool = False

    @property
    def percentile_text(self) -> str:
        return percentile_label(self.percentile)

    def display(self) -> str:
        """«+1.2 (P11)» — the compact report form."""
        return f"{format_z(self.z)} ({self.percentile_text})"


@dataclass(frozen=True)
class BsaBand:
    """One anchor of a BSA-indexed table: expected mean and SD at that BSA."""

    bsa_m2: float
    mean: float
    sd: float


@dataclass(frozen=True)
class BsaBandModel:
    """Paediatric norms as mean/SD anchors over BSA, interpolated linearly."""

    bands: tuple[BsaBand, ...]
    source: str

    def __post_init__(self) -> None:
        if len(self.bands) < 2:
            raise ValueError("a BSA model needs at least two anchors")
        if any(band.sd <= 0 for band in self.bands):
            raise ValueError("an SD must be positive")
        if any(band.bsa_m2 <= 0 for band in self.bands):
            raise ValueError("a BSA anchor must be positive")

    @property
    def bsa_range(self) -> tuple[float, float]:
        return (self.bands[0].bsa_m2, self.bands[-1].bsa_m2)

    def stats_at(self, bsa_m2: float) -> tuple[float, float, bool] | None:
        """(mean, sd, on_edge) interpolated at *bsa_m2*; ``None`` outside."""
        if bsa_m2 < self.bands[0].bsa_m2 or bsa_m2 > self.bands[-1].bsa_m2:
            return None
        lower = self.bands[0]
        for band in self.bands[1:]:
            if bsa_m2 <= band.bsa_m2:
                if bsa_m2 == band.bsa_m2 or bsa_m2 == lower.bsa_m2:
                    mean, sd = self._anchor_stats(bsa_m2)
                    return (mean, sd, False)
                span = band.bsa_m2 - lower.bsa_m2
                weight = (bsa_m2 - lower.bsa_m2) / span
                mean = lower.mean + (band.mean - lower.mean) * weight
                sd = lower.sd + (band.sd - lower.sd) * weight
                return (mean, sd, False)
            lower = band
        return None  # pragma: no cover — the range guard above makes it unreachable

    def _anchor_stats(self, bsa_m2: float) -> tuple[float, float]:
        for band in self.bands:
            if band.bsa_m2 == bsa_m2:
                return (band.mean, band.sd)
        raise ValueError(f"no anchor at BSA {bsa_m2}")

    def zscore(self, value: float, bsa_m2: float) -> ZScoreResult | None:
        """Z of *value* at the given BSA; ``None`` outside the anchored range."""
        if not math.isfinite(value) or not math.isfinite(bsa_m2) or bsa_m2 <= 0:
            return None
        stats = self.stats_at(bsa_m2)
        if stats is None:
            return None
        mean, sd, on_edge = stats
        return ZScoreResult(
            z=(value - mean) / sd,
            percentile=z_to_percentile((value - mean) / sd),
            source=self.source,
            on_edge=on_edge,
        )

    def value_at_z(self, z: float, bsa_m2: float) -> float | None:
        """The raw value *z* corresponds to at *bsa_m2* (growth-chart curves)."""
        stats = self.stats_at(bsa_m2)
        if stats is None:
            return None
        mean, sd, _ = stats
        return mean + z * sd


@dataclass(frozen=True)
class GaBand:
    """One anchor of a fetal table: expected mean and SD at that GA week."""

    weeks: float
    mean: float
    sd: float


@dataclass(frozen=True)
class GaBandModel:
    """Fetal norms as mean/SD anchors over gestational age in weeks."""

    bands: tuple[GaBand, ...]
    source: str

    def __post_init__(self) -> None:
        if len(self.bands) < 2:
            raise ValueError("a GA model needs at least two anchors")
        if any(band.sd <= 0 for band in self.bands):
            raise ValueError("an SD must be positive")
        weeks = [band.weeks for band in self.bands]
        if any(weeks[i] >= weeks[i + 1] for i in range(len(weeks) - 1)):
            raise ValueError("GA anchors must grow")

    @property
    def weeks_range(self) -> tuple[float, float]:
        return (self.bands[0].weeks, self.bands[-1].weeks)

    def stats_at(self, weeks: float) -> tuple[float, float, bool] | None:
        if weeks < self.bands[0].weeks or weeks > self.bands[-1].weeks:
            return None
        lower = self.bands[0]
        for band in self.bands[1:]:
            if weeks <= band.weeks:
                if weeks == band.weeks or weeks == lower.weeks:
                    mean, sd = self._anchor_stats(weeks)
                    return (mean, sd, False)
                span = band.weeks - lower.weeks
                weight = (weeks - lower.weeks) / span
                mean = lower.mean + (band.mean - lower.mean) * weight
                sd = lower.sd + (band.sd - lower.sd) * weight
                return (mean, sd, False)
            lower = band
        return None  # pragma: no cover — the range guard above makes it unreachable

    def _anchor_stats(self, weeks: float) -> tuple[float, float]:
        for band in self.bands:
            if band.weeks == weeks:
                return (band.mean, band.sd)
        raise ValueError(f"no anchor at GA {weeks}")

    def zscore(self, value: float, weeks: float) -> ZScoreResult | None:
        if not math.isfinite(value) or not math.isfinite(weeks) or weeks <= 0:
            return None
        stats = self.stats_at(weeks)
        if stats is None:
            return None
        mean, sd, on_edge = stats
        return ZScoreResult(
            z=(value - mean) / sd,
            percentile=z_to_percentile((value - mean) / sd),
            source=self.source,
            on_edge=on_edge,
        )

    def value_at_z(self, z: float, weeks: float) -> float | None:
        stats = self.stats_at(weeks)
        if stats is None:
            return None
        mean, sd, _ = stats
        return mean + z * sd


def percentile_curve(model: BsaBandModel | GaBandModel, z: float) -> list[tuple[float, float]]:
    """(x, value) points of one percentile curve across the model's range.

    x is BSA (``BsaBandModel``) or GA weeks (``GaBandModel``); the curve stops
    at the anchored range — the chart shows what the table actually covers.
    """
    points: list[tuple[float, float]] = []
    start, end = model.bsa_range if isinstance(model, BsaBandModel) else model.weeks_range
    steps = 24
    for index in range(steps + 1):
        x = start + (end - start) * index / steps
        value = model.value_at_z(z, x)
        if value is not None:
            points.append((x, value))
    return points
