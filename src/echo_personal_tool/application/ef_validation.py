"""External EF validation harness for the research status of auto-EF (#418).

What this module makes possible: run the *manual* step of the #418 protocol
locally — match SonoForge's auto-EF outputs against the published reference
EF values of EchoNet-Dynamic, compute agreement metrics, and persist them as
a versioned manifest that the auto-EF result card then shows next to every
automatic estimate («sens/spec in the UI»).

Scope honesty (#418 stays research-only): the harness computes metrics from
data the operator supplies and matches.  It does **not** download the
EchoNet-Dynamic dataset (its license requires registration with Stanford
AIMI and forbids redistribution), it does not claim clinical validation, and
every report is stamped ``research_only: true``.  The external conditions of
#418 — a legally usable dataset, the reference protocol and independent
raters — remain outside the application.

Inputs (all supplied by the operator):

* **Reference** — the EchoNet-Dynamic ``FileList.csv`` (``File,EF,ESVID``);
  any CSV with ``File``/``EF`` columns works.
* **Measured** — a JSON object ``{"<local key>": <EF>}`` of the auto-EF
  values to validate, produced outside the app (script, export reader).
* **Mapping** — a JSON object ``{"<local key>": "<FileList File value>"}``
  linking each measured value to its reference record.

Output: a versioned JSON manifest (default
``<app-data>/validation/auto_ef_manifest.json``) with MAE, bias, Bland–Altman
limits of agreement, Pearson r and reduced-EF sensitivity/specificity at a
configurable threshold.  Aggregates only — no patient data enters the
manifest.  CLI: ``python -m echo_personal_tool.application.ef_validation …``.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.domain.validation import metrics

logger = logging.getLogger(__name__)

MANIFEST_FORMAT = "sonoforge-ef-validation"
MANIFEST_VERSION = 1
#: Reduced-EF threshold of the default report (ASE: EF < 40 % is reduced).
DEFAULT_THRESHOLD_EF = 40.0
#: Minimum paired samples for a report; below this the metrics are noise.
MIN_PAIRS = 3
MANIFEST_FILENAME = "auto_ef_manifest.json"
RESEARCH_ONLY_LABEL = "EchoNet-Dynamic (FileList.csv)"


class EFValidationError(ValueError):
    """Stable-code failure of a validation computation or manifest check."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def load_ef_reference_csv(path: Path, *, ef_column: str = "EF", file_column: str = "File") -> dict[str, float]:
    """Parse an EchoNet-Dynamic ``FileList.csv`` into ``{file: EF}``.

    Header matching is case-insensitive; rows without a numeric EF or an
    empty file name are counted and skipped (reported via the returned
    counts in :func:`build_validation_report`?  No — kept simple: malformed
    rows are skipped; an empty result raises ``EFValidationError``).
    """
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            headers = {name.strip().lower(): name for name in (reader.fieldnames or [])}
            file_key = headers.get(file_column.lower())
            ef_key = headers.get(ef_column.lower())
            if file_key is None or ef_key is None:
                raise EFValidationError("reference_columns_missing")
            reference: dict[str, float] = {}
            for row in reader:
                raw_file = (row.get(file_key) or "").strip()
                raw_ef = (row.get(ef_key) or "").strip()
                if not raw_file:
                    continue
                try:
                    ef = float(raw_ef)
                except ValueError:
                    continue
                if not _is_valid_ef(ef):
                    continue
                reference[raw_file] = ef
    except OSError as exc:
        raise EFValidationError("reference_unreadable") from exc
    if not reference:
        raise EFValidationError("reference_empty")
    return reference


def _is_valid_ef(ef: float) -> bool:
    """EchoNet EF values live on 0–100 %; anything else is a parse artifact."""
    return 0.0 <= ef <= 100.0


def _normalize_reference_key(name: str) -> str:
    """Extension- and case-insensitive key so mappings survive ``.avi``/``.mp4``."""
    return name.strip().lower().rsplit(".", 1)[0] if "." in name.strip().lower() else name.strip().lower()


def _match_reference(reference: dict[str, float], target: str) -> float:
    if target in reference:
        return reference[target]
    normalized = _normalize_reference_key(target)
    for key, value in reference.items():
        if _normalize_reference_key(key) == normalized:
            return value
    raise EFValidationError("reference_missing")


def build_validation_report(
    reference: dict[str, float],
    measured: dict[str, float],
    mapping: dict[str, str],
    *,
    source_label: str = RESEARCH_ONLY_LABEL,
    threshold: float = DEFAULT_THRESHOLD_EF,
) -> dict[str, Any]:
    """Compute the versioned validation report from paired EF values.

    ``mapping`` links each *measured* key to its *reference* record.  A
    measured key without a mapping entry or a mapped reference record that
    does not exist raises ``EFValidationError`` — silently dropping pairs
    would bias the metrics.
    """
    ref_series: list[float] = []
    pred_series: list[float] = []
    for local_key, ef in measured.items():
        target = mapping.get(local_key)
        if target is None:
            raise EFValidationError("mapping_missing")
        try:
            ef_f = float(ef)
        except (TypeError, ValueError) as exc:
            raise EFValidationError("non_numeric_input") from exc
        if not _is_valid_ef(ef_f):
            raise EFValidationError("non_numeric_input")
        ref_series.append(_match_reference(reference, target))
        pred_series.append(ef_f)
    if len(ref_series) < MIN_PAIRS:
        raise EFValidationError("insufficient_pairs")
    try:
        mae = metrics.mean_absolute_error(ref_series, pred_series)
        bias_value = metrics.bias(ref_series, pred_series)
        loa_low, loa_high = metrics.bland_altman_limits(ref_series, pred_series)[1:]
        pearson = metrics.pearson_r(ref_series, pred_series)
        sensitivity, specificity = metrics.sensitivity_specificity(ref_series, pred_series, threshold=threshold)
        tp, fp, fn, tn = metrics.confusion_counts(ref_series, pred_series, threshold=threshold)
    except ValueError as exc:
        raise EFValidationError(str(exc)) from exc
    return {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - datetime.UTC migration deferred (ruff target py310)
        "tool": "auto-ef",
        "source": source_label,
        "n": len(ref_series),
        "threshold_ef": threshold,
        "units": "EF %",
        "research_only": metrics.RESEARCH_ONLY,
        "metrics": {
            "mae": mae,
            "bias": bias_value,
            "loa_low": loa_low,
            "loa_high": loa_high,
            "pearson_r": pearson,
            "sensitivity": sensitivity,
            "specificity": specificity,
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        },
    }


