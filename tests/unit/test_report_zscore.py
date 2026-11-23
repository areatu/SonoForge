"""Z-score rows of the report (plan А.12, issue #650) — the honest projection.

The paediatric sheet re-reads the key sizes as Z-scores against body size;
the fetal sheet against gestational age.  No axis input or no covering band
→ no row: an invented reference is worse than a missing one.  The row names
the table it used, so the shipped seed can never pass for a verified source.
"""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import IndexedMeasurements, MeasurementSnapshot
from echo_personal_tool.domain.services.pediatric_norms import load_norms
from echo_personal_tool.domain.services.report_builder import build_report_document
from echo_personal_tool.domain.services.report_document import PatientInfo
from echo_personal_tool.domain.services.report_zscore import zscore_report_values

PEDIATRIC_PROFILE = "builtin.pediatric_echo"
FETAL_PROFILE = "builtin.fetal_echo"


def _snapshot_with(lvedd_mm: float = 34.0) -> MeasurementSnapshot:
    return MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=lvedd_mm, millimeter_length=lvedd_mm),),
    )


class TestPediatricRows:
    def test_the_key_size_is_z_scored_against_bsa(self) -> None:
        rows = zscore_report_values(
            _snapshot_with(), PatientInfo(bsa_m2=1.0), load_norms(), study_profile_id=PEDIATRIC_PROFILE
        )
        lvedd = next(row for row in rows if row.parameter_id == "lv.lvedd")
        assert lvedd.value == "+0.00 (P50)"  # the seed mean at BSA 1.0 is 34 mm
        assert lvedd.group == "lv"
        assert "seed" in lvedd.norm

    def test_an_adult_profile_gets_nothing(self) -> None:
        rows = zscore_report_values(
            _snapshot_with(), PatientInfo(bsa_m2=1.0), load_norms(), study_profile_id="builtin.adult_echo"
        )
        assert rows == ()

    def test_no_bsa_no_rows(self) -> None:
        rows = zscore_report_values(_snapshot_with(), PatientInfo(), load_norms(), study_profile_id=PEDIATRIC_PROFILE)
        assert rows == ()

    def test_indexed_volumes_reach_the_rows(self) -> None:
        snapshot = MeasurementSnapshot(
            spacing_calibrated=True,
            indexed=IndexedMeasurements(bsa_m2=1.0, simpson_edvi_ml_m2=78.0),
        )
        rows = zscore_report_values(snapshot, PatientInfo(), load_norms(), study_profile_id=PEDIATRIC_PROFILE)
        edvi = next(row for row in rows if row.parameter_id == "lv.edvi")
        assert edvi.value == "+0.00 (P50)"


class TestFetalRows:
    def test_fetal_biometry_needs_the_gestational_age(self) -> None:
        snapshot = MeasurementSnapshot(
            spacing_calibrated=True,
            linear_measurements=(LinearMeasurement(label="FET-AO", pixel_length=4.3, millimeter_length=4.3),),
        )
        rows = zscore_report_values(snapshot, PatientInfo(), load_norms(), study_profile_id=FETAL_PROFILE)
        assert rows == ()
        rows = zscore_report_values(
            snapshot, PatientInfo(gestational_weeks=28.0), load_norms(), study_profile_id=FETAL_PROFILE
        )
        ao = next(row for row in rows if row.parameter_id == "fetal.ao_root")
        assert ao.value == "+0.00 (P50)"
        assert ao.group == "fetal"


class TestDocumentHook:
    def test_the_paediatric_document_prints_the_z_rows(self) -> None:
        document = build_report_document(
            _snapshot_with(36.0),
            PatientInfo(bsa_m2=1.0),
            study_profile_id=PEDIATRIC_PROFILE,
        )
        lvedd = next(
            row
            for group in document.groups
            for row in group.values
            if row.parameter_id == "lv.lvedd" and row.value.startswith(("+", "-"))
        )
        # 36 mm at BSA 1.0 (mean 34, sd 4.2) is half an SD above the mean.
        assert lvedd.value.startswith("+0.48")

    def test_the_full_document_hook_skips_the_adult_study(self) -> None:
        document = build_report_document(
            _snapshot_with(),
            PatientInfo(bsa_m2=1.0),
            study_profile_id="builtin.adult_echo",
        )
        norm_ids = set(load_norms().measurement_ids())
        assert not any(
            row.parameter_id in norm_ids and row.value.startswith(("+", "-"))
            for group in document.groups
            for row in group.values
        )
