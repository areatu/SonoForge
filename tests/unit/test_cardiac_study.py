"""When is a study echocardiography? (ТЗ 2026-10-23, п. 1.)

The naming window of a free caliper («Подписать измерение») is a cardiology
affordance: in echo the distance is almost always one of a known set, while in
abdominal/thyroid/renal ultrasound the set is open-ended and the window only
interrupts a two-click measurement.  These tests hold the rule that decides it:

* positive DICOM evidence — a cardiac body part, a cardiac preset name, a
  cardiac view — turns the window on;
* everything else, including an empty header and a plain folder of MP4/JPEG
  clips, leaves it off.  The probe is not evidence: the same transducer drives a
  cardiac and an abdominal preset.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.cardiac_study import (
    CARDIAC_WORDS,
    body_part_marks_cardiac,
    is_cardiac_cine,
    is_cardiac_study,
    text_marks_cardiac,
)


class TestPositiveEvidence:
    @pytest.mark.parametrize(
        "text",
        [
            "Adult Echo",
            "Echo",
            "Echo/Cardiac",
            "Cardiac 2D",
            "TTE",
            "TEE",
            "A4C",
            "A2C",
            "Apical 4 chamber",
            "Apical 2 chamber",
            "PLAX",
            "PSAX",
            "Parasternal long axis",
            "Subcostal",
            "Suprasternal notch",
            "LVOT",
            "Left ventricle function",
            "Mitral valve",
        ],
    )
    def test_cardiac_preset_names_are_recognised(self, text: str):
        assert text_marks_cardiac(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "ЭхоКГ",
            "эхокардиография",
            "ЭХОКГ — 2D",
            "Кардио",
            "Сердце",
            # «ё» is normalised before matching.
            "Эхокардиография плода",
        ],
    )
    def test_russian_preset_names_are_recognised(self, text: str):
        assert text_marks_cardiac(text) is True

    @pytest.mark.parametrize("body_part", ["HEART", "heart", " Cardiac "])
    def test_a_cardiac_body_part_is_enough(self, body_part: str):
        assert body_part_marks_cardiac(body_part) is True


class TestNegativeEvidence:
    @pytest.mark.parametrize(
        "text",
        [
            "Abdomen",
            "Abdominal",
            "Thyroid",
            "Kidneys",
            "Renal",
            "Pelvis",
            "Obstetric",
            "Breast",
            # «Эхо» alone is Russian shorthand for *any* ultrasound.
            "Эхо-признаки",
            "УЗИ брюшной полости",
            "Общий УЗИ",
            # Placeholders of the application itself.
            "Test",
            "Cine (MP4)",
            "Still (JPEG)",
            "",
            "   ",
        ],
    )
    def test_general_ultrasound_is_not_cardiac(self, text: str):
        assert text_marks_cardiac(text) is False

    def test_an_unknown_body_part_is_not_cardiac(self):
        assert body_part_marks_cardiac("") is False
        assert body_part_marks_cardiac("ABDOMEN") is False


class TestStudyLevelRule:
    def test_any_positive_field_is_enough(self):
        assert is_cardiac_study(body_part="HEART") is True
        assert is_cardiac_study(series_description="Adult Echo") is True
        assert is_cardiac_study(study_description="ЭхоКГ") is True

    def test_an_empty_header_is_not_cardiac(self):
        """No evidence means «no» — the window keeps out of general ultrasound."""
        assert is_cardiac_study() is False
        assert is_cardiac_study(body_part="", series_description="", study_description="") is False

    def test_a_conflicting_header_does_not_turn_cardiac(self):
        assert (
            is_cardiac_study(
                body_part="ABDOMEN",
                series_description="Abdomen",
                study_description="US abdomen",
            )
            is False
        )

    def test_the_word_list_is_narrow(self):
        """Guards against a future «helpful» addition of «us»/«эхо»/«2d»."""
        for forbidden in ("us", "эхо", "2d", "ultrasound", "узи"):
            assert forbidden not in CARDIAC_WORDS


class TestPhaseMarkerEligibility:
    @pytest.mark.parametrize("description", ["A4C", "Adult Echo", "ЭхоКГ", "PLAX"])
    def test_positive_cardiac_clip(self, description):
        assert is_cardiac_cine(series_description=description)

    @pytest.mark.parametrize(
        "body_part,series",
        [
            ("LIVER", ""),
            ("THYROID", ""),
            ("ABDOMEN", ""),
            ("NECK", ""),
            ("", "Thyroid 2D"),
            ("", "Печень"),
            ("", "Щитовидная железа"),
            ("", "УЗИ брюшной полости"),
            ("HEART", "Liver"),
        ],
    )
    def test_local_organ_vetoes_generic_cardiac_study_title(self, body_part, series):
        assert not is_cardiac_cine(body_part=body_part, series_description=series, study_description="Adult Echo")

    @pytest.mark.parametrize("mode", ["doppler", "m_mode", "m", "pw", "cw"])
    def test_non_bmode_time_axes_are_excluded(self, mode):
        assert not is_cardiac_cine(clip_mode=mode, body_part="HEART")

    def test_unknown_media_is_not_classified_by_its_motion(self):
        assert not is_cardiac_cine()
        assert not is_cardiac_cine(series_description="Cine (MP4)")
        assert is_cardiac_cine(study_description="ЭхоКГ")
