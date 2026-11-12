"""TabClinicalMemory: park/restore the values a clinician typed in a tab.

The module is deliberately Qt-free, so these tests run in the logic job: the
snapshot is a deep copy of the session DTO, and restoring it is the same
operation the controller performs on a tab switch.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.calculator_inputs import CalculatorInputStore
from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
from echo_personal_tool.application.tab_clinical_memory import TabClinicalMemory, adopt_loaded_bsa
from echo_personal_tool.domain.models.contour import Contour


def _contour() -> Contour:
    return Contour(phase="ED", view="A4C", chamber="LV", points=[(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)])


def _stores() -> tuple[StudyMeasurementSessionStore, CalculatorInputStore]:
    session = StudyMeasurementSessionStore()
    calculator = CalculatorInputStore()
    session.merge_contours("a.study", (_contour(),))
    calculator.set_manual("a.study", "bsa", 1.9)
    calculator.set_hr_estimate("a.study", 72, "cine")
    return session, calculator


def test_capture_keeps_only_open_studies_and_survives_the_live_store() -> None:
    session, calculator = _stores()

    memory = TabClinicalMemory.capture(session, calculator, ["a.study", "not-open.study"])

    assert set(memory.studies) == {"a.study"}
    assert memory.manual_inputs["a.study"]["bsa"] == 1.9
    assert memory.heart_rates["a.study"].bpm == 72

    session.clear()
    calculator.clear()
    assert memory.studies["a.study"].contours, "the snapshot is a deep copy, not a live view"


def test_restore_makes_the_parked_values_live_again() -> None:
    session, calculator = _stores()
    memory = TabClinicalMemory.capture(session, calculator, ["a.study"])
    fresh_session = StudyMeasurementSessionStore()
    fresh_calculator = CalculatorInputStore()

    restored = memory.restore_into(fresh_session, fresh_calculator)

    assert restored == ("a.study",)
    assert fresh_session.get("a.study").contours
    assert fresh_calculator.manual("a.study")["bsa"] == 1.9
    assert fresh_calculator.hr_estimate("a.study") is not None


def test_restore_keeps_a_dto_bsa_even_without_the_calculator_mirror() -> None:
    session = StudyMeasurementSessionStore()
    session.set_manual_bsa("a.study", 1.55)
    memory = TabClinicalMemory.capture(session, CalculatorInputStore(), ["a.study"])
    assert memory.manual_inputs == {}

    fresh_session = StudyMeasurementSessionStore()
    fresh_calculator = CalculatorInputStore()
    memory.restore_into(fresh_session, fresh_calculator)

    assert fresh_calculator.manual("a.study")["bsa"] == pytest.approx(1.55)


def test_calibration_alone_is_not_a_measurement() -> None:
    session = StudyMeasurementSessionStore()
    calculator = CalculatorInputStore()
    session.set_instance_spacing("a.study", "a.0", (0.3, 0.3))
    session.set_manual_bsa("a.study", 1.9)

    calibration_only = TabClinicalMemory.capture(session, calculator, ["a.study"])
    assert calibration_only
    assert calibration_only.has_measurements() is False

    session.merge_contours("a.study", (_contour(),))

    assert TabClinicalMemory.capture(session, calculator, ["a.study"]).has_measurements() is True


def test_an_empty_memory_is_falsey() -> None:
    assert not TabClinicalMemory()
    assert TabClinicalMemory(manual_inputs={"a.study": {"bsa": 1.9}})


def test_adopt_loaded_bsa_only_touches_records_that_were_loaded() -> None:
    session = StudyMeasurementSessionStore()
    calculator = CalculatorInputStore()
    session.set_manual_bsa("loaded.study", 1.55)
    session.set_manual_bsa("not-loaded.study", 2.0)

    adopt_loaded_bsa({"loaded.study"}, session, calculator)

    assert calculator.manual("loaded.study")["bsa"] == pytest.approx(1.55)
    assert calculator.manual("not-loaded.study") == {}
