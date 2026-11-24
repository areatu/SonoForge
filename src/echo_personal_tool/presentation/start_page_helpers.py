"""Pure helpers for the start page recent-studies block (spec 474 decomposition).

Extracted from ``MainWindow`` so the window class stays under its size
ceiling.  These functions format listing data into ``RecentStudySummary`` rows
and touch no window state.
"""

from __future__ import annotations

from echo_personal_tool.application.localization import tr, tr_plural
from echo_personal_tool.presentation.start_page import RecentStudySummary


def stored_record_summaries(listing: object, seen_keys: set[str]) -> list[RecentStudySummary]:
    """Rows for the stored records, including honest unreadable/failed states.

    The listing comes from the persistence worker (``MeasurementPersistence.
    list_saved_records``).  Unreadable records are aggregated into a single
    row (the manager shows them one by one); failed listings produce an
    honest "unavailable" row instead of pretending nothing was stored.
    """
    if listing is None:
        return []
    rows: list[RecentStudySummary] = []
    for record in getattr(listing, "records", ()):
        if not record.readable:
            continue  # aggregated below; the manager shows them one by one
        if record.key in seen_keys:
            continue
        seen_keys.add(record.key)
        date = record.saved_at[:10] if record.saved_at else ""
        title = " · ".join(part for part in (date, tr("start_page.recent_studies_saved")) if part)
        details = (
            f"{tr_plural('start_page.recent_studies_measurements', record.measurement_count)} · "
            f"{tr('start_page.recent_studies_saved')}"
        )
        rows.append(
            RecentStudySummary(
                key=record.key,
                title=title,
                details=details,
                origin="stored",
                folder="",
                study_uid="",
                available=False,
                study_date=date,
                measurement_count=int(record.measurement_count or 0),
            )
        )
    if getattr(listing, "failed", False):
        rows.append(
            RecentStudySummary(
                key="stored-unavailable",
                title=tr("start_page.recent_studies_failed"),
                details=tr("start_page.recent_studies_failed_tip"),
                origin="stored",
                available=False,
            )
        )
    elif getattr(listing, "unreadable", 0):
        rows.append(
            RecentStudySummary(
                key="stored-unreadable",
                title=tr_plural("start_page.recent_studies_unreadable", getattr(listing, "unreadable", 0)),
                details=tr("start_page.recent_studies_unreadable_tip"),
                origin="stored",
                available=False,
            )
        )
    return rows
