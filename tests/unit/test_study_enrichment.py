"""Unit tests for domain/services/study_enrichment.py."""

from __future__ import annotations

from echo_personal_tool.domain.models.orthanc import StudyEnrichment
from echo_personal_tool.domain.services.study_enrichment import (
    device_kind,
    is_ste_candidate,
    is_stress_study,
    merge_enrichment,
    merge_enrichment_map,
)


class TestIsStressStudy:
    def test_protocol_marker_latin_and_cyrillic(self) -> None:
        assert is_stress_study("DOBUTAMINE")
        assert is_stress_study("ДОБУТАМИН")
        assert is_stress_study("Dobutamine 10")

    def test_stage_names_imply_stress(self) -> None:
        assert is_stress_study("", ["Rest"])
        assert is_stress_study("", ["Rest", "Peak"])

    def test_plain_study(self) -> None:
        assert not is_stress_study("")
        assert not is_stress_study("Free Form")
        assert not is_stress_study("", ["", "  "])


class TestDeviceKind:
    def test_known_models(self) -> None:
        assert device_kind("RS85-RUS") == "RS85"
        assert device_kind("ELVIS") == "ELVIS"
        assert device_kind("Cardiac 31 cm FPD Motorized") == "GE OEC"

    def test_unknown_model_kept_verbatim(self) -> None:
        assert device_kind("Vivid E95") == "Vivid E95"
        assert device_kind("  ") == ""


class TestIsSteCandidate:
    def test_multiframe_clip_without_regions(self) -> None:
        assert is_ste_candidate(modality="US", has_regions=False, number_of_frames=20)

    def test_regular_cine_with_regions(self) -> None:
        assert not is_ste_candidate(modality="US", has_regions=True, number_of_frames=20)

    def test_still_image(self) -> None:
        assert not is_ste_candidate(modality="US", has_regions=False, number_of_frames=None)
        assert not is_ste_candidate(modality="US", has_regions=False, number_of_frames=1)

    def test_non_us_never_matches(self) -> None:
        assert not is_ste_candidate(modality="XA", has_regions=False, number_of_frames=20)


class TestMerge:
    def test_merge_unions_modes_and_flags(self) -> None:
        a = StudyEnrichment(study_uid="u", modes=frozenset({"2D"}), patient_age="060Y")
        b = StudyEnrichment(
            study_uid="u",
            modes=frozenset({"PW"}),
            is_stress=True,
            stress_stages=("Peak",),
            stress_views=("A4C",),
            ste_candidate=True,
            device_kind="RS85",
        )
        merged = merge_enrichment(a, b)
        assert merged is not None
        assert merged.modes == frozenset({"2D", "PW"})
        assert merged.is_stress is True
        assert merged.ste_candidate is True
        assert merged.stress_stages == ("Peak",)
        assert merged.stress_views == ("A4C",)
        assert merged.device_kind == "RS85"
        assert merged.patient_age == "060Y"

    def test_merge_with_none(self) -> None:
        only = StudyEnrichment(study_uid="u")
        assert merge_enrichment(None, only) is only
        assert merge_enrichment(only, None) is only
        assert merge_enrichment(None, None) is None

    def test_merge_map_is_incremental(self) -> None:
        target = {"u": StudyEnrichment(study_uid="u", modes=frozenset({"2D"}))}
        merge_enrichment_map(target, {"u": StudyEnrichment(study_uid="u", modes=frozenset({"M"}))})
        merge_enrichment_map(target, {"v": StudyEnrichment(study_uid="v", device_kind="ELVIS")})
        assert target["u"].modes == frozenset({"2D", "M"})
        assert target["v"].device_kind == "ELVIS"
