"""Item 7 of the 2026-11-06 list: the report format in the sheet header.

The owner works with abdominal and thyroid ultrasound in the same application,
and «Протокол ЭхоКГ» with cardiology norm dots on an abdominal study is wrong.
The format is therefore *content*: it sets the printed title and the groups that
belong to the document, once, so the preview, the PDF, the CSV and the JSON
export cannot disagree.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.body_surface import resolve_bsa_basis
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import IndexedMeasurements, MeasurementSnapshot
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.services.report_builder import (
    GROUP_ABDOMEN,
    GROUP_KIDNEY,
    GROUP_LEFT_VENTRICLE,
    GROUP_OTHER,
    GROUP_PLANIMETRY,
    GROUP_PRECEREBRAL,
    GROUP_THYROID,
    GROUP_VESSELS,
    PatientInfo,
    build_report_document,
)
from echo_personal_tool.domain.services.report_profiles import (
    DEFAULT_PROFILE_ID,
    PROFILE_ABDOMEN,
    PROFILE_ECHO,
    PROFILE_KIDNEY,
    PROFILE_ORDER,
    PROFILE_THYROID,
    PROFILE_ULTRASOUND,
    PROFILE_VASCULAR,
    PROFILES,
    normalize_profile_id,
    profile,
    profile_for_study,
    profile_title,
)


def _snapshot() -> MeasurementSnapshot:
    """A study with one cardiac caliper and one vessel Doppler measurement."""
    basis = resolve_bsa_basis(height_cm=170, weight_kg=65)
    return MeasurementSnapshot(
        height_cm=170,
        weight_kg=65,
        linear_measurements=(
            LinearMeasurement(label="КДР ЛЖ", pixel_length=96.0, millimeter_length=48.0),
            # A plain caliper of another organ lands in the «прочие» group, which
            # the generic protocol also drops — that is where cardiac labels go.
            LinearMeasurement(label="Печень: передне-задний", pixel_length=240.0, millimeter_length=120.0),
        ),
        vessel_measurements=(
            VesselMeasurement(
                psv_cm_s=60.0,
                edv_cm_s=20.0,
                ri=0.67,
                sd=3.0,
                mv_approx=4.0,
                sop_instance_uid="1.2.3",
                frame_index=0,
                measurement_id="vessel-1",
            ),
        ),
        indexed=IndexedMeasurements(bsa_m2=basis.value or 1.7),
    )


def _translate(key: str) -> str:
    return {
        "report.title": "Протокол эхокардиографии",
        "report.title.ultrasound": "Протокол ультразвукового исследования",
        "report.title.vascular": "Протокол ультразвукового исследования прецеребральных артерий",
        "report.title.abdomen": "Протокол ультразвукового исследования органов брюшной полости",
        "report.title.kidney": "Протокол ультразвукового исследования почек",
        "report.title.thyroid": "Протокол ультразвукового исследования щитовидной железы",
    }.get(key, key)


# ── the registry ────────────────────────────────────────────────────


def test_the_formats_exist_and_the_echo_one_is_the_default() -> None:
    assert [spec.id for spec in PROFILES] == [
        PROFILE_ECHO,
        PROFILE_VASCULAR,
        PROFILE_ABDOMEN,
        PROFILE_KIDNEY,
        PROFILE_THYROID,
        PROFILE_ULTRASOUND,
    ]
    assert PROFILE_ORDER[0] == DEFAULT_PROFILE_ID == PROFILE_ECHO


def test_an_unknown_format_falls_back_to_the_default() -> None:
    """A saved tab of a newer or older build must still open."""
    assert normalize_profile_id("cardio_mri") == DEFAULT_PROFILE_ID
    assert normalize_profile_id("") == DEFAULT_PROFILE_ID
    assert normalize_profile_id(None) == DEFAULT_PROFILE_ID
    assert profile("cardio_mri").id == DEFAULT_PROFILE_ID


def test_every_format_has_a_localised_label_key() -> None:
    for spec in PROFILES:
        assert spec.label_key == f"report.profile.{spec.id}"


def test_the_auto_selection_only_picks_the_starting_value() -> None:
    assert profile_for_study(cardiac=True) == PROFILE_ECHO
    assert profile_for_study(cardiac=False) == PROFILE_ULTRASOUND


# ── the document ────────────────────────────────────────────────────


def test_the_echo_document_keeps_every_group_and_prints_its_title() -> None:
    document = build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=PROFILE_ECHO)
    keys = {group.key for group in document.groups}
    assert GROUP_LEFT_VENTRICLE in keys
    assert GROUP_VESSELS in keys
    assert document.profile_id == PROFILE_ECHO
    assert document.title == "Протокол эхокардиографии"


def test_the_ultrasound_document_drops_the_cardiology_groups() -> None:
    document = build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=PROFILE_ULTRASOUND)
    keys = {group.key for group in document.groups}
    assert GROUP_LEFT_VENTRICLE not in keys, "a chamber of the heart is not part of an abdominal protocol"
    assert GROUP_OTHER not in keys, "«прочие» is where cardiac caliper labels land"
    assert GROUP_VESSELS in keys, "a measured vessel must stay"


def test_the_ultrasound_document_is_titled_differently() -> None:
    document = build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=PROFILE_ULTRASOUND)
    assert document.title == "Протокол ультразвукового исследования"
    assert profile_title(PROFILE_ULTRASOUND, _translate) == "Протокол ультразвукового исследования"


def _organ_snapshot() -> MeasurementSnapshot:
    return MeasurementSnapshot(
        linear_measurements=(
            LinearMeasurement(label="Почка П длина", pixel_length=100.0, millimeter_length=105.0),
            LinearMeasurement(label="ЩЖ П толщина", pixel_length=20.0, millimeter_length=18.0),
        ),
    )


def test_the_kidney_document_prints_the_kidney_protocol() -> None:
    """«УЗИ почек» measures go to the kidney report, not a generic one."""
    document = build_report_document(_organ_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=PROFILE_KIDNEY)
    keys = {group.key for group in document.groups}
    assert document.title == "Протокол ультразвукового исследования почек"
    assert GROUP_KIDNEY in keys
    assert GROUP_THYROID not in keys, "the gland is not part of a renal protocol"
    assert GROUP_LEFT_VENTRICLE not in keys


def test_the_thyroid_document_drops_the_other_organ_blocks() -> None:
    document = build_report_document(_organ_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=PROFILE_THYROID)
    keys = {group.key for group in document.groups}
    assert document.title == "Протокол ультразвукового исследования щитовидной железы"
    assert GROUP_THYROID in keys
    assert GROUP_KIDNEY not in keys
    assert GROUP_PRECEREBRAL not in keys
    assert GROUP_ABDOMEN not in keys


def test_an_unset_format_is_the_old_document() -> None:
    """Callers that do not know about formats keep the pre-item-7 behaviour."""
    empty = build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M")
    default = build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=PROFILE_ECHO)
    assert empty.title == "" and empty.profile_id == ""
    assert [group.key for group in empty.groups] == [group.key for group in default.groups]


def test_the_generic_format_is_a_deny_list_not_an_allow_list() -> None:
    """A new group appears in every format until somebody excludes it."""
    assert GROUP_PLANIMETRY not in profile(PROFILE_ULTRASOUND).excluded_groups


# ── the export follows the document ─────────────────────────────────


def test_the_json_export_names_the_format(tmp_path) -> None:
    import json

    from echo_personal_tool.application.report_export import render_report_json

    document = build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=PROFILE_ULTRASOUND)
    path = render_report_json(document, tmp_path / "report.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert {group["key"] for group in payload["groups"]} == {group.key for group in document.groups}
    assert GROUP_LEFT_VENTRICLE not in {group["key"] for group in payload["groups"]}


def test_the_csv_export_holds_the_groups_of_the_format(tmp_path) -> None:
    import csv

    from echo_personal_tool.application.report_export import render_report_csv

    document = build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=PROFILE_ULTRASOUND)
    path = render_report_csv(document, tmp_path / "report.csv")
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "the study has a vessel measurement, so the sheet is not empty"
    assert {row["group"] for row in rows} <= {group.key for group in document.groups}
    assert GROUP_LEFT_VENTRICLE not in {row["group"] for row in rows}


@pytest.mark.parametrize(
    ("profile_id", "expected", "forbidden"),
    [
        (PROFILE_ECHO, "Протокол эхокардиографии", "ультразвукового"),
        (PROFILE_VASCULAR, "Протокол ультразвукового исследования прецеребральных артерий", "щитовидной"),
        (PROFILE_ABDOMEN, "Протокол ультразвукового исследования органов брюшной полости", "щитовидной"),
        (PROFILE_KIDNEY, "Протокол ультразвукового исследования почек", "щитовидной"),
        (PROFILE_THYROID, "Протокол ультразвукового исследования щитовидной железы", "брюшной"),
        (PROFILE_ULTRASOUND, "Протокол ультразвукового исследования", "эхокардиографии"),
    ],
)
def test_the_pdf_sheet_is_titled_by_the_document(
    profile_id: str,
    expected: str,
    forbidden: str,
    tmp_path,
) -> None:
    """The sheet, the PDF and the export say the same thing."""
    from echo_personal_tool.application.report_export import export_report_document_pdf

    document = build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M", profile_id=profile_id)
    path = export_report_document_pdf(document, tmp_path / "report.pdf")
    assert path.is_file() and path.stat().st_size > 0

    # The full protocol titles wrap over lines on the sheet; compare the words.
    text = " ".join(_pdf_text(path).split())
    assert expected in text
    assert forbidden not in text


def _pdf_text(path) -> str:
    import fitz  # PyMuPDF

    with fitz.open(path) as pdf:
        return "\n".join(page.get_text() for page in pdf)
