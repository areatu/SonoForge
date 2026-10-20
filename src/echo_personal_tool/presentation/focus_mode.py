"""Focus mode for a single-file workspace (UI-6, spec §4.8, UQ-02).

The mode is a *view* of one clip: no study panels, the tool rail left of the
image, a thin header strip with the file facts and the measurements of this file
floating over the snapshot.  It never changes what is measured or stored — the
same viewer, the same controller and the same measurements stay behind it.

This module is pure: no Qt and no infrastructure, so the entry rule, the slot
plan and the geometry of the floating plates can be tested without a window.
The widgets live in :mod:`echo_personal_tool.presentation.focus_widgets` and the
window only wires them to the layout, the controller and the tab.

Three decisions are encoded here:

* **What is a single file.**  A tab is a single-file workspace when the whole
  study set holds exactly one clip (one instance across all series).  The
  application groups every media file into a study (a synthetic UID for video
  and images), so «one file» is exactly one clip — not «a file without a
  study», which the data model does not have.
* **When focus opens by itself.**  Only on a fresh load, only when the user's
  «Одиночный файл — в режиме „Фокус“» switch is on, and only once per source:
  after the user leaves with F, switching tabs must not drag the mode back
  (the per-tab ``focus_decided`` flag owns that).
* **What the layout drops.**  §4.8 (F1): the gallery, the tool panel and the
  tool row above the image disappear, the rail takes the left edge, and the
  step bar of the snapshot column stays exactly where UI-3 puts it.  The mode
  is not a new preset: the preset and the button view are kept for the return
  trip, so leaving focus restores the same layout document.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from echo_personal_tool.domain.models.metadata import StudyMetadata
from echo_personal_tool.presentation.layout.presets import (
    SLOT_RAIL,
    SLOT_VIEWER,
    SlotPlan,
)

#: A single-file workspace has exactly this many clips.
SINGLE_FILE_CLIP_COUNT = 1

#: §4.8: the floating measurements card and the cine plate of the schematic.
FOCUS_CARD_WIDTH = 280
FOCUS_CARD_HEIGHT = 196
FOCUS_CINE_WIDTH = 720
FOCUS_CINE_HEIGHT = 56
#: Distance from the edges of the viewer and between the two floating plates.
FOCUS_MARGIN = 12
FOCUS_GAP = 8
#: §4.8: «когда курсор при рисовании подходит к ним, они становятся полупрозрачными».
#: A plate fades once the pointer is within this many pixels of its edge.
PLATE_FADE_DISTANCE = 28
#: Opacity of a faded plate: readable, but the snapshot underneath stays visible.
PLATE_FADE_OPACITY = 0.45


def clip_count(studies: Iterable[StudyMetadata]) -> int:
    """Number of clips (instances) in a study set, across every series."""
    return sum(len(series.instances) for study in studies for series in study.series)


def is_single_file(studies: Iterable[StudyMetadata]) -> bool:
    """True when the study set is one file — the only case focus mode opens for."""
    return clip_count(studies) == SINGLE_FILE_CLIP_COUNT


def should_enter_focus(*, enabled: bool, studies: Iterable[StudyMetadata]) -> bool:
    """The automatic entry of §4.8: the setting is on and the file is alone."""
    return bool(enabled) and is_single_file(studies)


def focus_plan() -> SlotPlan:
    """Slots of the focus view (F1): rail left, image centre, no study panels.

    The plan is deliberately independent of the preset and of Multiview: the
    mode is a tab-scoped overlay over the chosen layout, and leaving it returns
    to the preset untouched.  ``top`` is empty because the thin header strip is
    not the tool row — the window puts it into the same column slot; ``bottom``
    is empty because the step bar belongs to the column and UI-3 keeps it there
    (UD-04: the step bar sits above the cine plate, not over the image).
    """
    return SlotPlan(left=SLOT_RAIL, center=SLOT_VIEWER, right=None, bottom=None, top=None)


@dataclass(frozen=True)
class FocusHeaderInfo:
    """One line of file facts for the focus strip: имя файла, проекция, пациент, дата."""

    file_label: str = ""
    projection: str = ""
    patient: str = ""
    date: str = ""

    def parts(self) -> tuple[str, ...]:
        """Non-empty facts in reading order; an unknown field is simply absent."""
        return tuple(part for part in (self.projection, self.patient, self.date) if part)


def focus_header_text(info: FocusHeaderInfo, separator: str = " · ") -> str:
    """The secondary line of the strip: projection · patient · date."""
    return separator.join(info.parts())


def split_measurement_line(line: str) -> tuple[str, str]:
    """Split ``«КДО 4C: 112 mL»`` into its label and value for the card rows.

    The lines come from the same plain-text formatter as the on-image overlay
    (``format_results_overlay``), so the card and the image can never disagree
    about a value.  A line without ``«: »`` (a diastology grade, for example)
    is a full-width row: the label keeps the whole text and the value is empty.
    """
    text = line.strip()
    label, separator, value = text.partition(": ")
    if not separator:
        return text, ""
    return label.strip(), value.strip()


@dataclass(frozen=True)
class FocusRect:
    """A pixel rectangle of a floating plate (integer geometry, Qt-free)."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def intersects(self, other: FocusRect) -> bool:
        """Whether two plates overlap (touching edges do not count)."""
        return self.x < other.right and other.x < self.right and self.y < other.bottom and other.y < self.bottom


