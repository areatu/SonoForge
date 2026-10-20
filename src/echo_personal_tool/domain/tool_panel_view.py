"""View model of the measurement panel 2.0 (TP-2 PR-1, spec 2026-10-15 §4.2, §8.1).

The module is pure domain: no Qt and no infrastructure.  It answers the
questions the panel of TP-2 asks before it draws anything:

* which context is the panel in (2D / M / Doppler) and which tools belong to
  it;
* which sections, quick tiles and favourites the version-3 layout shows in
  that context;
* what a search query finds — by RU and EN labels, by synonyms and by a query
  typed in the wrong keyboard layout (``rlh`` → ``кдр``);
* what the panel emits for a tool (the same ``action / view / phase / extra``
  contract the Measures menu emits today, D-09).

Nothing here changes what the old panel shows: the version-3 layout is read
only when the experimental flag ``tool_panel_v2`` is on (TP-2 PR-1).

Search ranking (A-01, A-02): a query is normalised, transliterated from the
wrong layout, and compared against every label, synonym and measurement of a
tool.  A measurement hit (the row «КДР ЛЖ» of the LV linear sequence) beats a
tool hit, so ``lvedd`` lists «КДР ЛЖ» first; the row still activates the
catalog tool (the sequence), because that is the smallest action the scanner
offers for the measurement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from echo_personal_tool.domain.measurement_catalog import (
    CATALOG,
    CTX_2D,
    CTX_CW,
    CTX_M,
    CTX_PW,
    CTX_TDI,
    CTX_VESSEL,
    DOPPLER_CONTEXTS,
    FLAG_AI,
    MEASUREMENTS,
    SECTIONS,
    ToolSpec,
    tools_for_context,
)
from echo_personal_tool.domain.tool_layout_v3 import (
    CONTEXT_COMMON,
    CUSTOM_SECTION_PREFIX,
    Context,
    Layout,
    default_layout,
)

#: Values of the context segment «Авто / 2D / М / Допплер».
PANEL_CONTEXT_2D = "2d"
PANEL_CONTEXT_M = "m"
PANEL_CONTEXT_DOPPLER = "doppler"
PANEL_CONTEXT_AUTO = "auto"
PANEL_CONTEXTS: tuple[str, ...] = (
    PANEL_CONTEXT_2D,
    PANEL_CONTEXT_M,
    PANEL_CONTEXT_DOPPLER,
)

#: Doppler acquisition modes of the panel chip (lower case, catalog notation).
DOPPLER_MODES: tuple[str, ...] = (CTX_PW, CTX_CW, CTX_TDI)

#: How many quick tiles and favourites the panel shows (§4.2).
QUICK_COUNT = 4
FAVORITES_COUNT = 9

#: Search never returns more than this many rows.
SEARCH_LIMIT = 40


# ── Defaults per context ────────────────────────────────────────────

#: Measurements a tool produces through the domain's derived formulas rather
#: than as a direct caliper or trace result.  Search may show the derived
#: label (a clinician looks for «Сист. ДЛА», not for «Vmax ТР»), but
#: activation starts the upstream tool, because that is the step the scanner
#: can record.  TP-3 replaces this table with the protocol steps.
DERIVED_RESULTS: Mapping[str, tuple[str, ...]] = {
    "tr.pg": ("tr.vmax",),
    "pa.pasp": ("tr.vmax",),
    "rv.rvsp": ("tr.vmax",),
    "pa.mpap": ("tr.vmax",),
}


def derived_result_ids(tool_id: str) -> tuple[str, ...]:
    """Measurements the tool's result feeds after a domain calculation."""
    return tuple(measurement_id for measurement_id, sources in DERIVED_RESULTS.items() if tool_id in sources)


#: Quick tiles of a context when the layout does not override them.
DEFAULT_QUICK: Mapping[str, tuple[str, ...]] = {
    PANEL_CONTEXT_2D: ("tool.caliper", "tool.area", "lv.linear_ed", "lv.edv_a4c"),
    PANEL_CONTEXT_M: ("mmode.caliper", "lv.linear_ed.m", "lv.lvesd.m", "mmode.time_hr"),
    PANEL_CONTEXT_DOPPLER: ("mv.e", "mv.dt", "av.vti", "av.vti.auto"),
}

