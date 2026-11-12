"""Per-tab clinical memory: the values a clinician typed, kept in RAM only.

The measurement session store and the calculator-input store are application
wide.  Every source change clears them, so a tab switch used to drop manual
pixel spacing, manual BSA, calculator overrides and contours whenever local
measurement storage was disabled.  The tab is the missing owner: it is exactly
the lifetime the user sees, and two tabs may even hold the same study without
sharing values.

``TabClinicalMemory`` is that owner.  The coordinator parks it in
``TabSession`` before the view leaves the tab and hands it back to the
controller when the tab returns.  The snapshot is a deep copy of plain DTOs:
no widgets, no Qt and no I/O, so the contract is testable at controller level.

When measurement persistence is enabled the disk record remains the authority
and the controller does not park a RAM copy — two sources that can diverge are
worse than the reload.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from echo_personal_tool.application.calculator_inputs import CalculatorInputStore, HeartRateCandidate
from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementData,
    StudyMeasurementSessionStore,
)
from echo_personal_tool.domain.calculators.models import SOURCE_ESTIMATE

logger = logging.getLogger(__name__)


@dataclass
class TabClinicalMemory:
    """The typed values of one tab, held in memory for the tab's lifetime."""

    studies: dict[str, StudyMeasurementData] = field(default_factory=dict)
    manual_inputs: dict[str, dict[str, float]] = field(default_factory=dict)
    #: Cine heart-rate estimates are session-only (not part of the persisted
    #: record), so losing them on a switch silently changed cardiac output.
    heart_rates: dict[str, HeartRateCandidate] = field(default_factory=dict)

    @classmethod
    def capture(
        cls,
        session: StudyMeasurementSessionStore,
        calculator_inputs: CalculatorInputStore,
        study_uids: Iterable[str],
    ) -> TabClinicalMemory:
        """Snapshot the stores for *study_uids*; unknown studies stay absent."""
        uids = tuple(dict.fromkeys(study_uids))
        heart_rates: dict[str, HeartRateCandidate] = {}
        for uid in uids:
            candidate = calculator_inputs.hr_estimate(uid)
            if candidate is not None and candidate.source == SOURCE_ESTIMATE:
                heart_rates[uid] = candidate
        manual_inputs = {uid: values for uid in uids if (values := calculator_inputs.manual(uid))}
        return cls(
            studies={uid: session.snapshot(uid) for uid in uids if uid in session},
            manual_inputs=manual_inputs,
            heart_rates=heart_rates,
        )

    def restore_into(
        self,
        session: StudyMeasurementSessionStore,
        calculator_inputs: CalculatorInputStore,
    ) -> tuple[str, ...]:
        """Make this tab's values live again; returns the restored study UIDs."""
        values_by_study = {study_uid: dict(values) for study_uid, values in self.manual_inputs.items()}
        for study_uid, data in self.studies.items():
            session.restore(study_uid, data)
            if data.manual_bsa_m2 is not None:
                # The DTO is the persisted authority; the calculator store is a
                # mirror, so a snapshot without the mirror still keeps the BSA.
                values_by_study.setdefault(study_uid, {}).setdefault("bsa", data.manual_bsa_m2)
        for study_uid, values in values_by_study.items():
            calculator_inputs.restore_manual(study_uid, values)
        for study_uid, candidate in self.heart_rates.items():
            calculator_inputs.set_hr_estimate(study_uid, candidate.bpm, candidate.detail)
        return tuple(self.studies)

    def has_measurements(self) -> bool:
        """Whether the tab holds user measurements, not only calibration or BSA."""
        return any(data.has_measurements for data in self.studies.values())

    def __bool__(self) -> bool:
        return bool(self.studies or self.manual_inputs or self.heart_rates)


def adopt_loaded_bsa(
    loaded: Iterable[str],
    session: StudyMeasurementSessionStore,
    calculator_inputs: CalculatorInputStore,
) -> None:
    """Seed the calculators' manual BSA from records that were loaded from disk.

    The manual value is persisted with the study, so an opened record keeps the
    body surface area the clinician typed instead of silently falling back to
    the Du Bois estimate.  The value already passed the document validator; a
    range failure is logged, never fatal.
    """
    for study_uid in tuple(loaded):
        data = session.get(study_uid)
        if data.manual_bsa_m2 is None:
            continue
        try:
            calculator_inputs.set_manual(study_uid, "bsa", data.manual_bsa_m2)
        except (KeyError, ValueError) as exc:
            log_boundary_failure(logger, "measurement.load", exc, code="invalid", level=logging.WARNING)


__all__ = ["TabClinicalMemory", "adopt_loaded_bsa"]
