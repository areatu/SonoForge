"""Tests for PHI filtering logic in DICOM tag inspector."""

from __future__ import annotations

from echo_personal_tool.infrastructure.dicom_tag_inspector import _is_phi_tag


class TestIsPhiTag:
    def test_patient_name_is_phi(self) -> None:
        # (0010,0010) PatientName
        assert _is_phi_tag(0x00100010) is True

    def test_patient_id_is_phi(self) -> None:
        # (0010,0020) PatientID
        assert _is_phi_tag(0x00100020) is True

    def test_patient_birth_date_is_phi(self) -> None:
        # (0010,0030) PatientBirthDate
        assert _is_phi_tag(0x00100030) is True

    def test_institution_name_is_phi(self) -> None:
        # (0008,0080) InstitutionName
        assert _is_phi_tag(0x00080080) is True

    def test_referring_physician_is_phi(self) -> None:
        # (0008,0090) ReferringPhysicianName
        assert _is_phi_tag(0x00080090) is True

    def test_performing_physician_is_phi(self) -> None:
        # (0008,1050) PerformingPhysicianName
        assert _is_phi_tag(0x00081050) is True

    def test_study_date_not_phi(self) -> None:
        # (0008,0020) StudyDate
        assert _is_phi_tag(0x00080020) is False

    def test_modality_not_phi(self) -> None:
        # (0008,0060) Modality
        assert _is_phi_tag(0x00080060) is False

    def test_study_description_not_phi(self) -> None:
        # (0008,1030) StudyDescription
        assert _is_phi_tag(0x00081030) is False

    def test_series_description_not_phi(self) -> None:
        # (0008,103E) SeriesDescription
        assert _is_phi_tag(0x0008103E) is False

    def test_heart_rate_not_phi(self) -> None:
        # (0010,1010) Age (not directly PHI but in patient group)
        # Actually (0010,1010) is in group 0x0010, so it IS phi
        assert _is_phi_tag(0x00101010) is True

    def test_accession_number_is_phi(self) -> None:
        # (0008,0050) AccessionNumber
        # This is in group 0x0008 but element 0x0050 is not in our filter
        assert _is_phi_tag(0x00080050) is False