DEFAULT_QUICK_BY_MODE: Mapping[str, tuple[str, ...]] = {
    CTX_PW: ("mv.e", "mv.a", "mv.dt", "lvot.vti"),
    CTX_CW: ("av.vmax", "av.vti", "tr.vmax", "av.vti.auto"),
    CTX_TDI: ("tdi.e_sept", "tdi.e_lat", "rv.s_prime", "hr.doppler"),
}

#: Favourites of a context when the layout does not override them.
DEFAULT_FAVORITES: Mapping[str, tuple[str, ...]] = {
    PANEL_CONTEXT_2D: (
        "lv.linear_ed",
        "lv.lvesd",
        "lv.edv_a4c",
        "lv.esv_a4c",
        "la.lav_a4c",
        "av.d",
    ),
    PANEL_CONTEXT_M: ("lv.linear_ed.m", "lv.lvesd.m", "mmode.caliper"),
    PANEL_CONTEXT_DOPPLER: ("mv.e", "mv.a", "tdi.e_sept", "tdi.e_lat", "tr.vmax", "av.vti"),
}

DEFAULT_FAVORITES_BY_MODE: Mapping[str, tuple[str, ...]] = {
    CTX_PW: ("mv.e", "mv.a", "mv.dt", "lv.ivrt", "lvot.vmax", "lvot.vti"),
    CTX_CW: ("av.vmax", "av.vti", "tr.vmax", "mv.vmax", "mv.vti", "av.vti.auto"),
    CTX_TDI: ("tdi.e_sept", "tdi.e_lat", "rv.s_prime"),
}

#: Default sectors of the radial menu per context (TP-6, spec §4.4):
#: seven tools — the eighth slot of the wheel is the fixed «Ещё…» sector.
DEFAULT_RADIAL: Mapping[str, tuple[str, ...]] = {
    PANEL_CONTEXT_2D: (
        "tool.caliper",
        "tool.area",
        "tool.volume",
        "lv.linear_ed",
        "lv.edv_a4c",
        "lv.esv_a4c",
        "av.d",
    ),
    PANEL_CONTEXT_M: ("lv.linear_ed.m", "lv.lvesd.m", "mmode.caliper"),
    PANEL_CONTEXT_DOPPLER: ("mv.e", "mv.a", "av.vmax", "av.vti", "tr.vmax", "lvot.vti", "tdi.e_sept"),
}


# ── Records ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PanelSection:
    """One drawn section: a title and its tools in display order."""

    key: str
    title: str
    items: tuple[ToolSpec, ...]
    custom: bool = False


@dataclass(frozen=True)
class PanelView:
    """Everything the panel needs for one context and one layout."""

    context: str
    sections: tuple[PanelSection, ...]
    quick: tuple[ToolSpec, ...]
    favorites: tuple[ToolSpec, ...]
    hidden_count: int
    total_count: int


@dataclass(frozen=True)
class ToolMatch:
    """One search result: the tool to activate and the label to show."""

    tool: ToolSpec
    label: str
    score: int
    matched_measurement: str | None = None


@dataclass(frozen=True)
class EmittedAction:
    """The payload the panel emits for a tool (mirrors ``_MenuButton``)."""

    action: str
    view: str = "A4C"
    phase: str = "ED"
    extra: str = ""


# ── Normalisation ───────────────────────────────────────────────────


def normalize_panel_context(context: str | None) -> str:
    """A known panel context; anything else (and ``None``) reads as 2D."""
    value = (context or "").strip().lower()
    return value if value in PANEL_CONTEXTS else PANEL_CONTEXT_2D


def normalize_doppler_mode(mode: str | None) -> str:
    """A known Doppler mode in catalog notation (``pw``/``cw``/``tdi``) or ``""``."""
    value = (mode or "").strip().lower()
    return value if value in DOPPLER_MODES else ""


def context_catalog_contexts(context: str, doppler_mode: str | None = None) -> frozenset[str]:
    """Catalog contexts that belong to a panel context.

    The Doppler segment covers the spectral modes and the vessel tools.  An
    explicit mode (PW/CW/TDI) narrows the set to that mode, so the tools the
    scanner cannot run in the current mode are listed as hidden instead of
    being offered.
    """
    normalized = normalize_panel_context(context)
    if normalized == PANEL_CONTEXT_2D:
        return frozenset({CTX_2D})
    if normalized == PANEL_CONTEXT_M:
        return frozenset({CTX_M})
    mode = normalize_doppler_mode(doppler_mode)
    if mode:
        return frozenset({mode, CTX_VESSEL})
    return frozenset(DOPPLER_CONTEXTS | {CTX_VESSEL})


