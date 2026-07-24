"""Unit tests for dicom_tag_dictionary lookup, search, and constants."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.dicom_tag_dictionary import (
    TAG_CONSTANTS,
    TagInfo,
    all_tags,
    lookup,
    search_by_keyword,
)


class TestTagInfo:
    def test_creation(self) -> None:
        info = TagInfo(tag=0x00100010, keyword="PatientName", vr="PN", description="Patient's Name")
        assert info.tag == 0x00100010
        assert info.keyword == "PatientName"
        assert info.vr == "PN"
        assert info.vm is None

    def test_with_vm(self) -> None:
        info = TagInfo(tag=0x00280030, keyword="PixelSpacing", vr="DS", description="Pixel Spacing", vm="2")
        assert info.vm == "2"


class TestLookup:
    def test_by_int(self) -> None:
        result = lookup(0x00100010)
        assert result is not None
        assert result.keyword == "PatientName"
        assert result.vr == "PN"

    def test_by_hex_string(self) -> None:
        result = lookup("00100010")
        assert result is not None
        assert result.keyword == "PatientName"

    def test_by_tuple(self) -> None:
        result = lookup((0x0010, 0x0010))
        assert result is not None
        assert result.keyword == "PatientName"

    def test_unknown_tag_returns_none(self) -> None:
        result = lookup(0xFFFFFFFF)
        assert result is None

    def test_unknown_hex_returns_none(self) -> None:
        result = lookup("FFFFFFFF")
        assert result is None

    def test_unknown_tuple_returns_none(self) -> None:
        result = lookup((0xFFFF, 0xFFFF))
        assert result is None

    def test_modality_tag(self) -> None:
        result = lookup(0x00080060)
        assert result is not None
        assert result.keyword == "Modality"
        assert result.vr == "CS"

    def test_pixel_spacing_tag(self) -> None:
        result = lookup((0x0028, 0x0030))
        assert result is not None
        assert result.keyword == "PixelSpacing"
        assert result.vm == "2"

    def test_frame_rate_tag(self) -> None:
        result = lookup(0x00186004)
        assert result is not None
        assert result.keyword == "FrameRate"


class TestAllTags:
    def test_returns_iterator(self) -> None:
        tags = list(all_tags())
        assert len(tags) > 100

    def test_ordered_by_tag_number(self) -> None:
        tags = list(all_tags())
        tag_numbers = [t.tag for t in tags]
        assert tag_numbers == sorted(tag_numbers)

    def test_all_are_tag_info(self) -> None:
        for tag in all_tags():
            assert isinstance(tag, TagInfo)


class TestSearchByKeyword:
    def test_exact_match(self) -> None:
        results = search_by_keyword("PatientName")
        assert len(results) >= 1
        assert any(r.keyword == "PatientName" for r in results)

    def test_case_insensitive(self) -> None:
        results = search_by_keyword("patient")
        assert len(results) >= 1

    def test_partial_match(self) -> None:
        results = search_by_keyword("Spacing")
        assert len(results) >= 1
        keywords = [r.keyword for r in results]
        assert any("Spacing" in kw for kw in keywords)

    def test_no_match(self) -> None:
        results = search_by_keyword("ZZZZZ_NONEXISTENT")
        assert results == []

    def test_pixel_search(self) -> None:
        results = search_by_keyword("Pixel")
        assert len(results) >= 3  # PixelSpacing, PixelRepresentation, etc.


class TestTagConstants:
    def test_patient_name(self) -> None:
        assert TAG_CONSTANTS["PATIENT_NAME"] == 0x00100010

    def test_modality(self) -> None:
        assert TAG_CONSTANTS["MODALITY"] == 0x00080060

    def test_pixel_spacing(self) -> None:
        assert TAG_CONSTANTS["PIXEL_SPACING"] == 0x00280030

    def test_frame_rate(self) -> None:
        assert TAG_CONSTANTS["FRAME_RATE"] == 0x00186004

    def test_rows(self) -> None:
        assert TAG_CONSTANTS["ROWS"] == 0x00280010

    def test_columns(self) -> None:
        assert TAG_CONSTANTS["COLUMNS"] == 0x00280011

    def test_number_of_frames(self) -> None:
        assert TAG_CONSTANTS["NUMBER_OF_FRAMES"] == 0x00280008

    def test_consistent_with_lookup(self) -> None:
        for name, tag_int in TAG_CONSTANTS.items():
            info = lookup(tag_int)
            assert info is not None, f"Constant {name}=0x{tag_int:08X} not found in lookup"

    def test_many_constants_defined(self) -> None:
        assert len(TAG_CONSTANTS) >= 60
