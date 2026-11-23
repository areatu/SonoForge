"""Paediatric and fetal norm tables (plan А.12, issue #650).

The norms live in ``resources/references/pediatric_norms.yaml`` — the same
physician-editable pattern as the adult reference store.  The shipped tables
are **seeds**: approximate mean/SD anchors, every one labelled
``verified: false`` with a source string that says so.  They are starting
points for the physician to correct, not a quote from a primary publication —
reporting a seed as «ASE» would be the exact dishonesty this tool refuses.

Public API:

* :func:`load_norms` — parse the YAML into :class:`BsaBandModel` /
  :class:`GaBandModel` (cached by path);
* :func:`zscore_for` — one Z-score for a measurement id, routed by profile:
  paediatric models take BSA, fetal models take gestational weeks;
* :func:`model_for`, :func:`norm_measurement_ids` — table introspection for
  the growth charts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from echo_personal_tool.domain.services.zscore import BsaBand, BsaBandModel, GaBand, GaBandModel, ZScoreResult

log = logging.getLogger(__name__)

#: Default table shipped with the application.
DEFAULT_NORMS_PATH = Path(__file__).resolve().parents[2] / "resources" / "references" / "pediatric_norms.yaml"


class PediatricNormsError(ValueError):
    """A malformed norms table — the physician must see what is wrong."""


def _parse_bands(raw: list[dict[str, Any]]) -> tuple[BsaBand, ...]:
    bands = []
    for entry in raw:
        bands.append(BsaBand(bsa_m2=float(entry["bsa"]), mean=float(entry["mean"]), sd=float(entry["sd"])))
    return tuple(bands)


def _parse_ga_bands(raw: list[dict[str, Any]]) -> tuple[GaBand, ...]:
    bands = []
    for entry in raw:
        bands.append(GaBand(weeks=float(entry["weeks"]), mean=float(entry["mean"]), sd=float(entry["sd"])))
    return tuple(bands)


class PediatricNorms:
    """The parsed norms table: models by measurement id."""

    def __init__(self, models: dict[str, BsaBandModel | GaBandModel]) -> None:
        self._models = dict(models)

    def model_for(self, measurement_id: str) -> BsaBandModel | GaBandModel | None:
        return self._models.get(measurement_id)

    def measurement_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._models))

    def zscore_for(
        self,
        measurement_id: str,
        value: float,
        *,
        bsa_m2: float | None = None,
        gestational_weeks: float | None = None,
    ) -> ZScoreResult | None:
        """Z of *value* against the model of *measurement_id*.

        A BSA model needs ``bsa_m2``, a GA model needs ``gestational_weeks``;
        the other input being absent (or the value outside the anchored
        range) returns ``None`` — no invented references.
        """
        model = self._models.get(measurement_id)
        if model is None:
            return None
        if isinstance(model, BsaBandModel):
            if bsa_m2 is None:
                return None
            return model.zscore(value, bsa_m2)
        if gestational_weeks is None:
            return None
        return model.zscore(value, gestational_weeks)


def parse_norms(data: dict[str, Any]) -> PediatricNorms:
    """Parse the YAML mapping into a :class:`PediatricNorms` table."""
    version = data.get("schema_version")
    if version != 1:
        raise PediatricNormsError(f"unsupported pediatric_norms schema_version: {version!r}")
    models: dict[str, BsaBandModel | GaBandModel] = {}
    raw_models = data.get("models")
    if not isinstance(raw_models, dict):
        raise PediatricNormsError("pediatric_norms.yaml: «models» mapping is missing")
    for measurement_id, raw in raw_models.items():
        source = str(raw.get("source") or "").strip()
        if not source:
            raise PediatricNormsError(f"{measurement_id}: a norm model must name its source")
        kind = str(raw.get("kind") or "").strip()
        if kind == "bsa_bands":
            models[str(measurement_id)] = BsaBandModel(bands=_parse_bands(raw.get("bands") or []), source=source)
        elif kind == "ga_bands":
            models[str(measurement_id)] = GaBandModel(bands=_parse_ga_bands(raw.get("bands") or []), source=source)
        else:
            raise PediatricNormsError(f"{measurement_id}: unknown model kind {kind!r}")
    return PediatricNorms(models)


def load_norms(path: Path | None = None) -> PediatricNorms:
    """Load and parse the norms table (``DEFAULT_NORMS_PATH`` by default)."""
    chosen = path or DEFAULT_NORMS_PATH
    with open(chosen, encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise PediatricNormsError(f"{chosen}: the norms table must be a YAML mapping")
    return parse_norms(data)


_CACHE: dict[str, PediatricNorms] = {}


def cached_norms(path: Path | None = None) -> PediatricNorms:
    """The parsed table, cached by resolved path (the report calls it often)."""
    resolved = str((path or DEFAULT_NORMS_PATH).resolve())
    table = _CACHE.get(resolved)
    if table is None:
        table = load_norms(path or DEFAULT_NORMS_PATH)
        _CACHE[resolved] = table
    return table