def panel_context_for_mode(mode: str | None) -> str:
    """Panel context of the viewer: ``m``, ``doppler``, otherwise 2D."""
    value = (mode or "").strip().lower()
    if value == PANEL_CONTEXT_M:
        return PANEL_CONTEXT_M
    if value == PANEL_CONTEXT_DOPPLER:
        return PANEL_CONTEXT_DOPPLER
    return PANEL_CONTEXT_2D


# ── Layout access ───────────────────────────────────────────────────


def resolve_layout_context(layout: Layout | None, context: str) -> Context | None:
    """The version-3 context that supplies sections to a panel context.

    A missing context inherits «Общий» (§8.3.5); a context marked
    ``inherit=True`` does the same.  A broken document falls back to the
    built-in layout instead of hiding every tool.
    """
    document = layout if layout is not None else default_layout()
    profile = document.profile()
    if profile is None:
        return default_layout().context(CONTEXT_COMMON)
    requested = profile.contexts.get(normalize_panel_context(context))
    if requested is not None and not requested.inherit:
        return requested
    common = profile.contexts.get(CONTEXT_COMMON)
    if common is not None:
        return common
    return default_layout().context(CONTEXT_COMMON)


def _flags_ok(flags: Iterable[str], preferences: Any | None, *, ai_available: bool) -> bool:
    """Whether a tool/section passes the build profile and the user flags."""
    for flag in flags:
        if flag.startswith("pref:"):
            if preferences is not None and not bool(getattr(preferences, flag[len("pref:") :], False)):
                return False
        elif flag in (FLAG_AI, "profile:full") and not ai_available:
            return False
    return True


def _section_title(section_key: str, title: str | None, language: str) -> str:
    spec = SECTIONS.get(section_key)
    if spec is not None:
        return spec.label(language).short
    return title or section_key


# ── Panel view ──────────────────────────────────────────────────────


def panel_view(
    layout: Layout | None,
    context: str,
    *,
    doppler_mode: str | None = None,
    language: str = "ru",
    preferences: Any | None = None,
    ai_available: bool = True,
    show_hidden: bool = False,
) -> PanelView:
    """Sections, quick tiles and favourites of one panel context.

    ``preferences`` only contributes the experimental flags of the catalog
    (``pref:show_strain``, ``pref:show_la_auto``); the layout contributes the
    order, visibility and user sections.  ``show_hidden`` renders the tools of
    the other contexts too — the «показать» action of the hidden line.
    """
    normalized = normalize_panel_context(context)
    catalog_contexts = context_catalog_contexts(normalized, doppler_mode)
    resolved = resolve_layout_context(layout, normalized)
    sections_in_layout = resolved.sections if resolved is not None else ()
    mode = normalize_doppler_mode(doppler_mode)

    sections: list[PanelSection] = []
    placed: set[str] = set()
    hidden_count = 0
    total_count = 0

    for block in sections_in_layout:
        if not block.visible:
            continue
        section_spec = SECTIONS.get(block.key)
        if section_spec is not None and not _flags_ok(section_spec.flags, preferences, ai_available=ai_available):
            continue
        items: list[ToolSpec] = []
        for item in block.items:
            if item.id in placed:
                continue
            tool = CATALOG.get(item.id)
            if tool is None:
                continue
            if not _flags_ok(tool.flags, preferences, ai_available=ai_available):
                continue
            placed.add(item.id)
            total_count += 1
            if not item.visible:
                if show_hidden:
                    items.append(tool)
                continue
            if tool.contexts & catalog_contexts:
                items.append(tool)
            else:
                hidden_count += 1
                if show_hidden:
                    items.append(tool)
        is_custom = block.key.startswith(CUSTOM_SECTION_PREFIX)
        if items or is_custom:
            sections.append(
                PanelSection(
                    key=block.key,
                    title=_section_title(block.key, block.title, language),
                    items=tuple(items),
                    custom=is_custom,
                )
            )

    quick = _resolve_ids(
        resolved.quick if resolved is not None and resolved.quick else default_quick(normalized, mode),
        catalog_contexts,
        language,
        preferences,
        ai_available=ai_available,
        limit=QUICK_COUNT,
    )
    favorites = _resolve_ids(
        resolved.favorites if resolved is not None and resolved.favorites else default_favorites(normalized, mode),
        catalog_contexts,
        language,
        preferences,
        ai_available=ai_available,
        limit=FAVORITES_COUNT,
    )
    return PanelView(
        context=normalized,
        sections=tuple(sections),
        quick=quick,
        favorites=favorites,
        hidden_count=hidden_count,
        total_count=total_count,
    )


