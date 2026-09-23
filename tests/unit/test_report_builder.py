"""Unit tests for the structured study report (domain/services/report_builder.py)."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    DopplerResults,
    IndexedMeasurements,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
    PlanimeterResult,
    StrainReport,
)
from echo_personal_tool.domain.services.report_builder import (
    GROUP_AORTIC_VALVE,
    GROUP_LEFT_ATRIUM,
    GROUP_LEFT_VENTRICLE,
    GROUP_MITRAL_VALVE,
    GROUP_PLANIMETRY,
    GROUP_TRICUSPID_VALVE,
    GROUP_VESSELS,
    PatientInfo,
    build_report_document,
    build_report_groups,
    format_norm,
    format_sex,
    group_for_label,
    is_pathological,
    norm_range_for,
)
from echo_personal_tool.infrastructure.i18n import tr


def _snapshot(**kwargs) -> MeasurementSnapshot:
    return MeasurementSnapshot(**kwargs)


def _values(groups, key: str) -> dict[str, str]:
    for group in groups:
        if group.key == key:
            return {value.label: value.value for value in group.values}
    return {}


class TestNormLookup:
    """Norms come from the structured ASE reference data, per sex."""

    def test_sex_specific_range(self) -> None:
        male = norm_range_for("LVEDD", "M")
        female = norm_range_for("LVEDD", "F")
        assert male is not None and female is not None
        assert (male.low, male.high) == (42.0, 59.0)
        assert (female.low, female.high) == (36.0, 51.0)

    def test_upper_bound_only(self) -> None:
        norm = norm_range_for("LAVi", "M")
        assert norm is not None
        assert norm.low is None
        assert norm.high == 34.0

    def test_unknown_label_has_no_norm(self) -> None:
        assert norm_range_for("Some random label", "M") is None

    @pytest.mark.parametrize(
        ("sex", "expected"),
        [("", False), ("M", False), ("М", False), ("F", True), ("Ж", True), ("female", True)],
    )
    def test_format_sex(self, sex: str, expected: bool) -> None:
        assert (format_sex(sex) == format_sex("F")) is expected

    @pytest.mark.parametrize("sex", ["O", "X", "", "  "])
    def test_unknown_sex_is_not_reported_as_male(self, sex: str) -> None:
        """DICOM ``O`` means Other; it must not be printed as male."""
        assert format_sex(sex) == format_sex("")
        assert format_sex(sex) != format_sex("M")
        assert format_sex(sex) != format_sex("F")

    def test_male_sex_is_reported_as_male(self) -> None:
        assert format_sex("M") == format_sex("М") == format_sex("male")


class TestNormFormatting:
    def test_range(self) -> None:
        from echo_personal_tool.domain.services.ase_reference_norms import NormRange

        assert format_norm(NormRange(low=42.0, high=59.0)) == "42–59"

    def test_small_values_keep_two_decimals(self) -> None:
        from echo_personal_tool.domain.services.ase_reference_norms import NormRange

        # 0.32–0.42 must not be rounded to 0.3–0.4.
        assert format_norm(NormRange(low=0.32, high=0.42)) == "0.32–0.42"

    def test_unit_conversion_back_to_app_units(self) -> None:
        from echo_personal_tool.domain.services.ase_reference_norms import NormRange

        # The reference stores TR Vmax in m/s; the app reports cm/s.
        assert format_norm(NormRange(high=2.8), scale=0.01) == "≤280"

    def test_none(self) -> None:
        assert format_norm(None) == ""


class TestPathology:
    def test_value_above_range_is_pathological(self) -> None:
        pathological, norm = is_pathological("LVEDD", 62.0, "M", norm_label="LVEDD")
        assert pathological is True
        assert norm == "42–59"

    def test_value_inside_range_is_not(self) -> None:
        pathological, norm = is_pathological("LVEDD", 50.0, "M", norm_label="LVEDD")
        assert pathological is False
        assert norm == "42–59"

    def test_unit_conversion_applies_to_value(self) -> None:
        # 310 cm/s = 3.1 m/s is above the 2.8 m/s limit; 250 cm/s is not.
        assert is_pathological("TR Vmax", 310.0, "M")[0] is True
        assert is_pathological("TR Vmax", 250.0, "M")[0] is False

    def test_none_value_is_never_pathological(self) -> None:
        assert is_pathological("LVEDD", None, "M") == (False, "")


class TestGrouping:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("LVEDD", GROUP_LEFT_VENTRICLE),
            ("IVSd", GROUP_LEFT_VENTRICLE),
            ("LVPWd", GROUP_LEFT_VENTRICLE),
            # LVOT diameter belongs to the aortic assessment (AVA = f(LVOTd)).
            ("LVOTd", GROUP_AORTIC_VALVE),
            ("ФВ ЛЖ", GROUP_LEFT_VENTRICLE),
            ("LAVi Bi", GROUP_LEFT_ATRIUM),
            ("MVd", GROUP_MITRAL_VALVE),
            ("MR jet", GROUP_MITRAL_VALVE),
            ("MV area", GROUP_MITRAL_VALVE),
            ("PHT", GROUP_MITRAL_VALVE),
            ("E", GROUP_MITRAL_VALVE),
            ("A", GROUP_MITRAL_VALVE),
            ("DT", GROUP_MITRAL_VALVE),
            ("IVRT", GROUP_MITRAL_VALVE),
        ],
    )
    def test_group_for_label(self, label: str, expected: str) -> None:
        assert group_for_label(label) == expected


class TestBuildReportGroups:
    def test_measurements_land_in_their_anatomical_group(self) -> None:
        snapshot = _snapshot(
            lvef=LvefResult(
                a4c=LvViewMetrics(length_ed_mm=85.0, edv_ml=120.0, esv_ml=45.0),
                lvef_percent=48.0,
            ),
            linear_measurements=(
                LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=62.0),
                LinearMeasurement(label="MVd", pixel_length=40, millimeter_length=20.0),
            ),
        )
        groups = build_report_groups(snapshot, sex="M")
        keys = [group.key for group in groups]
        assert GROUP_LEFT_VENTRICLE in keys
        assert GROUP_MITRAL_VALVE in keys
        # Groups come in anatomical order, not in insertion order.
        assert keys.index(GROUP_LEFT_VENTRICLE) < keys.index(GROUP_MITRAL_VALVE)
        assert "LVEDD" in _values(groups, GROUP_LEFT_VENTRICLE)
        assert "MVd" in _values(groups, GROUP_MITRAL_VALVE)

    def test_group_titles_are_translated_once_per_group(self) -> None:
        snapshot = _snapshot(
            linear_measurements=(
                LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=62.0),
                LinearMeasurement(label="IVSd", pixel_length=20, millimeter_length=13.0),
            )
        )
        groups = build_report_groups(snapshot, sex="M")
        lv = next(group for group in groups if group.key == GROUP_LEFT_VENTRICLE)
        assert lv.title
        assert all(value.label for value in lv.values)

    def test_empty_snapshot_produces_no_groups(self) -> None:
        assert build_report_groups(MeasurementSnapshot(), sex="M") == ()

    def test_doppler_values_are_grouped_by_valve(self) -> None:
        snapshot = _snapshot(
            doppler=DopplerResults(e_cm_s=95.0, a_cm_s=60.0, tr_vmax_cm_s=310.0),
        )
        groups = build_report_groups(snapshot, sex="M")
        assert "E" in _values(groups, GROUP_MITRAL_VALVE)
        assert "TR Vmax" in _values(groups, GROUP_TRICUSPID_VALVE)

    def test_tr_vmax_norm_is_reported_in_app_units(self) -> None:
        snapshot = _snapshot(doppler=DopplerResults(tr_vmax_cm_s=310.0))
        groups = build_report_groups(snapshot, sex="M")
        tr_row = next(
            value
            for group in groups
            for value in group.values
            if value.label == "TR Vmax"
        )
        assert tr_row.norm == "≤280"
        assert tr_row.pathological is True

    def test_indexed_values_use_the_indexed_norm(self) -> None:
        snapshot = _snapshot(
            indexed=IndexedMeasurements(bsa_m2=1.9, lvmi_g_m2=126.0, lav_bi_index_ml_m2=40.0)
        )
        groups = build_report_groups(snapshot, sex="M")
        lv = _values(groups, GROUP_LEFT_VENTRICLE)
        assert "LVMI" in lv
        lavi = _values(groups, GROUP_LEFT_ATRIUM)
        assert "LAVi Bi" in lavi
        flagged = {
            value.label
            for group in groups
            for value in group.values
            if value.pathological
        }
        assert {"LVMI", "LAVi Bi"} <= flagged

    def test_planimeter_measurements_form_their_own_group(self) -> None:
        snapshot = _snapshot(
            planimeter=(PlanimeterResult(label="Thrombus", kind="area", value=3.4, unit="cm²"),)
        )
        groups = build_report_groups(snapshot, sex="M")
        assert [group.key for group in groups] == [GROUP_PLANIMETRY]
        assert _values(groups, GROUP_PLANIMETRY)["Thrombus"] == "3.40"

    def test_strain_values_are_flagged_against_gls_norm(self) -> None:
        snapshot = _snapshot(
            strain=StrainReport(
                gls_by_view=(("A4C", -14.0),),
                qc_by_view=(("A4C", "valid"),),
                gls_average=-14.0,
                views_valid=("A4C",),
            )
        )
        groups = build_report_groups(snapshot, sex="M")
        lv = next(group for group in groups if group.key == GROUP_LEFT_VENTRICLE)
        gls_rows = [value for value in lv.values if value.norm]
        assert gls_rows, "GLS rows must carry the reference range"
        assert all(value.pathological for value in gls_rows)

    def test_length_unit_preference_is_applied(self) -> None:
        snapshot = _snapshot(
            linear_measurements=(
                LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=62.0),
            )
        )
        mm = build_report_groups(snapshot, sex="M", length_display_unit="mm")
        cm = build_report_groups(snapshot, sex="M", length_display_unit="cm")
        assert _values(mm, GROUP_LEFT_VENTRICLE)["LVEDD"] == "62.0"
        assert _values(cm, GROUP_LEFT_VENTRICLE)["LVEDD"] == "6.2"

    @pytest.mark.parametrize("label", ["%D", "%S", "%D стеноз", "%S стеноз"])
    def test_percent_calipers_are_reported_in_percent(self, label: str) -> None:
        """A stenosis degree is a percentage, not a length."""
        snapshot = _snapshot(
            linear_measurements=(
                LinearMeasurement(label=label, pixel_length=0.0, millimeter_length=80.0),
            )
        )
        rows = next(
            (v for g in build_report_groups(snapshot, sex="M") for v in g.values if v.label == label),
            None,
        )
        assert rows is not None
        assert (rows.value, rows.unit) == ("80.0", "%")

    def test_percent_calipers_ignore_length_unit(self) -> None:
        snapshot = _snapshot(
            linear_measurements=(
                LinearMeasurement(label="%S стеноз", pixel_length=0.0, millimeter_length=80.0),
            )
        )
        mm = build_report_groups(snapshot, sex="M", length_display_unit="mm")
        cm = build_report_groups(snapshot, sex="M", length_display_unit="cm")
        row_mm = next(v for g in mm for v in g.values if v.label == "%S стеноз")
        row_cm = next(v for g in cm for v in g.values if v.label == "%S стеноз")
        assert (row_mm.value, row_mm.unit) == (row_cm.value, row_cm.unit) == ("80.0", "%")

    def test_percent_and_length_calipers_coexist(self) -> None:
        snapshot = _snapshot(
            linear_measurements=(
                LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=62.0),
                LinearMeasurement(label="%D стеноз", pixel_length=0.0, millimeter_length=60.0),
            )
        )
        groups = build_report_groups(snapshot, sex="M", length_display_unit="mm")
        assert _values(groups, GROUP_LEFT_VENTRICLE)["LVEDD"] == "62.0"
        vessel = next(v for g in groups for v in g.values if v.label == "%D стеноз")
        assert (vessel.value, vessel.unit, vessel.group) == ("60.0", "%", GROUP_VESSELS)

    def test_unpixel_calibrated_values_are_reported_as_pixels(self) -> None:
        snapshot = _snapshot(
            spacing_calibrated=False,
            linear_measurements=(
                LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=62.0),
            ),
        )
        groups = build_report_groups(snapshot, sex="M")
        row = next(
            value for group in groups for value in group.values if value.label == "LVEDD"
        )
        assert row.unit == "px"
        assert row.value == "120"


class TestBuildReportDocument:
    def test_document_carries_patient_and_groups(self) -> None:
        snapshot = _snapshot(rwt=0.45)
        document = build_report_document(
            snapshot,
            PatientInfo(name="Иванов И.И.", sex="M"),
            sex="M",
        )
        assert document.patient.name == "Иванов И.И."
        assert document.has_measurements is True
        # Row labels are translated, so compare through tr() as well.
        assert tr("domain.report.rwt") in {
            value.label for value in document.pathological_values
        }

    def test_empty_document(self) -> None:
        document = build_report_document(None, None)
        assert document.has_measurements is False
        assert document.pathological_values == ()

    def test_bsa_is_taken_from_the_snapshot(self) -> None:
        snapshot = _snapshot(indexed=IndexedMeasurements(bsa_m2=1.93))
        document = build_report_document(snapshot, PatientInfo(), sex="M")
        assert document.patient.bsa_m2 == pytest.approx(1.93)

    def test_explicit_bsa_is_not_overwritten(self) -> None:
        snapshot = _snapshot(indexed=IndexedMeasurements(bsa_m2=1.93))
        document = build_report_document(
            snapshot, PatientInfo(bsa_m2=2.10), sex="M"
        )
        assert document.patient.bsa_m2 == pytest.approx(2.10)
