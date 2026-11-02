"""Measurement tool catalog (TP-0 PR-1, spec 2026-10-15 §5, §8.1, A-12).

The catalog must mirror the Measures menu one-to-one until TP-2 renders the
panel from it: every ``_MENU`` button maps to exactly one catalog tool through
its layout-v2 ``tool_id`` and the payloads are identical.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain import measurement_catalog as cat
from echo_personal_tool.domain.measurement_catalog import (
    CATALOG,
    DEFAULT_LINEAR_UNIT,
    LEGACY_ALIASES,
    MEASUREMENTS,
    SECTIONS,
    Quantity,
    ToolKind,
    display_unit,
    en_label_violations,
    ru_label_violations,
)


def _menu():
    from echo_personal_tool.presentation.measures_menu import _MENU

    return _MENU


def _menu_buttons():
    return [(group, button) for group, buttons in _menu() for button in buttons]


# ── Structure ───────────────────────────────────────────────────────


def test_catalog_is_consistent() -> None:
    assert cat.validate_catalog() == []


def test_ids_are_unique_and_well_formed() -> None:
    ids = [tool.id for tool in cat._TOOL_LIST]
    assert len(ids) == len(set(ids))
    for tool_id in [*ids, *MEASUREMENTS]:
        assert tool_id == tool_id.lower(), tool_id
        assert " " not in tool_id and "|" not in tool_id, tool_id
        assert "." in tool_id or tool_id == "hr", tool_id


def test_single_result_tool_shares_id_with_its_measurement() -> None:
    """Shared namespace (spec §8.1): a measuring tool named like a result produces it."""
    for tool in CATALOG.values():
        if tool.id in MEASUREMENTS:
            assert tool.result_keys == (tool.id,), tool.id


def test_auto_variants_point_to_the_manual_result() -> None:
    for tool in CATALOG.values():
        if tool.id.endswith((".auto", ".ai_plus")):
            base = tool.id.rsplit(".", 1)[0]
            assert tool.result_keys == (base,), tool.id
            assert tool.kind is ToolKind.AUTO


def test_measuring_tools_declare_requirements() -> None:
    for tool in CATALOG.values():
        if tool.kind is ToolKind.ACTION:
            continue
        assert tool.requires, tool.id
        if tool.contexts & cat.DOPPLER_CONTEXTS or tool.contexts == {cat.CTX_VESSEL}:
            assert cat.REQ_DOPPLER in tool.requires, tool.id


def test_doppler_velocity_results_match_tool_context() -> None:
    for tool in CATALOG.values():
        for key in tool.result_keys:
            spec = MEASUREMENTS[key]
            if spec.quantity is Quantity.VELOCITY and tool.contexts & cat.DOPPLER_CONTEXTS:
                assert spec.doppler_mode in tool.contexts, (tool.id, key)


def test_only_caliper_has_a_default_key() -> None:
    """Today's only panel shortcut (keyboard_shortcuts: caliper "L"); TP-4 adds the rest."""
    keys = {tool.id: tool.default_key for tool in CATALOG.values() if tool.default_key}
    assert keys == {"tool.caliper": "L"}


# ── Mirror of the Measures menu ────────────────────────────────────


def test_every_menu_button_has_a_catalog_alias() -> None:
    buttons = _menu_buttons()
    assert len(buttons) == len(CATALOG) == 94
    missing = [button.tool_id for _, button in buttons if button.tool_id not in LEGACY_ALIASES]
    assert missing == []
    assert {LEGACY_ALIASES[button.tool_id] for _, button in buttons} == set(CATALOG)


def test_payload_section_and_label_key_mirror_the_menu() -> None:
    for group, button in _menu_buttons():
        tool = CATALOG[LEGACY_ALIASES[button.tool_id]]
        payload = tool.payload
        assert payload.legacy_id == button.tool_id
        assert payload.action == (None if button.action is None else str(button.action)), tool.id
        assert (payload.view, payload.phase) == (button.view, button.phase), tool.id
        assert payload.caliper_label == button.caliper_label, tool.id
        assert payload.doppler_peak == button.doppler_peak, tool.id
        assert payload.doppler_interval == button.doppler_interval, tool.id
        assert payload.doppler_trace == button.doppler_trace, tool.id
        assert payload.vessel == button.vessel, tool.id
        assert tool.label_key == button.label_key, tool.id
        assert SECTIONS[tool.section].legacy_key == group, tool.id


def test_default_order_within_sections_matches_menu() -> None:
    for group, buttons in _menu():
        section = cat.SECTION_BY_LEGACY_KEY[group]
        expected = [LEGACY_ALIASES[button.tool_id] for button in buttons]
        assert [tool.id for tool in cat.tools_in_section(section)] == expected, group