def manifest_path(path: Path | None = None) -> Path:
    """Default manifest location: ``<app-data>/validation/auto_ef_manifest.json``."""
    if path is not None:
        return Path(path)
    from echo_personal_tool.infrastructure.paths import validation_dir

    return validation_dir() / MANIFEST_FILENAME


def save_validation_manifest(report: dict[str, Any], *, path: Path | None = None) -> Path:
    """Persist a report atomically (0600); aggregates only, no PHI by design."""
    validate_validation_report(report)
    destination = manifest_path(path)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True).encode("ascii")
    from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

    MeasurementRepository.atomic_write(destination, payload)
    return destination


def validate_validation_report(report: dict[str, Any]) -> None:
    """Fail closed on a manifest that is not the exact shape we produced."""
    if report.get("format") != MANIFEST_FORMAT or report.get("version") != MANIFEST_VERSION:
        raise EFValidationError("manifest_format")
    for key in ("n", "threshold_ef", "source", "metrics"):
        if key not in report:
            raise EFValidationError("manifest_format")
    if not isinstance(report["metrics"], dict):
        raise EFValidationError("manifest_format")
    for key in ("mae", "bias", "loa_low", "loa_high", "pearson_r"):
        if not isinstance(report["metrics"].get(key), (int, float)):
            raise EFValidationError("manifest_format")


def load_validation_summary(*, path: Path | None = None) -> dict[str, Any] | None:
    """Load the persisted manifest for UI display; ``None`` when absent.

    A corrupt or foreign manifest raises ``EFValidationError`` — the caller
    decides whether to hide the line or surface the failure.
    """
    destination = manifest_path(path)
    try:
        payload = destination.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise EFValidationError("manifest_unreadable") from exc
    try:
        report = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise EFValidationError("manifest_format") from exc
    if not isinstance(report, dict):
        raise EFValidationError("manifest_format")
    validate_validation_report(report)
    return report


def load_auto_ef_validation_summary() -> dict[str, Any] | None:
    """Facade for the auto-EF result card: the manifest, or ``None``.

    presentation imports this — and only this — symbol; the storage paths and
    the repository helpers stay behind the application boundary.
    """
    return load_validation_summary()


def _format_percent(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{float(value) * 100:.1f}%"


def _format_ef(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.1f}"


def _main(argv: list[str] | None = None) -> int:
    """CLI: build and persist the manifest from operator-supplied files."""
    parser = argparse.ArgumentParser(
        prog="python -m echo_personal_tool.application.ef_validation",
        description="Compute the auto-EF external validation report (research only, #418).",
    )
    parser.add_argument("--reference", required=True, help="EchoNet-Dynamic FileList.csv (File,EF,ESVID)")
    parser.add_argument("--measured", required=True, help="JSON: {local_key: EF}")
    parser.add_argument("--mapping", required=True, help="JSON: {local_key: FileList File value}")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_EF, help="reduced-EF threshold")
    parser.add_argument("--output", help="manifest path (default: <app-data>/validation/auto_ef_manifest.json)")
    args = parser.parse_args(argv)

    try:
        reference = load_ef_reference_csv(Path(args.reference))
        measured = json.loads(Path(args.measured).read_text(encoding="utf-8"))
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
        if not isinstance(measured, dict) or not isinstance(mapping, dict):
            raise EFValidationError("input_shape")
        report = build_validation_report(
            reference,
            {str(k): v for k, v in measured.items()},
            {str(k): str(v) for k, v in mapping.items()},
            threshold=float(args.threshold),
        )
        destination = save_validation_manifest(report, path=Path(args.output) if args.output else None)
    except (EFValidationError, OSError, ValueError) as exc:
        log_boundary_failure(logger, "ef_validation.cli", exc, code="invalid_input", level=logging.ERROR)
        print(f"validation failed: {type(exc).__name__}", file=sys.stderr)  # noqa: T201 - CLI path
        return 2
    print(f"manifest written: {destination}")  # noqa: T201 - CLI path
    print(  # noqa: T201 - CLI path
        f"n={report['n']} mae={_format_ef(report['metrics']['mae'])} EF% "
        f"bias={_format_ef(report['metrics']['bias'])} "
        f"sens/spec(EF<{report['threshold_ef']:.0f}%): "
        f"{_format_percent(report['metrics']['sensitivity'])}/{_format_percent(report['metrics']['specificity'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
