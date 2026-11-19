"""Worklist / patient-index application service (#626).

Consumes normalized inbound events (HL7 ORM/ADT, FHIR) and MPPS updates,
persists them through the :class:`WorklistStorePort`, and writes PHI-free
audit events. Pure application logic — no Qt, no sockets, no SQL here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from echo_personal_tool.domain.models.audit import AuditAction
from echo_personal_tool.domain.models.worklist import (
    DemographicsEvent,
    MppsUpdate,
    OrderControl,
    OrderEvent,
    WorklistItem,
    WorklistStatus,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorklistService:
    """Apply inbound orders/demographics and serve MWL/MPPS queries."""

    def __init__(self, *, store: Any, session: Any = None, now: Any = None) -> None:
        self._store = store
        self._session = session
        self._now = now or _now_iso

    def _audit(self, action: AuditAction, *, study_key: str = "", details: dict[str, str] | None = None) -> None:
        if self._session is None:
            return
        self._session.record_study_audit(action, study_key=study_key, details=details or {})

    # ── inbound HL7 / FHIR ───────────────────────────────────────────

    def apply_order(self, event: OrderEvent) -> WorklistItem | None:
        """Apply an ORM/OMG order or FHIR ServiceRequest to the worklist."""
        control = event.control
        if control is None:
            return None
        now = self._now()
        if event.patient is not None:
            self._store.upsert_patient(event.patient)
        if control is OrderControl.CANCEL:
            ok = bool(
                self._store.set_worklist_status(event.accession_number, WorklistStatus.CANCELLED.value, updated_at=now)
            )
            self._audit(
                AuditAction.INTEROP_RECEIVED,
                details={
                    "protocol": event.source,
                    "event": "order.cancel",
                    "accession": event.accession_number[:64],
                    "applied": str(ok),
                },
            )
            return self._store.get_worklist_item(event.accession_number) if ok else None
        item = WorklistItem(
            accession_number=event.accession_number,
            patient_id=event.patient.patient_id if event.patient else "",
            patient_name=event.patient.name if event.patient else "",
            birth_date=event.patient.birth_date if event.patient else "",
            sex=event.patient.sex if event.patient else "",
            procedure_code=event.procedure_code,
            procedure_description=event.procedure_description,
            scheduled_datetime=event.scheduled_datetime,
            scheduled_station_ae=event.scheduled_station_ae,
            referring_physician=event.referring_physician,
            indications=event.indications,
            study_instance_uid=event.study_instance_uid,
            status=WorklistStatus.SCHEDULED,
            source=event.source,
            updated_at=now,
        )
        self._store.upsert_worklist_item(item)
        self._audit(
            AuditAction.INTEROP_RECEIVED,
            details={
                "protocol": event.source,
                "event": "order.new" if control is OrderControl.NEW else "order.replace",
                "accession": event.accession_number[:64],
            },
        )
        return item

    def apply_demographics(self, event: DemographicsEvent) -> None:
        """Apply an ADT event: update the patient index, honour MRG merges."""
        if event.merge is not None:
            self._store.apply_merge(event.merge.source_id, event.merge.target_id, merged_at=self._now())
            if event.patient is not None:
                self._store.upsert_patient(event.patient)
            self._audit(
                AuditAction.INTEROP_RECEIVED,
                details={"protocol": event.source, "event": "patient.merge"},
            )
            return
        if event.patient is not None:
            self._store.upsert_patient(event.patient)
            self._audit(
                AuditAction.INTEROP_RECEIVED,
                details={"protocol": event.source, "event": f"patient.{event.event.lower()}"},
            )

    # ── MWL / MPPS ───────────────────────────────────────────────────

    def find_by_study_uid(self, study_instance_uid: str) -> WorklistItem | None:
        found = self._store.find_by_study_uid(study_instance_uid)
        return found if isinstance(found, WorklistItem) else None

    def query_worklist(self, *, patient_id: str = "", station_ae: str = "") -> list[WorklistItem]:
        """MWL C-FIND backing query; only non-terminal statuses are returned."""
        items = self._store.query_worklist(patient_id=patient_id, station_ae=station_ae)
        return [
            item
            for item in items
            if getattr(item, "status", WorklistStatus.SCHEDULED)
            in (WorklistStatus.SCHEDULED, WorklistStatus.IN_PROGRESS)
        ]

    def apply_mpps(self, update: MppsUpdate) -> bool:
        """MPPS N-CREATE/N-SET backing transition."""
        if update.status not in (WorklistStatus.IN_PROGRESS, WorklistStatus.COMPLETED, WorklistStatus.DISCONTINUED):
            return False
        ok = bool(self._store.set_worklist_status(update.accession_number, update.status.value, updated_at=self._now()))
        self._audit(
            AuditAction.INTEROP_RECEIVED,
            details={
                "protocol": "dicom-mpps",
                "event": f"mpps.{update.status.value.lower()}",
                "accession": update.accession_number[:64],
            },
        )
        return ok