def test_section_order_matches_menu() -> None:
    assert [section.legacy_key for section in SECTIONS.values()] == [group for group, _ in _menu()]


def test_actions_exist_in_measurement_action_enum() -> None:
    from echo_personal_tool.presentation.measurement_action import MeasurementAction

    values = {str(action) for action in MeasurementAction}
    for tool in CATALOG.values():
        if tool.payload.action is not None:
            assert tool.payload.action in values, tool.id


def test_profile_flags_mirror_menu_filters() -> None:
    from echo_personal_tool.presentation import measures_menu

    ai_actions = {tool.payload.action for tool in CATALOG.values() if cat.FLAG_AI in tool.flags}
    assert ai_actions == set(measures_menu._AI_ONNX_ACTIONS)
    la_auto = {tool.payload.action for tool in CATALOG.values() if "pref:show_la_auto" in tool.flags}
    assert la_auto == {action for action, pref in measures_menu._EXPERIMENTAL_BUTTONS.items() if pref == "show_la_auto"}
    for group, pref in measures_menu._EXPERIMENTAL_GROUPS.items():
        section = SECTIONS[cat.SECTION_BY_LEGACY_KEY[group]]
        assert f"pref:{pref}" in section.flags
        assert all(f"pref:{pref}" in tool.flags for tool in cat.tools_in_section(section.id))


def test_legacy_alias_lookup() -> None:
    assert cat.catalog_id_for_legacy("caliper|A4C|ED||||") == "tool.caliper"
    assert cat.catalog_id_for_legacy("manual_simpson|A2C|ES||||") == "lv.esv_a2c"
    assert cat.catalog_id_for_legacy("mbs_simpson|A4C|ED||||") == "lv.edv_a4c.auto"
    assert cat.catalog_id_for_legacy("None|A4C|ED|RVOTd|||") == "rvot.d"
    assert cat.catalog_id_for_legacy("None|A4C|ED|RVOT|||") == "rv.rvot_prox"
    assert cat.catalog_id_for_legacy("doppler_trace_auto_region|A4C|ED||||AV VTI") == "av.vti.auto"
    assert cat.catalog_id_for_legacy("unknown|A4C|ED||||") is None


def test_old_menu_labels_stay_searchable() -> None:
    """Risk «врачи привыкли к старым подписям» (spec §12): old labels are synonyms."""
    from echo_personal_tool.infrastructure.i18n import tr_for_language

    for _, button in _menu_buttons():
        tool = CATALOG[LEGACY_ALIASES[button.tool_id]]
        known = {s.casefold() for s in tool.synonyms}
        for key in tool.result_keys:
            known |= {s.casefold() for s in MEASUREMENTS[key].synonyms}
        for language in cat.LANGUAGES:
            known |= {tool.label(language).short.casefold(), tool.label(language).full.casefold()}
        for language in cat.LANGUAGES:
            old = tr_for_language(button.label_key, language).strip()
            assert old.casefold() in known, (tool.id, language, old)


# ── Labels (D-02, A-12, Q-03) ──────────────────────────────────────


def _all_labels():
    for collection in (CATALOG, MEASUREMENTS, SECTIONS):
        for item in collection.values():
            for language in cat.LANGUAGES:
                label = item.labels[language]
                yield item.id, language, label.short
                yield item.id, language, label.full


def test_every_item_has_ru_and_en_labels() -> None:
    for item_id, _, text in _all_labels():
        assert text.strip() == text and text, item_id


def test_ru_labels_have_no_latin_outside_allowlist() -> None:
    bad = [(item_id, text, ru_label_violations(text)) for item_id, lang, text in _all_labels() if lang == "ru"]
    assert [entry for entry in bad if entry[2]] == []


def test_en_labels_have_no_cyrillic() -> None:
    bad = [(item_id, text) for item_id, lang, text in _all_labels() if lang == "en" and en_label_violations(text)]
    assert bad == []


def test_no_bracketed_translations() -> None:
    """D-02: one language per label — no «КДО (EDV)»."""
    for item_id, language, text in _all_labels():
        if "(" in text:
            inner = text[text.index("(") + 1 : text.index(")")]
            if language == "ru":
                assert ru_label_violations(inner) == [], (item_id, text)
            else:
                assert en_label_violations(inner) == [], (item_id, text)


def test_ru_violation_detector() -> None:
    assert ru_label_violations("КДО (EDV)") == ["EDV"]
    assert ru_label_violations("Vmax АК") == []
    assert ru_label_violations("E/e′ ср.") == []
    assert ru_label_violations("dP/dt ЛЖ (Δt 1→3 м/с)") == []
    assert ru_label_violations("LVOT VTI") == ["LVOT"]


