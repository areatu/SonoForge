"""Domain view of measurement panel 2.0 (TP-2 PR-1, spec 2026-10-15).

The panel draws what :func:`panel_view` returns and starts what
:func:`emitted_action` sends; the search ranking is what acceptance A-01 and
A-02 measure.  These tests do not need Qt.
"""

from __future__ import annotations

from echo_personal_tool.domain.measurement_catalog import CATALOG
from echo_personal_tool.domain.tool_layout_v3 import default_layout
from echo_personal_tool.domain.tool_panel_view import (
    FAVORITES_COUNT,
    PANEL_CONTEXTS,
    QUICK_COUNT,
    PanelSection,
    all_context_tools,
    default_favorites,
    default_quick,
    emitted_action,
    favorite_key,
    find_tool_for_action,
    panel_view,
    query_variants,
    search_tools,
    section_progress,
)


def _ids(tools) -> list[str]:
    return [tool.id for tool in tools]


def _search(query: str, context: str = "2d", *, doppler_mode: str | None = None):
    return search_tools(query, default_layout(), context, doppler_mode=doppler_mode, language="ru")


# ── Search (A-01, A-02) ────────────────────────────────────────────


def test_search_lvedd_finds_the_lv_linear_row() -> None:
    match = _search("lvedd")[0]
    assert match.tool.id == "lv.linear_ed"
    assert match.label == "КДР ЛЖ"
    assert match.matched_measurement == "lv.lvedd"
    assert match.score == 0


def test_search_ru_abbreviation_and_wrong_layout_find_the_same_row() -> None:
    """A-02: «кдр» and the QWERTY twin «rlh» both list «КДР ЛЖ» first."""
    for query in ("кдр", "rlh", "КДР", "lvedd"):
        match = _search(query)[0]
        assert (match.tool.id, match.label) == ("lv.linear_ed", "КДР ЛЖ"), query


def test_query_variants_transliterate_both_directions() -> None:
    assert "rlh" in query_variants("кдр")
    assert "кдр" in query_variants("rlh")
    assert query_variants("   ") == ()


def test_wrong_layout_does_not_match_long_english_names() -> None:
    """«rlh» is the RU layout of «кдр», not an abbreviation of a long name."""
    matches = _search("кдр", "doppler")
    assert all(match.tool.id != "mv.pht" for match in matches)


def test_search_reaches_pasp_through_the_tr_vmax_tool() -> None:
    """«Сист. ДЛА» has no own tool: its upstream step is TR Vmax (CW)."""
    for query in ("сдла", "pasp", "сист. дла"):
        match = _search(query, "doppler")[0]
        assert match.tool.id == "tr.vmax", query
        assert match.label == "Сист. ДЛА"
        assert match.matched_measurement == "pa.pasp"


def test_search_reaches_rvsp_synonym() -> None:
    match = _search("rvsp", "doppler")[0]
    assert (match.tool.id, match.label) == ("tr.vmax", "Сист. ДПЖ")
    assert match.matched_measurement == "rv.rvsp"


def test_search_respects_the_context() -> None:
    assert _search("сдла", "2d") == ()
    assert all(match.tool.id != "tr.vmax" for match in _search("vmax", "2d"))


def test_search_is_case_and_punctuation_insensitive() -> None:
    assert _search("  КДР  ")[0].tool.id == "lv.linear_ed"
    assert _search("сист. дла", "doppler")[0].label == "Сист. ДЛА"


def test_empty_search_returns_nothing() -> None:
    assert _search("") == ()
    assert _search("   ") == ()


# ── Panel view ─────────────────────────────────────────────────────


def test_two_d_context_has_quick_tiles_and_favourites() -> None:
    view = panel_view(default_layout(), "2d", language="ru")
    assert len(view.sections) == 12
    assert _ids(view.quick) == ["tool.caliper", "tool.area", "lv.linear_ed", "lv.edv_a4c"]
    assert _ids(view.favorites) == [
        "lv.linear_ed",
        "lv.lvesd",
        "lv.edv_a4c",
        "lv.esv_a4c",
        "la.lav_a4c",
        "av.d",
    ]
    assert len(view.quick) <= QUICK_COUNT
    assert len(view.favorites) <= FAVORITES_COUNT
    assert view.total_count == len(CATALOG)
    assert view.hidden_count == 50


