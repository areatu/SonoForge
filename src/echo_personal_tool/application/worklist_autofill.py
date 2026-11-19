"""Worklist → report autofill facade (#626).

Presentation never touches the SQLite store directly; it asks this
application facade for the demographics of the study currently open in the
report window.  Returns ``None`` when no worklist order matches, so the
caller keeps whatever the study itself carried.
"""

from __future__ import annotations

from echo_personal_tool.application.worklist_service import WorklistService
from echo_personal_tool.domain.services.report_document import PatientInfo
from echo_personal_tool.infrastructure.paths import worklist_db_path
from echo_personal_tool.infrastructure.worklist_repository import WorklistRepository


def autofill_patient_for_study(study_instance_uid: str) -> PatientInfo | None:
    """Best-effort worklist demographics for ``study_instance_uid``.

    Empty strings in the result mean "not known to the worklist"; callers
    should only overwrite fields they already have empty.
    """
    if not study_instance_uid or study_instance_uid == "__default__":
        return None
    store = WorklistRepository(worklist_db_path())
    try:
        service = WorklistService(store=store)
        item = service.find_by_study_uid(study_instance_uid)
    finally:
        store.close()
    if item is None:
        return None
    return PatientInfo(
        name=item.patient_name,
        patient_id=item.patient_id,
        birth_date=item.birth_date,
        sex=item.sex,
        study_date=item.scheduled_datetime[:10],
        physician=item.referring_physician,
    )
