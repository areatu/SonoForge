"""Unit tests for domain/services/patient_display.py (pure formatters)."""

from __future__ import annotations

from datetime import datetime

import pytest

from echo_personal_tool.domain.services.patient_display import (
    format_dicom_date,
    format_dicom_time,
    format_patient_age,
    format_patient_header,
    format_patient_sex,
    format_person_name,
    format_relative_day,
    format_size_mb,
    plural_ru,
)


class TestFormatPersonName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ИВАНОВ^ИВАН^ИВАНОВИЧ", "Иванов Иван Иванович"),
            ("Smith^John", "Smith John"),
            ("ПЕТРОВА^АННА^СЕРГЕЕВНА", "Петрова Анна Сергеевна"),
            ("van der Berg^Jan", "Van der Berg Jan"),
            ("Иванов Иван", "Иванов Иван"),
            ("", "—"),
            ("^^^", "—"),
        ],
    )
    def test_variants(self, raw, expected):
        assert format_person_name(raw, fallback="—") == expected

    def test_trailing_empty_components_are_dropped(self):
        assert format_person_name("DOE^JOHN^") == "Doe John"

    def test_fallback_is_used_for_blank_values(self):
        assert format_person_name("   ", fallback="Пациент не указан") == "Пациент не указан"


class TestDates:
    def test_dicom_date(self):
        assert format_dicom_date("20240404") == "04.04.2024"

    def test_dicom_date_passthrough(self):
        assert format_dicom_date("2024") == "2024"
        assert format_dicom_date("") == ""

    def test_dicom_time(self):
        assert format_dicom_time("113045.123") == "11:30"
        assert format_dicom_time("") == ""
        assert format_dicom_time("abc") == ""

    def test_relative_day_labels(self):
        today = datetime(2026, 10, 4, 12, 0)
        assert format_relative_day("20261004", today_label="Сегодня", now=today) == "Сегодня"
        assert format_relative_day("20261003", yesterday_label="Вчера", now=today) == "Вчера"
        assert format_relative_day("20240404", now=today) == "04.04.2024"
        assert format_relative_day("bad-date", now=today) == "bad-date"


class TestAge:
    @pytest.mark.parametrize(
        ("birth", "study", "expected"),
        [
            ("19570112", "20240404", "67 лет"),
            ("19800101", "20240101", "44 года"),
            ("20230101", "20240404", "1 год"),
            ("20240101", "20240404", "3 мес."),
            ("", "20240404", ""),
            ("20240404", "not-a-date", ""),
        ],
    )
    def test_age(self, birth, study, expected):
        assert format_patient_age(birth, study) == expected

    def test_english_forms(self):
        age = format_patient_age("19570112", "20240404", year_forms=("year", "years", "years"))
        assert age == "67 years"

    def test_birth_after_study_returns_empty(self):
        assert format_patient_age("20250101", "20240101") == ""

    def test_plural_rules(self):
        assert plural_ru(1, "год", "года", "лет") == "год"
        assert plural_ru(3, "год", "года", "лет") == "года"
        assert plural_ru(11, "год", "года", "лет") == "лет"
        assert plural_ru(22, "год", "года", "лет") == "года"


class TestSexAndSize:
    def test_sex(self):
        assert format_patient_sex("M") == "М"
        assert format_patient_sex("f") == "Ж"
        assert format_patient_sex("X") == ""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0.4, "0.4 МБ"), (42, "42 МБ"), (1536, "1.5 ГБ"), (None, ""), (0, "")],
    )
    def test_size(self, value, expected):
        assert format_size_mb(value) == expected


class TestPatientHeader:
    def test_full_header(self):
        class Study:
            patient_name = "ИВАНОВ^ИВАН^ИВАНОВИЧ"
            patient_sex = "M"
            patient_birth_date = "19570112"
            study_date = "20240404"
            patient_id = "1234567"

        header = format_patient_header(Study())
        assert header == "Иванов Иван Иванович · М · 67 лет · ID 1234567"

    def test_missing_fields_are_omitted(self):
        class Study:
            patient_name = ""
            patient_sex = ""
            patient_birth_date = ""
            study_date = "20240404"
            patient_id = ""

        assert format_patient_header(Study()) == "—"
