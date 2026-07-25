"""Verify PHI removal from DICOM files and anonymization of sensitive data.

Tests that PatientName, PatientID, BirthDate, and other PHI tags are
properly identified and filtered. Verifies study description cleaning.
"""

from __future__ import annotations

from pathlib import Path

import pydicom
import pytest

pytestmark = pytest.mark.security

from echo_personal_tool.infrastructure.dicom_tag_inspector import (
    _is_phi_tag,
    read_all_dicom_tag_rows,
)


class TestPhiTagIdentification:
    """Comprehensive tests for _is_phi_tag() across all PHI-sensitive DICOM tags."""

    # Patient group (0010,xxxx) — all are PHI
    @pytest.mark.parametrize(
        "tag_int,description",
        [
            (0x00100010, "PatientName"),
            (0x00100020, "PatientID"),
            (0x00100030, "PatientBirthDate"),
            (0x00100040, "PatientSex"),
            (0x00100100, "OtherPatientIDs"),
            (0x00101010, "PatientAge"),
            (0x00101020, "PatientSize"),
            (0x00101030, "PatientWeight"),
            (0x00102150, "CountryOfBirth"),
            (0x00102152, "RegionOfResidence"),
            (0x001021B0, "AdditionalPatientHistory"),
            (0x00104000, "PatientComments"),
        ],
    )
    def test_patient_group_is_phi(self, tag_int: int, description: str) -> None:
        assert _is_phi_tag(tag_int) is True, f"{description} should be PHI"

    # Institution/physician elements in group 0008
    @pytest.mark.parametrize(
        "tag_int,description",
        [
            (0x00080080, "InstitutionName"),
            (0x00080090, "ReferringPhysicianName"),
            (0x00081040, "InstitutionalDepartmentName"),
            (0x00081050, "PerformingPhysicianName"),
        ],
    )
    def test_institution_physician_is_phi(self, tag_int: int, description: str) -> None:
        assert _is_phi_tag(tag_int) is True, f"{description} should be PHI"

    # Non-PHI tags
    @pytest.mark.parametrize(
        "tag_int,description",
        [
            (0x00080020, "StudyDate"),
            (0x00080050, "AccessionNumber"),
            (0x00080060, "Modality"),
            (0x00081030, "StudyDescription"),
            (0x0008103E, "SeriesDescription"),
            (0x0020000D, "StudyInstanceUID"),
            (0x0020000E, "SeriesInstanceUID"),
            (0x00080018, "SOPInstanceUID"),
        ],
    )
    def test_non_phi_tags(self, tag_int: int, description: str) -> None:
        assert _is_phi_tag(tag_int) is False, f"{description} should NOT be PHI"

    def test_unknown_tag_not_phi(self) -> None:
        assert _is_phi_tag(0x99990001) is False

    def test_zero_tag_not_phi(self) -> None:
        assert _is_phi_tag(0x00000000) is False


class TestDicomTagRowFiltering:
    """Test that read_all_dicom_tag_rows with filter_phi=True removes PHI tags.

    Uses PatientID (LO VR) and PatientBirthDate (DA VR) to avoid the
    PersonName formatting code path which varies across pydicom versions.
    """

    def _make_dicom_file(self, tmp_path: Path) -> Path:
        """Create a minimal DICOM file with patient and study tags."""
        ds = pydicom.Dataset()
        ds.PatientID = "P001"
        ds.PatientBirthDate = "19900101"
        ds.StudyDate = "20250115"
        ds.StudyDescription = "Transthoracic Echo"
        ds.Modality = "US"

        file_meta = pydicom.Dataset()
        file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        file_meta.MediaStorageSOPInstanceUID = "1.2.3.4"
        file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
        ds.file_meta = file_meta

        f = tmp_path / "test.dcm"
        ds.save_as(f, enforce_file_format=True)
        return f

    def test_unfiltered_includes_all_tags(self, tmp_path: Path) -> None:
        f = self._make_dicom_file(tmp_path)
        rows = read_all_dicom_tag_rows(f, filter_phi=False)
        keywords = {r.keyword for r in rows}
        assert "PatientID" in keywords
        assert "StudyDate" in keywords

    def test_filtered_removes_patient_tags(self, tmp_path: Path) -> None:
        f = self._make_dicom_file(tmp_path)
        rows = read_all_dicom_tag_rows(f, filter_phi=True)
        keywords = {r.keyword for r in rows}
        # PHI tags should be filtered out
        assert "PatientID" not in keywords
        # Non-PHI tags should remain
        assert "StudyDate" in keywords

    def test_filtered_removes_birth_date(self, tmp_path: Path) -> None:
        f = self._make_dicom_file(tmp_path)
        rows = read_all_dicom_tag_rows(f, filter_phi=True)
        keywords = {r.keyword for r in rows}
        assert "PatientBirthDate" not in keywords


class TestAnonymizationCompleteness:
    """Verify that all expected PHI fields can be identified and filtered."""

    ALL_PHI_TAGS = [
        (0x00100010, "PatientName"),
        (0x00100020, "PatientID"),
        (0x00100030, "PatientBirthDate"),
        (0x00100040, "PatientSex"),
        (0x00080080, "InstitutionName"),
        (0x00080090, "ReferringPhysicianName"),
        (0x00081050, "PerformingPhysicianName"),
        (0x00081040, "InstitutionalDepartmentName"),
    ]

    @pytest.mark.parametrize("tag_int,description", ALL_PHI_TAGS)
    def test_phi_tag_identified(self, tag_int: int, description: str) -> None:
        assert _is_phi_tag(tag_int) is True, f"PHI tag {description} must be identified"

    def test_no_phi_leakage_in_study_description(self, tmp_path: Path) -> None:
        """Study descriptions are NOT PHI by default — verify they pass through."""
        ds = pydicom.Dataset()
        ds.StudyDescription = "Transthoracic Echocardiogram"
        ds.PatientID = "123"
        file_meta = pydicom.Dataset()
        file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        file_meta.MediaStorageSOPInstanceUID = "1.2.3"
        file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
        ds.file_meta = file_meta

        f = tmp_path / "test.dcm"
        ds.save_as(f, enforce_file_format=True)

        rows = read_all_dicom_tag_rows(f, filter_phi=True)
        descriptions = [r.value for r in rows if r.keyword == "StudyDescription"]
        assert len(descriptions) == 1
        assert "Echocardiogram" in descriptions[0]


class TestStudyDescriptionCleaning:
    """Verify study descriptions can contain arbitrary text safely."""

    @pytest.mark.parametrize(
        "description",
        [
            "Normal Study",
            "Echo - Rule out cardiomyopathy",
            "Follow-up: LV function",
            "Study with <special> characters",
            "Very " + "long " * 50 + "description",
            "",
        ],
    )
    def test_study_description_variants(self, description: str) -> None:
        from echo_personal_tool.infrastructure.orthanc_dicom_json import tag_value

        item = {
            "00081030": {"vr": "LO", "Value": [description]},
        }
        result = tag_value(item, "00081030")
        assert result == description