def _resolve_ids(
    ids: Iterable[str],
    catalog_contexts: frozenset[str],
    language: str,
    preferences: Any | None,
    *,
    ai_available: bool,
    limit: int,
) -> tuple[ToolSpec, ...]:
    tools: list[ToolSpec] = []
    seen: set[str] = set()
    for tool_id in ids:
        if tool_id in seen:
            continue
        tool = CATALOG.get(tool_id)
        if tool is None or not (tool.contexts & catalog_contexts):
            continue
        if not _flags_ok(tool.flags, preferences, ai_available=ai_available):
            continue
        seen.add(tool_id)
        tools.append(tool)
        if len(tools) >= limit:
            break
    return tuple(tools)


def default_quick(context: str, doppler_mode: str | None = None) -> tuple[str, ...]:
    """Quick tiles of a context (mode-specific for Doppler)."""
    mode = normalize_doppler_mode(doppler_mode)
    if normalize_panel_context(context) == PANEL_CONTEXT_DOPPLER and mode:
        return DEFAULT_QUICK_BY_MODE.get(mode, DEFAULT_QUICK[PANEL_CONTEXT_DOPPLER])
    return DEFAULT_QUICK[normalize_panel_context(context)]


def default_favorites(context: str, doppler_mode: str | None = None) -> tuple[str, ...]:
    """Favourites of a context (mode-specific for Doppler)."""
    mode = normalize_doppler_mode(doppler_mode)
    if normalize_panel_context(context) == PANEL_CONTEXT_DOPPLER and mode:
        return DEFAULT_FAVORITES_BY_MODE.get(mode, DEFAULT_FAVORITES[PANEL_CONTEXT_DOPPLER])
    return DEFAULT_FAVORITES[normalize_panel_context(context)]


def default_radial(context: str) -> tuple[str, ...]:
    """Radial-menu sectors of a context when the profile does not override them."""
    return DEFAULT_RADIAL[normalize_panel_context(context)]


def favorite_key(index: int) -> str:
    """Keyboard badge of a favourite (1–9); empty outside the range."""
    return str(index + 1) if 0 <= index < FAVORITES_COUNT else ""


# ── Tool behaviour ──────────────────────────────────────────────────


def emitted_action(tool: ToolSpec) -> EmittedAction:
    """The ``action / view / phase / extra`` a tool sends when activated.

    This is the same precedence the Measures menu has used since Э2:
    a Doppler peak label, then an interval, then an auto-region trace, then a
    plain trace, then a caliper label, then the action itself (D-09).
    """
    payload = tool.payload
    if payload.doppler_peak:
        return EmittedAction("doppler_peak", payload.view, payload.phase, payload.doppler_peak)
    if payload.doppler_interval:
        return EmittedAction("doppler_interval", payload.view, payload.phase, payload.doppler_interval)
    if payload.action == "doppler_trace_auto_region" and payload.doppler_trace:
        return EmittedAction("doppler_trace_auto_region", payload.view, payload.phase, payload.doppler_trace)
    if payload.doppler_trace:
        return EmittedAction("doppler_trace", payload.view, payload.phase, payload.doppler_trace)
    if payload.caliper_label:
        return EmittedAction("caliper", payload.view, payload.phase, payload.caliper_label)
    return EmittedAction(payload.action or "caliper", payload.view, payload.phase, "")


