"""Persistent store for imported external reports (HL7 ORU / FHIR DiagnosticReport).

A single JSON document with atomic replace + symlink refusal, mirroring the
local user store.  Reports are capped (oldest evicted first) so a busy inbound
feed cannot grow the file without bound.  The PDF payload travels as Base64
inside the document — it is external report content, not a credential.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from echo_personal_tool.domain.models.imported_report import ImportedReport

_STORE_VERSION = 1
#: Upper bound on stored reports; the inbound feed evicts the oldest beyond it.
MAX_REPORTS = 500


def _is_unsafe_link(path: Path) -> bool:
    try:
        return path.is_symlink() or (path.exists() and not path.is_file())
    except OSError:
        return True


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class ImportedReportStore:
    """JSON-file-backed store of :class:`ImportedReport` entries."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> list[ImportedReport]:
        if _is_unsafe_link(self._path):
            return []
        try:
            raw = self._path.read_bytes()
        except OSError:
            return []
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return []
        if not isinstance(document, dict) or document.get("version") != _STORE_VERSION:
            return []
        entries = document.get("reports")
        if not isinstance(entries, list):
            return []
        reports: list[ImportedReport] = []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("report_id"):
                reports.append(ImportedReport.from_dict(entry))
        return reports

    def _save(self, reports: list[ImportedReport]) -> None:
        if _is_unsafe_link(self._path):
            raise RuntimeError("unsafe_store_path")
        document: dict[str, Any] = {
            "version": _STORE_VERSION,
            "reports": [r.to_dict() for r in reports],
        }
        _atomic_write(self._path, json.dumps(document, ensure_ascii=False).encode("utf-8"))

    def save(self, report: ImportedReport) -> None:
        """Insert or replace a report (keyed by report_id + source), evicting oldest."""
        reports = self._load()
        reports = [r for r in reports if not (r.report_id == report.report_id and r.source == report.source)]
        reports.append(report)
        if len(reports) > MAX_REPORTS:
            reports = reports[-MAX_REPORTS:]
        self._save(reports)

    def get(self, report_id: str, *, source: str = "") -> ImportedReport | None:
        for report in self._load():
            if report.report_id == report_id and (not source or report.source == source):
                return report
        return None

    def list_for_patient(self, patient_id: str) -> list[ImportedReport]:
        return [r for r in self._load() if r.patient_id == patient_id]

    def list_all(self) -> list[ImportedReport]:
        return self._load()

    def delete(self, report_id: str, *, source: str = "") -> bool:
        reports = self._load()
        kept = [r for r in reports if not (r.report_id == report_id and (not source or r.source == source))]
        if len(kept) == len(reports):
            return False
        self._save(kept)
        return True
