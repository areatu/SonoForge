"""SQLite WAL store for the worklist queue and patient index (#626).

One database file under the app data dir; WAL mode so the MWL/MPPS server and
the MLLP listener can read while the writer appends. Stores operational
scheduling data only — no measurement payloads, no audit trail (that lives in
the hash-chained audit log).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from echo_personal_tool.domain.models.worklist import PatientDemographics, WorklistItem, WorklistStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS worklist (
    accession_number TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL DEFAULT '',
    patient_name TEXT NOT NULL DEFAULT '',
    birth_date TEXT NOT NULL DEFAULT '',
    sex TEXT NOT NULL DEFAULT '',
    procedure_code TEXT NOT NULL DEFAULT '',
    procedure_description TEXT NOT NULL DEFAULT '',
    scheduled_datetime TEXT NOT NULL DEFAULT '',
    scheduled_station_ae TEXT NOT NULL DEFAULT '',
    referring_physician TEXT NOT NULL DEFAULT '',
    indications TEXT NOT NULL DEFAULT '',
    study_instance_uid TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'SCHEDULED',
    source TEXT NOT NULL DEFAULT 'hl7',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS patients (
    patient_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    birth_date TEXT NOT NULL DEFAULT '',
    sex TEXT NOT NULL DEFAULT '',
    mrn TEXT NOT NULL DEFAULT '',
    merged_into TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_worklist_patient ON worklist(patient_id);
CREATE INDEX IF NOT EXISTS idx_worklist_status ON worklist(status);
"""


class WorklistRepository:
    """SQLite-backed :class:`WorklistStorePort` implementation."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(_SCHEMA)
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(worklist)").fetchall()}
            if "study_instance_uid" not in columns:
                self._db.execute("ALTER TABLE worklist ADD COLUMN study_instance_uid TEXT NOT NULL DEFAULT ''")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ── worklist ─────────────────────────────────────────────────────

    def upsert_worklist_item(self, item: WorklistItem) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO worklist (accession_number, patient_id, patient_name, birth_date, sex,
                   procedure_code, procedure_description, scheduled_datetime, scheduled_station_ae,
                   referring_physician, indications, study_instance_uid, status, source, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(accession_number) DO UPDATE SET
                     patient_id=excluded.patient_id, patient_name=excluded.patient_name,
                     birth_date=excluded.birth_date, sex=excluded.sex,
                     procedure_code=excluded.procedure_code, procedure_description=excluded.procedure_description,
                     scheduled_datetime=excluded.scheduled_datetime, scheduled_station_ae=excluded.scheduled_station_ae,
                     referring_physician=excluded.referring_physician, indications=excluded.indications,
                     study_instance_uid=excluded.study_instance_uid,
                     status=excluded.status, source=excluded.source, updated_at=excluded.updated_at""",
                (
                    item.accession_number,
                    item.patient_id,
                    item.patient_name,
                    item.birth_date,
                    item.sex,
                    item.procedure_code,
                    item.procedure_description,
                    item.scheduled_datetime,
                    item.scheduled_station_ae,
                    item.referring_physician,
                    item.indications,
                    item.study_instance_uid,
                    item.status.value,
                    item.source,
                    item.updated_at,
                ),
            )
            self._db.commit()

    def _row_to_item(self, row: sqlite3.Row) -> WorklistItem:
        return WorklistItem.from_dict({key: row[key] for key in row.keys()})

    def find_by_study_uid(self, study_instance_uid: str) -> WorklistItem | None:
        if not study_instance_uid:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM worklist WHERE study_instance_uid=? ORDER BY updated_at DESC LIMIT 1",
                (study_instance_uid,),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def get_worklist_item(self, accession_number: str) -> WorklistItem | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM worklist WHERE accession_number=?", (accession_number,)).fetchone()
        return self._row_to_item(row) if row else None

    def query_worklist(self, *, patient_id: str = "", status: str = "", station_ae: str = "") -> list[WorklistItem]:
        query = "SELECT * FROM worklist WHERE 1=1"
        params: list[str] = []
        if patient_id:
            query += " AND patient_id=?"
            params.append(patient_id)
        if status:
            query += " AND status=?"
            params.append(status)
        if station_ae:
            query += " AND scheduled_station_ae=?"
            params.append(station_ae)
        query += " ORDER BY scheduled_datetime"
        with self._lock:
            rows = self._db.execute(query, params).fetchall()
        return [self._row_to_item(row) for row in rows]

    def set_worklist_status(self, accession_number: str, status: str, *, updated_at: str = "") -> bool:
        try:
            WorklistStatus(status)
        except ValueError:
            return False
        with self._lock:
            cur = self._db.execute(
                "UPDATE worklist SET status=?, updated_at=? WHERE accession_number=?",
                (status, updated_at, accession_number),
            )
            self._db.commit()
            return cur.rowcount > 0

    # ── patient index ────────────────────────────────────────────────

    def upsert_patient(self, demographics: PatientDemographics) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._db.execute(
                """INSERT INTO patients (patient_id, name, birth_date, sex, mrn, updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(patient_id) DO UPDATE SET
                     name=excluded.name, birth_date=excluded.birth_date, sex=excluded.sex,
                     mrn=excluded.mrn, updated_at=excluded.updated_at""",
                (
                    demographics.patient_id,
                    demographics.name,
                    demographics.birth_date,
                    demographics.sex,
                    demographics.mrn,
                    now,
                ),
            )
            self._db.commit()

    def get_patient(self, patient_id: str) -> PatientDemographics | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM patients WHERE patient_id=?", (patient_id,)).fetchone()
        if not row:
            return None
        return PatientDemographics.from_dict(
            {key: row[key] for key in row.keys() if key not in ("merged_into", "updated_at")}
        )

    def apply_merge(self, source_id: str, target_id: str, *, merged_at: str = "") -> None:
        """ADT^A40 MRG: mark the source patient merged and re-point its worklist rows.

        Source DICOM studies on the PACS are never rewritten here; the merge
        only re-points the local index/worklist so new orders land on the
        surviving identity.
        """
        with self._lock:
            self._db.execute(
                "UPDATE patients SET merged_into=?, updated_at=? WHERE patient_id=?",
                (target_id, merged_at, source_id),
            )
            self._db.execute(
                "UPDATE worklist SET patient_id=?, updated_at=? WHERE patient_id=?",
                (target_id, merged_at, source_id),
            )
            self._db.commit()

    def export_state(self) -> dict[str, object]:
        """Debug/backup helper: full dump as JSON-able dict."""
        with self._lock:
            items = [dict(row) for row in self._db.execute("SELECT * FROM worklist").fetchall()]
            patients = [dict(row) for row in self._db.execute("SELECT * FROM patients").fetchall()]
        return {"worklist": items, "patients": patients, "dump": json.dumps({"worklist": items, "patients": patients})}
