"""The one list of tool buttons the row and the rail are built from (UI-2 PR-3).

Spec: ``docs/superpowers/specs/2026-10-16-ui-redesign-spec-plan-ru.md`` §4.1
(the 42 px row and the 70 px rail), §4.2 (the row composition), §9 (the new
package).  D-09 of the tool-panel spec: every button, whichever view draws it,
ends in one entry point of the window.

The module is Qt-free so the table can be tested without a widget:

* :data:`TOOL_BUTTONS` is the display order — the composition of §4.2, cut down
  to what the application can actually do today.  «Указатель», «сдвиг»,
  «яркость», «поворот» and «Фокус» are deliberately absent: the viewer has no
  such modes yet (they arrive with ``ToolInteractionController``, QH-3, and the
  focus mode with UI-6), and a button that cannot do anything is worse than no
  button.  «Сравнить» is not repeated here either — the switch lives in the
  title bar (UI-1).
* a measurement button is an entry of the tool catalog (``source="catalog"``),
  so its caption, its availability in the current context and its payload come
  from the catalog rather than from a copy of it (UD-15: the caption of a
  catalog tool is the menu key the catalog already names);
* a mode button is an entry of the shortcut registry (``source="shortcut"``),
  so its key badge and its tooltip are read from the registry and pressing it
  calls the handler the key itself calls;
* :func:`unavailable_reason` is why a button is dimmed (D-08: the reason is a
  tooltip, not a silent no-op).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from echo_personal_tool.application.localization import tr_for_language
from echo_personal_tool.domain.measurement_catalog import CATALOG, ToolSpec
from echo_personal_tool.domain.tool_panel_view import (
    EmittedAction,
    context_catalog_contexts,
    emitted_action,
    normalize_doppler_mode,
    normalize_panel_context,
)
from echo_personal_tool.keyboard_shortcuts import append_shortcut_hint, get_shortcut

#: Left group: the measurement tools of §4.2.
GROUP_MEASURE: Final = "measure"
#: The auto-contour button, separated from the manual tools.
GROUP_AUTO: Final = "auto"
#: The manual-caliper / calibration group (§4.5: the chip lives in the corner).
GROUP_CALIBRATION: Final = "calibration"
#: Right-aligned group (§4.2: «масштаб», …).
GROUP_VIEW: Final = "view"

#: ``ToolButtonSpec.source`` values, i.e. which table a button is resolved in.
SOURCE_CATALOG: Final = "catalog"
SOURCE_SHORTCUT: Final = "shortcut"


@dataclass(frozen=True)
class ToolButtonSpec:
    """One button of the row / the rail.

    ``ref`` names the entry the button borrows everything from: a tool id of
    :data:`~echo_personal_tool.domain.measurement_catalog.CATALOG` or a
    shortcut id of the registry.  ``id`` is the stable identity the widget
    reports in :attr:`ToolButtonSignals.action_requested`, so a later move of a
    button inside the table does not change what the window listens for.
    """

    id: str
    source: str
    ref: str
    group: str = GROUP_MEASURE
    #: Caption key for buttons that are not catalog tools; a catalog tool reads
    #: its caption from ``ToolSpec.label_key`` instead.
    label_key: str = ""
    #: ``resources/icons/<icon>.svg``; an icon the theme has no glyph for leaves
    #: the button on its caption (§4.1: the row is icons, the rail is icon + text).
    icon: str = ""
    #: A thin separator before this button (the groups of §4.2).
    separated: bool = False

    @property
    def shortcut_id(self) -> str:
        """The registry id whose key the button shows, when there is one.

        A mode button *is* its shortcut; a catalog tool has no registry id of
        its own, so its badge comes from :attr:`ToolSpec.default_key`.
        """
        return self.ref if self.source == SOURCE_SHORTCUT else ""

    @property
    def checkable(self) -> bool:
        """A mode button stays pressed while the mode is armed (D-08).

        Every mode button is checkable: the window reports the armed tool through
        :meth:`ToolButtonsBase.set_active`, and the pressed look is the only
        feedback a hotkey press gets (item 3 of the 2026-10-23 acceptance list:
        «при нажатии на соответствующие клавиши кнопки не выделяются»).
        """
        return True


@dataclass(frozen=True)
class ToolButtonState:
    """What the window knows about the current frame; drives dimming.

    Deliberately a value object rather than a query: the widgets must not reach
    into the viewer, and :meth:`unavailable_reason` stays testable.
    """

    has_clip: bool = False
    multiview: bool = False
    #: Panel context of the current clip (``2d`` / ``doppler``).  M-mode keeps the
    #: 2D tools: §4.4 gives the row the same composition there while the trace
    #: gets its own strip (UI-3), so a mode the catalog does not describe must not
    #: dim the whole row into a dead strip.
    context: str = "2d"
    doppler_mode: str | None = None


TOOL_BUTTON_STATE_EMPTY: Final = ToolButtonState()


#: The row / the rail, in display order (§4.2).
TOOL_BUTTONS: Final[tuple[ToolButtonSpec, ...]] = (
    ToolButtonSpec("caliper", SOURCE_CATALOG, "tool.caliper", icon="activity_caliper"),
    ToolButtonSpec("spline_area", SOURCE_CATALOG, "tool.area", icon="activity_area"),
    ToolButtonSpec("spline_volume", SOURCE_CATALOG, "tool.volume", icon="activity_lv2d"),
    ToolButtonSpec(
        # Same General tools as the panel rows, but armed in freehand mode
        # (2026-10-25: replaced the Contour / Model pair on user request).
        "freehand_area",
        SOURCE_CATALOG,
        "tool.area",
        label_key="toolbtn.freehand_area",
        icon="activity_contour",
        separated=True,
    ),
    ToolButtonSpec(
        "freehand_volume",
        SOURCE_CATALOG,
        "tool.volume",
        label_key="toolbtn.freehand_volume",
        icon="activity_model",
    ),
    ToolButtonSpec("vti_trace", SOURCE_SHORTCUT, "vti_trace", label_key="toolbtn.vti_trace", icon="show_chart"),
    ToolButtonSpec(
        "doppler_interval",
        SOURCE_SHORTCUT,
        "doppler_interval",
        label_key="toolbtn.doppler_interval",
        icon="activity_doppler_interval",
    ),
    ToolButtonSpec(
        "auto_segment",
        SOURCE_SHORTCUT,
        "auto_segment",
        group=GROUP_AUTO,
        label_key="toolbtn.auto_segment",
        icon="activity_auto_s",
        separated=True,
    ),
    ToolButtonSpec(
        # «D/S маркеры» (2026-10-27 UI list, item 6): the physician can ask for
        # ED/ES detection on the current echo clip even when the DICOM header
        # has no positive cardiac label.  It sits immediately before the
        # calibration button, as the acceptance list asks.
        "ds_markers",
        SOURCE_SHORTCUT,
        "cine_phase_markers",
        group=GROUP_CALIBRATION,
        label_key="toolbtn.ds_markers",
        icon="activity_cine_phases",
    ),
    ToolButtonSpec(
        "calibration",
        SOURCE_SHORTCUT,
        "calibration_toggle",
        group=GROUP_CALIBRATION,
        label_key="toolbtn.calibration",
        icon="tune",
        separated=True,
    ),
    ToolButtonSpec(
        # The loupe is a *mode*, not a shortcut of the registry: it has no key of
        # its own («Z» already holds the temporary lens), and inventing one would
        # put a badge on the button that nothing answers (item 4 of the
        # 2026-10-23 list — «непонятно, что именно приближается»).
        "zoom",
        SOURCE_SHORTCUT,
        "zoom_loupe",
        group=GROUP_VIEW,
        label_key="toolbtn.zoom",
        icon="search",
    ),
)

#: The buttons the right-aligned group holds (§4.2: «Справа от ряда — масштаб,
#: поворот, «Сравнить», «Фокус»»; only the zoom exists yet).
TOOL_BUTTONS_RIGHT: Final[tuple[str, ...]] = tuple(spec.id for spec in TOOL_BUTTONS if spec.group == GROUP_VIEW)

_BY_ID: Final[dict[str, ToolButtonSpec]] = {spec.id: spec for spec in TOOL_BUTTONS}


def tool_button_spec(button_id: str) -> ToolButtonSpec | None:
    """The descriptor of ``button_id``, or ``None`` for an unknown id."""
    return _BY_ID.get(button_id)


def catalog_tool(spec: ToolButtonSpec) -> ToolSpec | None:
    """The catalog entry behind a measurement button."""
    if spec.source != SOURCE_CATALOG:
        return None
    return CATALOG.get(spec.ref)


def _language(language: str) -> str:
    return (language or "ru").strip().lower()[:2]


def caption(spec: ToolButtonSpec, language: str = "ru") -> str:
    """Short text of the button.

    A catalog tool answers with its own short label (TP-0 keeps the RU and EN
    forms of every tool, and UD-15 asks the row to reuse them rather than keep a
    third list of captions); a ``label_key`` on the spec overrides that — the
    freehand pair reuses ``tool.area``/``tool.volume`` but must not read
    «Сплайн».  The rest of the buttons read a locale key.
    """
    if spec.label_key:
        return tr_for_language(spec.label_key, language)
    tool = catalog_tool(spec)
    if tool is not None:
        return tool.label(_language(language)).short
    return tr_for_language(spec.id, language)


def payload(spec: ToolButtonSpec) -> EmittedAction | None:
    """The ``action / view / phase / extra`` a catalog tool activates with.

    ``None`` says the button is not a measurement tool: the window routes it to
    the handler of its shortcut instead (D-09 — one sink for the payload,
    :meth:`MainWindow._on_measure_action`).
    """
    tool = catalog_tool(spec)
    return None if tool is None else emitted_action(tool)


def key_hint(spec: ToolButtonSpec) -> str:
    """The key badge of the button — always the key that really works (§4.1).

    A mode button reads its sequence out of the registry; a catalog tool has no
    registry id of its own, so its badge is the tool's default key.  Nothing here
    invents a binding: an unbound tool simply has no badge.
    """
    if spec.shortcut_id and has_shortcut(spec.shortcut_id):
        sequences = get_shortcut(spec.shortcut_id).sequences
        return sequences[0] if sequences else ""
    tool = catalog_tool(spec)
    return "" if tool is None else (tool.default_key or "")


#: Locale keys explaining what a mode button actually does.  A bare «Калибровка»
#: on a row of twelve glyphs does not say «click two ends of a known distance»,
#: which is exactly what the 2026-10-23 acceptance pass reported (item 3).
_MODE_TOOLTIP_KEYS: Final[dict[str, str]] = {
    "calibration": "toolbtn.calibration_tooltip",
    "doppler_interval": "toolbtn.doppler_interval_tooltip",
    "vti_trace": "toolbtn.vti_trace_tooltip",
    "zoom": "toolbtn.zoom_tooltip",
    "ds_markers": "toolbtn.ds_markers_tooltip",
}


def tooltip(spec: ToolButtonSpec, language: str = "ru") -> str:
    """Full name plus the key hint — the wording the measures menu uses."""
    tool = catalog_tool(spec)
    explanation = _MODE_TOOLTIP_KEYS.get(spec.id)
    if tool is None and explanation:
        text = tr_for_language(explanation, language)
        if spec.shortcut_id and has_shortcut(spec.shortcut_id):
            return append_shortcut_hint(text, spec.shortcut_id, language=language)
        return text
    if spec.label_key and tool is not None:
        # Freehand pair: the caption is the truth, not the spline full name.
        text = caption(spec, language)
    elif tool is not None:
        text = tool.label(_language(language)).full
    else:
        text = caption(spec, language)
    if spec.shortcut_id and has_shortcut(spec.shortcut_id):
        return append_shortcut_hint(text, spec.shortcut_id, language=language)
    key = key_hint(spec)
    return f"{text} ({key})" if key else text


def has_shortcut(shortcut_id: str) -> bool:
    """Whether the registry knows the id (a row button may sit in the viewer)."""
    try:
        get_shortcut(shortcut_id)
    except KeyError:
        return False
    return True


def unavailable_reason(spec: ToolButtonSpec, state: ToolButtonState, language: str = "ru") -> str:
    """Why ``spec`` is dimmed, or ``""`` when it is available (D-08).

    Three rules, in the order a clinician hits them: no clip; Multiview, where
    stage 1 refuses every tool that would draw on the hidden main viewer (§10.2
    of the comparison spec); and the context of the clip, read from the catalog
    rather than guessed here.
    """
    if not state.has_clip:
        return tr_for_language("toolbtn.reason.no_clip", language)
    if state.multiview:
        return tr_for_language("toolbtn.reason.multiview", language)
    if spec.group == GROUP_VIEW:
        return ""
    tool = catalog_tool(spec)
    if tool is None:
        # A mode button guards itself: the handler behind it shows its own status
        # hint («временная калибровка не готова»), exactly as the hotkey does — so
        # the row never dims a button on a guess the catalog cannot back.
        return ""
    contexts = context_catalog_contexts(
        normalize_panel_context(state.context),
        normalize_doppler_mode(state.doppler_mode),
    )
    if tool.contexts and not (tool.contexts & contexts):
        return tr_for_language("toolbtn.reason.context", language)
    return ""


def visible_buttons(state: ToolButtonState) -> tuple[ToolButtonSpec, ...]:
    """Every spec — the views never drop buttons, they dim them (§4.2)."""
    del state
    return TOOL_BUTTONS
