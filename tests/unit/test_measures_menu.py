"""Measures tab accordion menu layout."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication, QPushButton

from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget


def test_lv_auto_has_no_biplane_buttons(_qapp) -> None:
    menu = MeasuresMenuWidget()
    biplane = [child for child in menu.findChildren(QPushButton) if child.text().startswith("Simpson 2C")]
    assert len(biplane) == 2
    assert all(button.isEnabled() for button in biplane)


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_user_section_shows_its_title_and_saved_position() -> None:
    import copy

    from echo_personal_tool.infrastructure.user_preferences import default_user_preferences
    from echo_personal_tool.presentation.measures_menu import default_tool_layout, encode_tool_layout

    layout = copy.deepcopy(default_tool_layout())
    layout.insert(2, {"key": "custom:mine", "title": "Мои & я", "items": []})
    preferences = default_user_preferences()
    preferences.show_strain = True  # experimental section is hidden by default
    preferences.tool_panel_layout_json = encode_tool_layout(layout)

    menu = MeasuresMenuWidget()
    menu.set_preferences(preferences)

    keys = [section._title_key for section in menu._sections]
    layout_keys = [entry["key"] for entry in layout]
    # The study profile hides the sections of the other studies; the visible
    # ones keep the saved order.
    assert keys == [key for key in layout_keys if key in set(keys)]
    user_section = menu._sections[2]
    assert user_section._header.text() == "Мои && я"  # "&" is escaped for Qt mnemonics
    assert user_section._custom_title == "Мои & я"


def test_builtin_section_title_comes_from_translations() -> None:
    from echo_personal_tool.infrastructure.i18n import tr

    menu = MeasuresMenuWidget()
    general = next(section for section in menu._sections if section._title_key == "menu.general")

    assert general._custom_title is None
    assert general._header.text() == tr("menu.general")


def test_general_doppler_heart_rate_routes_time_interval_and_requires_time(qtbot) -> None:
    from echo_personal_tool.infrastructure.i18n import tr
    from echo_personal_tool.presentation.measurement_action import MeasurementAction

    menu = MeasuresMenuWidget()
    qtbot.addWidget(menu)
    general = next(section for section in menu._sections if section._title_key == "menu.general")
    button = next(child for child in general.findChildren(QPushButton) if child.text() == tr("menu.doppler_heart_rate"))

    menu.set_doppler_tool_availability(time_ok=False)
    assert not button.isEnabled()
    menu.set_doppler_tool_availability(time_ok=True, vessel_ok=False)
    assert button.isEnabled()
    with qtbot.waitSignal(menu.action_requested) as signal:
        button.click()
    assert signal.args == [MeasurementAction.DOPPLER_INTERVAL, "A4C", "ED", "RR"]
    # The existing cine auto-HR tool is a separate action.
    assert any(spec.action == MeasurementAction.HEART_RATE for _, spec in menu._tool_buttons)


def _menu_keys(profile_id: str) -> set[str]:
    """Label keys of the buttons the study profile leaves in the menu."""
    from echo_personal_tool.infrastructure.user_preferences import default_user_preferences
    from echo_personal_tool.presentation.measures_menu import build_measure_menu

    preferences = default_user_preferences()
    preferences.study_profile = profile_id
    return {spec.label_key for _group, specs in build_measure_menu(preferences) for spec in specs}


def test_the_renal_menu_carries_both_kidneys_and_the_bladder() -> None:
    """Item 11: every size the owner listed has its own button."""
    from echo_personal_tool.domain.study_profiles import STUDY_PROFILE_KIDNEY

    keys = _menu_keys(STUDY_PROFILE_KIDNEY)
    for key in (
        "menu.kidney_r_length",
        "menu.kidney_r_width",
        "menu.kidney_r_thickness",
        "menu.kidney_r_parenchyma",
        "menu.kidney_r_sinus",
        "menu.vessel_renal_right",
        "menu.kidney_l_length",
        "menu.kidney_l_width",
        "menu.kidney_l_thickness",
        "menu.kidney_l_parenchyma",
        "menu.kidney_l_sinus",
        "menu.vessel_renal_left",
        "menu.bladder_length",
        "menu.bladder_width",
        "menu.bladder_depth",
        "menu.bladder_wall",
    ):
        assert key in keys, key
    # «Высота» is the old name of the third bladder size: the profile shows
    # «глубина» and must not offer both.
    assert "menu.bladder_height" not in keys


def test_the_abdominal_and_thyroid_menus_offer_their_measurements() -> None:
    from echo_personal_tool.domain.study_profiles import STUDY_PROFILE_ABDOMEN, STUDY_PROFILE_THYROID

    abdomen = _menu_keys(STUDY_PROFILE_ABDOMEN)
    for key in (
        "menu.liver_llt",
        "menu.liver_rlt",
        "menu.liver_kvr",
        "menu.gb_length",
        "menu.gb_width",
        "menu.gb_wall",
        "menu.portal_vein",
        "menu.bile_duct",
        "menu.pancreas_head",
        "menu.pancreas_body",
        "menu.pancreas_tail",
        "menu.pancreas_duct",
        "menu.abd_aorta",
    ):
        assert key in abdomen, key

    thyroid = _menu_keys(STUDY_PROFILE_THYROID)
    for key in (
        "menu.thyroid_r_thick",
        "menu.thyroid_r_width",
        "menu.thyroid_r_height",
        "menu.thyroid_l_thick",
        "menu.thyroid_l_width",
        "menu.thyroid_l_height",
        "menu.thyroid_isthmus",
    ):
        assert key in thyroid, key


def test_the_organ_volume_button_belongs_to_the_organ_studies_only() -> None:
    """«Объём по трём измерениям» is ordinary-ultrasound volumetry.

    Echocardiography and the vascular study keep their own volume tools; the
    extra button would be one of the «лишние кнопки» the owner complained about.
    """
    from echo_personal_tool.domain.study_profiles import (
        STUDY_PROFILE_ABDOMEN,
        STUDY_PROFILE_ECHO,
        STUDY_PROFILE_KIDNEY,
        STUDY_PROFILE_THYROID,
        STUDY_PROFILE_VASCULAR,
    )

    for profile_id in (STUDY_PROFILE_ABDOMEN, STUDY_PROFILE_KIDNEY, STUDY_PROFILE_THYROID):
        assert "menu.organ_volume" in _menu_keys(profile_id), profile_id
    for profile_id in (STUDY_PROFILE_ECHO, STUDY_PROFILE_VASCULAR):
        assert "menu.organ_volume" not in _menu_keys(profile_id), profile_id