@dataclass(frozen=True)
class FocusPanelRects:
    """Where the two floating plates sit inside the snapshot area (F1)."""

    card: FocusRect
    cine: FocusRect


def place_focus_panels(
    area_width: int,
    area_height: int,
    *,
    card_width: int = FOCUS_CARD_WIDTH,
    card_height: int = FOCUS_CARD_HEIGHT,
    cine_width: int = FOCUS_CINE_WIDTH,
    cine_height: int = FOCUS_CINE_HEIGHT,
    margin: int = FOCUS_MARGIN,
    gap: int = FOCUS_GAP,
) -> FocusPanelRects:
    """Place the measurements card (top-right) and the cine plate (bottom-centre).

    §4.8: «Плавающие элементы прижаты к краям».  The result never leaves the
    area and never lets the card touch the cine plate: on a short viewer the
    card is shortened first (it scrolls its rows), the cine plate second.  A
    zero-sized area still yields valid, non-negative rectangles, so a resize
    during teardown cannot produce a negative geometry.
    """
    width = max(0, int(area_width))
    height = max(0, int(area_height))
    margin = max(0, int(margin))
    gap = max(0, int(gap))

    cine_height = min(max(0, int(cine_height)), max(0, height - 2 * margin))
    cine_width = min(max(0, int(cine_width)), max(0, width - 2 * margin))
    cine = FocusRect(
        x=max(0, (width - cine_width) // 2),
        y=max(0, height - margin - cine_height),
        width=cine_width,
        height=cine_height,
    )

    card_width = min(max(0, int(card_width)), max(0, width - 2 * margin))
    card_height = min(max(0, int(card_height)), max(0, height - 2 * margin))
    # Keep a gap between the card and the plate; the plate itself is clamped,
    # so a very small area may leave no room at all for the card.
    card_height = min(card_height, max(0, cine.y - gap - margin))
    card = FocusRect(
        x=max(0, width - margin - card_width),
        y=margin,
        width=card_width,
        height=card_height,
    )
    return FocusPanelRects(card=card, cine=cine)


def plate_opacity(
    cursor_x: int,
    cursor_y: int,
    rect: FocusRect,
    *,
    distance: int = PLATE_FADE_DISTANCE,
    faded: float = PLATE_FADE_OPACITY,
) -> float:
    """Opacity of a floating plate for a pointer at ``(cursor_x, cursor_y)``.

    §4.8 asks the plates to step back while the user draws near them.  The
    pointer inside the plate, or within ``distance`` of its edge (measured to
    the nearest point of the rectangle), fades it; anywhere else it is opaque.
    A degenerate rectangle fades only under the pointer itself.
    """
    dx = max(rect.x - cursor_x, 0, cursor_x - rect.right)
    dy = max(rect.y - cursor_y, 0, cursor_y - rect.bottom)
    reach = max(0, int(distance))
    if rect.width <= 0 or rect.height <= 0:
        inside = rect.x <= cursor_x <= rect.right and rect.y <= cursor_y <= rect.bottom
        return float(faded) if inside else 1.0
    if dx * dx + dy * dy <= reach * reach:
        return float(faded)
    return 1.0


def measurement_lines(text: str) -> tuple[str, ...]:
    """Non-empty lines of a plain-text overlay summary, for the card."""
    return tuple(line.strip() for line in str(text or "").splitlines() if line.strip())


def copy_text(info: FocusHeaderInfo, lines: Sequence[str], *, title: str) -> str:
    """The clipboard payload of «Копировать»: file facts, then the values."""
    header = " · ".join(part for part in (info.file_label, *info.parts()) if part)
    body = "\n".join(lines)
    if header and body:
        return f"{title}\n{header}\n\n{body}"
    if header:
        return f"{title}\n{header}"
    if body:
        return f"{title}\n\n{body}"
    return title


__all__ = [
    "FOCUS_CARD_HEIGHT",
    "FOCUS_CARD_WIDTH",
    "FOCUS_CINE_HEIGHT",
    "FOCUS_CINE_WIDTH",
    "FOCUS_GAP",
    "FOCUS_MARGIN",
    "PLATE_FADE_DISTANCE",
    "PLATE_FADE_OPACITY",
    "SINGLE_FILE_CLIP_COUNT",
    "FocusHeaderInfo",
    "FocusPanelRects",
    "FocusRect",
    "clip_count",
    "copy_text",
    "focus_header_text",
    "focus_plan",
    "is_single_file",
    "measurement_lines",
    "place_focus_panels",
    "plate_opacity",
    "should_enter_focus",
    "split_measurement_line",
]