@pytest.mark.parametrize(
    ("measurement_id", "ru_short"),
    [
        ("lv.edv_bp", "КДО ЛЖ Биплан"),  # Q-03: «Биплан», not «бипланово»
        ("lv.ef_bp", "ФВ ЛЖ Биплан"),
        ("la.lav_bp", "ОЛП Биплан"),
        ("lv.edvi", "иКДО"),  # indexed: lower-case «и» prefix
        ("lv.esvi", "иКСО"),
        ("la.lavi", "иОЛП"),
        ("lv.svi", "иУО"),
        ("lv.mass_i", "иММЛЖ"),
        ("pa.pasp", "Сист. ДЛА"),
        ("mv.dt", "DT"),  # DT, IVRT, VTI, DVI are not translated
        ("lv.ivrt", "IVRT"),
        ("av.vti", "VTI АК"),
        ("lvot.vti", "VTI ВТЛЖ"),
        ("av.dvi", "DVI"),
        ("mv.pht", "ВПД МК"),
    ],
)
def test_ru_label_decisions(measurement_id: str, ru_short: str) -> None:
    assert MEASUREMENTS[measurement_id].label("ru").short == ru_short


def test_biplane_wording() -> None:
    for item_id, language, text in _all_labels():
        if language == "ru":
            assert "бипланово" not in text.lower(), item_id


def test_indexed_measurements_use_prefix() -> None:
    for spec in MEASUREMENTS.values():
        if spec.indexed:
            assert spec.label("ru").short.startswith("и"), spec.id
            assert spec.quantity.value.startswith("indexed_"), spec.id


def test_label_language_fallback() -> None:
    assert MEASUREMENTS["lv.lvedd"].label("ru_RU").short == "КДР ЛЖ"
    assert MEASUREMENTS["lv.lvedd"].label("de").short == "LVEDD"


# ── Units (Q-01, Q-02) ─────────────────────────────────────────────


def test_linear_dimensions_default_to_mm() -> None:
    assert DEFAULT_LINEAR_UNIT == "mm"
    assert MEASUREMENTS["lv.lvedd"].unit() == "mm"
    assert MEASUREMENTS["lv.lvedd"].unit(linear_unit="cm") == "cm"
    assert MEASUREMENTS["lv.lvedd"].decimals_for("mm") == 0
    assert MEASUREMENTS["lv.lvedd"].decimals_for("cm") == 1
    with pytest.raises(ValueError):
        display_unit(Quantity.LENGTH, linear_unit="in")


def test_orifice_diameters_and_vti_stay_in_cm() -> None:
    """Area formulas (π·(d/2)², SV = CSA·VTI) work in cm — calculators use cm too."""
    for measurement_id in ("lvot.d", "rvot.d", "mv.d", "mr.pisa_r", "av.vti", "lvot.vti"):
        spec = MEASUREMENTS[measurement_id]
        assert spec.unit() == "cm" == spec.unit(linear_unit="mm"), measurement_id


@pytest.mark.parametrize(
    ("measurement_id", "unit"),
    [
        ("av.vmax", "m/s"),  # CW
        ("tr.vmax", "m/s"),
        ("mr.vmax", "m/s"),
        ("mv.e", "cm/s"),  # PW
        ("lvot.vmax", "cm/s"),
        ("rvot.vmax", "cm/s"),
        ("tdi.e_sept", "cm/s"),  # TDI
        ("rv.s_prime", "cm/s"),
    ],
)
def test_velocity_units_follow_doppler_mode(measurement_id: str, unit: str) -> None:
    assert MEASUREMENTS[measurement_id].unit() == unit


def test_velocity_unit_follows_actual_mode() -> None:
    """A PW-default site measured with CW is shown in m/s (D-17)."""
    assert MEASUREMENTS["lvot.vmax"].unit(doppler_mode="cw") == "m/s"
    assert MEASUREMENTS["av.vmax"].unit(doppler_mode="pw") == "cm/s"
    assert cat.velocity_unit_for_mode(None) == "cm/s"


def test_velocity_units_agree_with_doppler_catalog() -> None:
    from echo_personal_tool.domain.doppler_catalog import velocity_display_unit

    for mode in ("cw", "pw", "tdi"):
        assert display_unit(Quantity.VELOCITY, doppler_mode=mode) == velocity_display_unit(mode)


def test_every_velocity_has_an_expected_mode() -> None:
    for spec in MEASUREMENTS.values():
        if spec.quantity is Quantity.VELOCITY:
            assert spec.doppler_mode in {"cw", "pw", "tdi"}, spec.id


def test_tools_for_context() -> None:
    cw = {tool.id for tool in cat.tools_for_context("cw")}
    assert {"av.vmax", "tr.vmax", "hr.doppler"} <= cw
    assert "tool.caliper" not in cw
    assert "lv.linear_ed.m" in {tool.id for tool in cat.tools_for_context("m")}
    with pytest.raises(ValueError):
        cat.tools_for_context("3d")
