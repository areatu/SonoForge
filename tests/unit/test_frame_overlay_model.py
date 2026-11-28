"""The frame overlay model (``viewer.frame_overlay``).

Viewer-level rendering is pinned by the widget tests (calibration banner
styles, transcript transcript lines); these pin the extracted pure model:
ordered lines, exact-line banner recognition and the style/width variant.
"""

from __future__ import annotations

from echo_personal_tool.presentation.viewer.frame_overlay import (
    CALIBRATION_MIN_WIDTH,
    CALIBRATION_PROMPT_STYLE,
    CALIBRATION_SUCCESS_STYLE,
    DEFAULT_STYLE,
    FrameOverlayModel,
)


def test_a_fresh_model_is_empty() -> None:
    model = FrameOverlayModel()
    assert model.lines() == ()
    assert model.text() == ""
    style, width = model.style()
    assert style == DEFAULT_STYLE
    assert width == 0


def test_lines_append_in_order_and_join_with_newlines() -> None:
    model = FrameOverlayModel()
    model.append("IVSd: 10.0 mm (20.0 px)")
    model.append("LVEDD: 50.0 mm (100.0 px)")
    assert model.lines() == ("IVSd: 10.0 mm (20.0 px)", "LVEDD: 50.0 mm (100.0 px)")
    assert model.text() == "IVSd: 10.0 mm (20.0 px)\nLVEDD: 50.0 mm (100.0 px)"
    assert model.style() == (DEFAULT_STYLE, 0)


def test_clear_resets_to_the_default_variant() -> None:
    model = FrameOverlayModel()
    model.append("anything")
    model.clear()
    assert model.lines() == ()
    assert model.style() == (DEFAULT_STYLE, 0)


def test_the_calibration_prompt_banner_uses_its_variant() -> None:
    from echo_personal_tool.application.localization import tr
    from echo_personal_tool.presentation.viewer.frame_overlay import CALIBRATION_PROMPT_OVERLAY_KEY

    model = FrameOverlayModel()
    model.append(tr(CALIBRATION_PROMPT_OVERLAY_KEY))
    assert model.is_calibration_prompt() is True
    assert model.is_calibration_success() is False
    assert model.style() == (CALIBRATION_PROMPT_STYLE, CALIBRATION_MIN_WIDTH)


def test_the_calibration_success_banner_uses_its_variant() -> None:
    from echo_personal_tool.application.localization import tr
    from echo_personal_tool.presentation.viewer.frame_overlay import CALIBRATION_SUCCESS_OVERLAY_KEY

    model = FrameOverlayModel()
    model.append(tr(CALIBRATION_SUCCESS_OVERLAY_KEY))
    assert model.is_calibration_success() is True
    assert model.style() == (CALIBRATION_SUCCESS_STYLE, CALIBRATION_MIN_WIDTH)


def test_a_transcript_line_after_the_banner_returns_to_the_default_style() -> None:
    from echo_personal_tool.application.localization import tr
    from echo_personal_tool.presentation.viewer.frame_overlay import CALIBRATION_PROMPT_OVERLAY_KEY

    model = FrameOverlayModel()
    model.append(tr(CALIBRATION_PROMPT_OVERLAY_KEY))
    model.append("LVEDD: 50.0 mm")
    assert model.is_calibration_prompt() is False
    assert model.style() == (DEFAULT_STYLE, 0)


def test_a_translated_banner_inside_a_transcript_is_not_a_banner() -> None:
    from echo_personal_tool.application.localization import tr
    from echo_personal_tool.presentation.viewer.frame_overlay import CALIBRATION_PROMPT_OVERLAY_KEY

    model = FrameOverlayModel()
    model.append("IVSd: 10.0 mm")
    model.append(tr(CALIBRATION_PROMPT_OVERLAY_KEY))
    assert model.is_calibration_prompt() is False
    assert model.style() == (DEFAULT_STYLE, 0)