def test_doppler_context_offers_only_doppler_tools() -> None:
    view = panel_view(default_layout(), "doppler", doppler_mode="cw", language="ru")
    assert [section.key for section in view.sections] == ["general", "mv_av", "tv_pv", "vessels"]
    assert _ids(view.quick) == ["av.vmax", "av.vti", "tr.vmax", "av.vti.auto"]
    assert _ids(view.favorites) == [
        "av.vmax",
        "av.vti",
        "tr.vmax",
        "mv.vmax",
        "mv.vti",
        "av.vti.auto",
    ]
    contexts = {"cw", "vessel"}
    for section in view.sections:
        for tool in section.items:
            assert tool.contexts & contexts, tool.id


def test_m_context_offers_only_mmode_tools() -> None:
    view = panel_view(default_layout(), "m", language="ru")
    assert len(view.sections) == 2
    assert _ids(view.quick) == ["mmode.caliper", "lv.linear_ed.m", "lv.lvesd.m", "mmode.time_hr"]
    assert _ids(view.favorites) == ["lv.linear_ed.m", "lv.lvesd.m", "mmode.caliper"]


def test_hidden_tools_can_be_shown_without_changing_the_count() -> None:
    hidden = panel_view(default_layout(), "m", language="ru")
    shown = panel_view(default_layout(), "m", language="ru", show_hidden=True)
    assert hidden.hidden_count == shown.hidden_count
    assert sum(len(section.items) for section in hidden.sections) < sum(
        len(section.items) for section in shown.sections
    )
    assert sum(len(section.items) for section in shown.sections) == len(CATALOG)


def test_defaults_for_modes_and_favourite_badges() -> None:
    assert default_quick("doppler", "pw") == ("mv.e", "mv.a", "mv.dt", "lvot.vti")
    assert default_favorites("doppler", "tdi") == ("tdi.e_sept", "tdi.e_lat", "rv.s_prime")
    assert favorite_key(0) == "1"
    assert favorite_key(8) == "9"
    assert favorite_key(9) == ""


def test_every_panel_context_is_readable() -> None:
    for context in PANEL_CONTEXTS:
        view = panel_view(default_layout(), context, language="en")
        assert view.context == context
        assert view.quick and view.favorites


# ── Activation payload (D-09) ──────────────────────────────────────


def test_emitted_action_precedence() -> None:
    payload = emitted_action(CATALOG["lv.linear_ed"])
    assert (payload.action, payload.view, payload.phase, payload.extra) == ("lv2d_all_diastole", "A4C", "ED", "")

    peak = emitted_action(CATALOG["mv.e"])
    assert (peak.action, peak.extra) == ("doppler_peak", "E")

    interval = emitted_action(CATALOG["mv.pht"])
    assert (interval.action, interval.extra) == ("doppler_interval", "MV PHT")

    trace = emitted_action(CATALOG["av.vti"])
    assert (trace.action, trace.extra) == ("doppler_trace", "AV VTI")

    auto_region = emitted_action(CATALOG["av.vti.auto"])
    assert (auto_region.action, auto_region.extra) == ("doppler_trace_auto_region", "AV VTI")

    caliper = emitted_action(CATALOG["rvot.d"])
    assert (caliper.action, caliper.extra) == ("caliper", "RVOTd")


def test_highlight_targets_follow_the_legacy_view_and_phase_rules() -> None:
    tools = all_context_tools(default_layout(), language="ru")
    assert find_tool_for_action(tools, "lv2d_es").id == "lv.lvesd"
    assert find_tool_for_action(tools, "manual_simpson", view="A4C", phase="ES").id == "lv.esv_a4c"
    assert find_tool_for_action(tools, "mbs_simpson", view="A4C", phase="ES").id == "lv.esv_a4c.auto"
    assert find_tool_for_action(tools, "lav_bi").id == "la.lav_a2c"
    assert find_tool_for_action(tools, "rv_fac", view="A4C", phase="ES").id == "rv.fac"
    assert find_tool_for_action(tools, "rv_fac", view="A2C") is None


def test_section_progress_counts_tools_with_results() -> None:
    view = panel_view(default_layout(), "2d", language="ru")
    section = next(block for block in view.sections if block.key == "lv")
    assert section_progress(section, {"lv.lvedd", "lv.lvesd"}) == (2, len(section.items))
    assert section_progress(section, set()) == (0, len(section.items))


def test_panel_section_is_frozen_and_ordered() -> None:
    section = PanelSection(key="lv", title="ЛЖ", items=tuple(CATALOG[key] for key in ("lv.linear_ed", "lv.lvesd")))
    assert _ids(section.items) == ["lv.linear_ed", "lv.lvesd"]