def needs_doppler_time(tool: ToolSpec) -> bool:
    """Whether the tool needs the Doppler time scale (heart rate, VTI, DT)."""
    payload = tool.payload
    return bool(
        payload.doppler_interval
        or payload.doppler_trace
        or payload.action in {"doppler_mitral_inflow", "doppler_trace", "doppler_trace_auto_region"}
    )


def is_vessel_tool(tool: ToolSpec) -> bool:
    """Tools of the vessel workflow need a detected vessel cycle."""
    return bool(tool.payload.vessel)


def find_tool_for_action(
    tools: Iterable[ToolSpec], action: str, *, view: str = "A4C", phase: str = "ED"
) -> ToolSpec | None:
    """The tool a next-step highlight refers to (the old blink target).

    ``RV_FAC`` ignores the phase and matches on the view, exactly like the
    Measures menu; every other action matches view and phase.
    """
    from echo_personal_tool.domain.measurement_catalog import ToolKind

    for tool in tools:
        if tool.kind is ToolKind.ACTION and tool.payload.action != action:
            continue
        if tool.payload.action != action:
            continue
        if action == "rv_fac":
            if tool.payload.view == view:
                return tool
            continue
        if tool.payload.view == view and tool.payload.phase == phase:
            return tool
    return None


def all_context_tools(
    layout: Layout | None,
    *,
    language: str = "ru",
    preferences: Any | None = None,
    ai_available: bool = True,
) -> tuple[ToolSpec, ...]:
    """Visible tools of the layout regardless of context (search, hidden count)."""
    resolved = resolve_layout_context(layout, PANEL_CONTEXT_2D)
    if resolved is None:
        return ()
    tools: list[ToolSpec] = []
    seen: set[str] = set()
    for block in resolved.sections:
        if not block.visible:
            continue
        for item in block.items:
            if not item.visible or item.id in seen:
                continue
            tool = CATALOG.get(item.id)
            if tool is None or not _flags_ok(tool.flags, preferences, ai_available=ai_available):
                continue
            seen.add(item.id)
            tools.append(tool)
    return tuple(tools)


# ── Search ──────────────────────────────────────────────────────────

#: A physical QWERTY key typed while the RU layout is on: ``rlh`` → ``кдр``.
_EN_TO_RU = str.maketrans(
    {
        "q": "й",
        "w": "ц",
        "e": "у",
        "r": "к",
        "t": "е",
        "y": "н",
        "u": "г",
        "i": "ш",
        "o": "щ",
        "p": "з",
        "[": "х",
        "]": "ъ",
        "a": "ф",
        "s": "ы",
        "d": "в",
        "f": "а",
        "g": "п",
        "h": "р",
        "j": "о",
        "k": "л",
        "l": "д",
        ";": "ж",
        "'": "э",
        "z": "я",
        "x": "ч",
        "c": "с",
        "v": "м",
        "b": "и",
        "n": "т",
        "m": "ь",
        ",": "б",
        ".": "ю",
        "/": ".",
        "`": "ё",
    }
)
_RU_TO_EN = str.maketrans({value: key for key, value in _EN_TO_RU.items() if len(value) == 1})
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_PUNCT_RE = re.compile(r"[^\w\s′]+", re.UNICODE)


def _normalize_text(text: str) -> str:
    value = (text or "").casefold().replace("ё", "е").replace("’", "'")
    value = _PUNCT_RE.sub(" ", value)
    return " ".join(value.split())


def query_variants(query: str) -> tuple[str, ...]:
    """The query itself plus its RU↔EN mis-layout twins (A-02)."""
    base = _normalize_text(query)
    if not base:
        return ()
    variants = [base]
    if _LATIN_RE.search(base):
        transliterated = _normalize_text(base.translate(_EN_TO_RU))
        if transliterated and transliterated not in variants:
            variants.append(transliterated)
    if _CYRILLIC_RE.search(base):
        transliterated = _normalize_text(base.translate(_RU_TO_EN))
        if transliterated and transliterated not in variants:
            variants.append(transliterated)
    return tuple(variants)


def _subsequence(needle: str, haystack: str) -> bool:
    iterator = iter(haystack)
    return all(char in iterator for char in needle)


