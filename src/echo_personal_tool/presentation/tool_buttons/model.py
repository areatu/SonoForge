"""The image tools of the tool row (UI-2 PR-3, spec §4.2 «Ряд над снимком»).

Pure module, no Qt: the list of buttons, their order and the payload each one
sends. The row widget only renders :data:`ROW_TOOLS` and emits the same
``action_requested(action, view, phase, extra)`` contract as the tool panel
(D-09), so both entries reach one handler, :meth:`MainWindow._on_measure_action`.

Buttons take their identity from the measurement catalog where the catalog has
a tool for them (``catalog_id``); the rest are viewer tools that the catalog
does not describe (contour, calibration, auto-contour) and carry their action
directly. :func:`validate_row` checks both kinds in the unit tests.

Not in this PR: the pointer / shift / loupe / brightness modes and the right
group (zoom, rotation, compare, focus). They have no handler yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.presentation.measurement_action import MeasurementAction


@dataclass(frozen=True)
class RowTool:
    """One button of the tool row."""

    id: str
    action: MeasurementAction
    label_key: str
    shortcut_id: str = ""
    catalog_id: str = ""
    view: str = "A4C"
    phase: str = "ED"
    extra: str = ""

    def payload(self) -> tuple[MeasurementAction, str, str, str]:
        """The ``action_requested`` arguments of this button."""
        return self.action, self.view, self.phase, self.extra


#: Left group of the row: linear, area, contour │ Doppler │ calibration │ auto-contour.
ROW_TOOLS: tuple[RowTool, ...] = (
    RowTool("caliper", MeasurementAction.CALIPER, "tool_row.caliper", "caliper", "tool.caliper"),
    RowTool("area", MeasurementAction.SPLINE_AREA, "tool_row.area", "", "tool.area"),
    RowTool("contour", MeasurementAction.MANUAL_CONTOUR, "tool_row.contour", "manual_contour"),
    RowTool("doppler", MeasurementAction.DOPPLER_TRACE, "tool_row.doppler", "vti_trace"),
    RowTool("calibration", MeasurementAction.CALIBRATION, "tool_row.calibration", "calibration_toggle"),
    RowTool("auto_contour", MeasurementAction.AUTO_SEGMENT, "tool_row.auto_contour", "auto_segment"),
)


def row_tool(tool_id: str) -> RowTool | None:
    """The button with ``tool_id``; ``None`` when there is none."""
    for tool in ROW_TOOLS:
        if tool.id == tool_id:
            return tool
    return None


def validate_row(
    tools: tuple[RowTool, ...] = ROW_TOOLS,
    *,
    catalog: dict[str, object],
    shortcut_ids: frozenset[str],
    locale_keys: frozenset[str],
) -> list[str]:
    """Consistency problems of a row (an empty list means consistent).

    ``catalog`` maps catalog ids to tools with a ``payload.action`` attribute;
    ``shortcut_ids`` are the ids of the shortcut registry; ``locale_keys`` are
    the keys both locales define.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for tool in tools:
        if tool.id in seen:
            problems.append(f"duplicate id: {tool.id}")
        seen.add(tool.id)
        if tool.label_key not in locale_keys:
            problems.append(f"{tool.id}: no label {tool.label_key}")
        if tool.shortcut_id and tool.shortcut_id not in shortcut_ids:
            problems.append(f"{tool.id}: unknown shortcut {tool.shortcut_id}")
        if tool.catalog_id:
            catalog_tool = catalog.get(tool.catalog_id)
            if catalog_tool is None:
                problems.append(f"{tool.id}: unknown catalog tool {tool.catalog_id}")
            elif getattr(getattr(catalog_tool, "payload", None), "action", None) != str(tool.action):
                problems.append(f"{tool.id}: catalog action differs from the button")
    return problems
