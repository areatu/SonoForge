"""Tests for dicom_tag_dictionary module."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.dicom_tag_dictionary import (
    MODALITY,
    PATIENT_ID,
    PATIENT_NAME,
    PIXEL_SPACING,
    STUDY_DATE,
    TAG_CONSTANTS,
    TagInfo,
    all_tags,
    lookup,
    search_by_keyword,
)


class TestLookup:
    def test_int_lookup(self) -> None:
        info = lookup(0x00100010)
        assert info is not None
        assert info.keyword == "PatientName"
        assert info.vr == "PN"
        assert info.tag == 0x00100010

    def test_hex_string_lookup(self) -> None:
        info = lookup("00100010")
        assert info is not None
        assert info.keyword == "PatientName"

    def test_tuple_lookup(self) -> None:
        info = lookup((0x0010, 0x0010))
        assert info is not None
        assert info.keyword == "PatientName"

    def test_missing_tag_returns_none(self) -> None:
        assert lookup(0x99999999) is None

    def test_invalid_hex_string(self) -> None:
        with pytest.raises(ValueError):
            lookup("ZZZZZZZZ")

    def test_modality_lookup(self) -> None:
        info = lookup("00080060")
        assert info is not None
        assert info.keyword == "Modality"
        assert info.vr == "CS"

    def test_pixel_spacing_lookup(self) -> None:
        info = lookup(0x00280030)
        assert info is not None
        assert info.keyword == "PixelSpacing"
        assert info.vm == "2"

    def test_study_instance_uid(self) -> None:
        info = lookup((0x0020, 0x000D))
        assert info is not None
        assert info.keyword == "StudyInstanceUID"


class TestTagInfo:
    def test_frozen(self) -> None:
        info = TagInfo(tag=0x00100010, keyword="PatientName", vr="PN", description="Patient's Name")
        with pytest.raises(AttributeError):
            info.keyword = "Changed"  # type: ignore[misc]

    def test_optional_vm(self) -> None:
        info = TagInfo(
            tag=0x00280030,
            keyword="PixelSpacing",
            vr="DS",
            description="Pixel Spacing",
            vm="2",
        )
        assert info.vm == "2"

    def test_vm_none_default(self) -> None:
        info = TagInfo(tag=0x00100010, keyword="PatientName", vr="PN", description="Patient's Name")
        assert info.vm is None


class TestModuleConstants:
    def test_patient_name(self) -> None:
        assert PATIENT_NAME == 0x00100010

    def test_patient_id(self) -> None:
        assert PATIENT_ID == 0x00100020

    def test_modality(self) -> None:
        assert MODALITY == 0x00080060

    def test_pixel_spacing(self) -> None:
        assert PIXEL_SPACING == 0x00280030

    def test_study_date(self) -> None:
        assert STUDY_DATE == 0x00080020

    def test_all_constants_are_valid_ints(self) -> None:
        for name, tag_int in TAG_CONSTANTS.items():
            assert isinstance(tag_int, int)
            info = lookup(tag_int)
            assert info is not None, f"Constant {name}={hex(tag_int)} not found in dictionary"


class TestAllTags:
    def test_returns_iterator(self) -> None:
        tags = list(all_tags())
        assert len(tags) > 200

    def test_sorted_by_tag_number(self) -> None:
        tags = list(all_tags())
        tag_numbers = [t.tag for t in tags]
        assert tag_numbers == sorted(tag_numbers)

    def test_all_are_tag_info(self) -> None:
        for tag in all_tags():
            assert isinstance(tag, TagInfo)


class TestSearchByKeyword:
    def test_patient_matches(self) -> None:
        results = search_by_keyword("Patient")
        assert len(results) > 5
        keywords = {r.keyword for r in results}
        assert "PatientName" in keywords
        assert "PatientID" in keywords

    def test_case_insensitive(self) -> None:
        lower = search_by_keyword("modality")
        upper = search_by_keyword("MODALITY")
        assert len(lower) == len(upper)
        assert len(lower) > 0

    def test_partial_match(self) -> None:
        results = search_by_keyword("Transducer")
        assert len(results) > 0
        for r in results:
            assert "transducer" in r.keyword.lower()

    def test_no_match(self) -> None:
        results = search_by_keyword("ZZZZNONEXISTENT")
        assert results == []