def _score_text(text: str, query: str) -> int | None:
    """Score of one candidate string; lower is better, ``None`` is no match."""
    haystack = _normalize_text(text)
    if not haystack:
        return None
    if haystack == query:
        return 0
    if haystack.startswith(query):
        return 10
    if any(word.startswith(query) for word in haystack.split()):
        return 20
    if query in haystack:
        return 30
    # Subsequence matching finds abbreviations («кдр» in «КДР ЛЖ»), but on a
    # long full name it matches almost anything: «rlh» must not list
    # «Mitral pressure half-time» for a query typed in the wrong layout.
    if len(query) >= 2 and " " not in query and len(haystack) <= 24 and _subsequence(query, haystack):
        return 40
    return None


def _measurement_fields(measurement_id: str) -> tuple[str, ...]:
    spec = MEASUREMENTS.get(measurement_id)
    if spec is None:
        return ()
    fields: list[str] = []
    for language in ("ru", "en"):
        label = spec.label(language)
        fields.extend((label.short, label.full))
    fields.extend(spec.synonyms)
    return tuple(fields)


def _tool_fields(tool: ToolSpec) -> tuple[str, ...]:
    fields: list[str] = []
    for language in ("ru", "en"):
        label = tool.label(language)
        fields.extend((label.short, label.full))
    fields.extend(tool.synonyms)
    section = SECTIONS.get(tool.section)
    if section is not None:
        for language in ("ru", "en"):
            fields.append(section.label(language).short)
    return tuple(fields)


def _best_match(tool: ToolSpec, variants: Iterable[str], language: str) -> ToolMatch | None:
    best: ToolMatch | None = None
    # A measurement hit wins over a tool hit: the row can carry the specific
    # label («КДР ЛЖ»), while the emitted action stays the catalog tool.
    for result_id in (*tool.result_keys, *derived_result_ids(tool.id)):
        for field in _measurement_fields(result_id):
            for query in variants:
                score = _score_text(field, query)
                if score is None:
                    continue
                candidate = ToolMatch(
                    tool=tool,
                    label=MEASUREMENTS[result_id].label(language).short,
                    score=score,
                    matched_measurement=result_id,
                )
                if best is None or candidate.score < best.score:
                    best = candidate
    for field in _tool_fields(tool):
        for query in variants:
            score = _score_text(field, query)
            if score is None:
                continue
            candidate = ToolMatch(tool=tool, label=tool.label(language).short, score=score + 5)
            if best is None or candidate.score < best.score:
                best = candidate
    return best


def search_tools(
    query: str,
    layout: Layout | None = None,
    context: str = PANEL_CONTEXT_2D,
    *,
    doppler_mode: str | None = None,
    language: str = "ru",
    preferences: Any | None = None,
    ai_available: bool = True,
    limit: int = SEARCH_LIMIT,
) -> tuple[ToolMatch, ...]:
    """Ranked tools of the current context for a search query.

    Searches RU and EN labels, synonyms, measurement labels and the old
    labels kept as synonyms.  A query typed in the wrong layout is matched
    through its transliteration (A-02).  Only tools the current context can
    run are returned; the panel does not offer a CW trace on a PW clip.
    """
    variants = query_variants(query)
    if not variants:
        return ()
    catalog_contexts = context_catalog_contexts(context, doppler_mode)
    candidates = [
        tool
        for tool in tools_for_context(next(iter(sorted(catalog_contexts))))
        if tool.contexts & catalog_contexts and _flags_ok(tool.flags, preferences, ai_available=ai_available)
    ]
    # Vessel tools are not reachable from every catalog context: take the
    # union explicitly instead of relying on one representative.
    if len(catalog_contexts) > 1:
        candidates = [
            tool
            for tool in CATALOG.values()
            if tool.contexts & catalog_contexts and _flags_ok(tool.flags, preferences, ai_available=ai_available)
        ]
    matches: list[ToolMatch] = []
    for tool in candidates:
        match = _best_match(tool, variants, language)
        if match is not None:
            matches.append(match)
    matches.sort(key=lambda item: (item.score, item.tool.id))
    return tuple(matches[:limit])


# ── Section progress (TP-2 PR-2 wires the status provider) ──────────


def section_progress(section: PanelSection, completed: Iterable[str]) -> tuple[int, int]:
    """How many tools of a section already produced a result."""
    done = set(completed)
    total = len(section.items)
    return sum(1 for tool in section.items if any(key in done for key in tool.result_keys)), total
