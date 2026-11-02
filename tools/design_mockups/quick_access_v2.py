"""Second round of quick-access concepts (2026-10-30 UI review).

The first round (``quick_access.py``) answered *where* the tool panel goes.  The
review of the running 0.3.3 build showed that the placement was not the problem:
the same eleven actions live in the row over the image *and* in the right panel,
the row spends its width on long captions («Площадь (свободно)») and folds the
rest into a bare «…», the armed tool is only visible as one caption, modifiers
(«Интервал», «D/S маркеры», «Калибровка») look exactly like tools, and the
anatomical board — the one control that says what the panel is about — sits
below the fold.

So this round varies the *model* of the toolbar, not its position:

* 11 «Активный инструмент» — the row is icons; the armed tool opens in place as a
  labelled card with its own options (spline / freehand, closure, tolerance), so
  the options stop hiding in the panel and the row stops widening;
* 12 «Две полосы» — six pinned actions with captions and keys plus one «Все
  инструменты» sheet, and the full tool list is shown once, in the panel, as an
  icon rack — one map instead of two;
* 13 «Инструмент в шаге» — no permanent row at all: the tools valid for the
  current protocol step sit in a pill over the image next to the instruction, and
  the panel becomes the navigator (protocol → anatomy → measurements).

All three keep the same header, clips, viewer, step bar, cine bar and status bar,
so only the tool model and the panel body differ.  Frames are the de-identified
fixtures, the study is fictional.

Run from this directory (one process per canvas, see the runner):
    LD_LIBRARY_PATH=<qt stubs> QT_QPA_PLATFORM=offscreen python quick_access_v2_run.py
"""

from __future__ import annotations

import lay_final as F
import screen_a as A
from common import (
    C,
    QRectF,
    button,
    hline,
    icon,
    kbd,
    pill,
    rrect,
    search_field,
    section_label,
    text,
    toggle,
    tw,
    vline,
)
from kit import REPO, Canvas
from lay_common import H, S, W, clips_grid, status, step_bar, title, viewer_area

OUT = REPO / "docs/images/quick-access-concepts-v2"
TH = F.TH
TB, SB = F.TB, F.SB
PL = F.PL
CINE_H, STEP_H = F.CINE_H, F.STEP_H
CLIPS_W = F.CLIPS_W

# One vocabulary for every canvas: the captions of the running build, shortened
# where the row had to fold (the full name stays in the tooltip and the sheet).
# Keys are the *real* registry bindings (keyboard_shortcuts.py): caliper L,
# manual contour C, auto contour I, Doppler VTI V, interval T, calibration K.
# «Площадь», «Объём», the freehand pair, «D/S маркеры» and «Лупа» have no key in
# the registry, so the mockups draw no badge for them instead of inventing one.
TOOLS = [
    ("l-ruler", "Калипер", "L"),
    ("l-square-dashed", "Площадь", ""),
    ("l-spline", "Объём", "C"),
    ("l-sparkles", "Авто-контур", "I"),
]
TOOLS_MORE = [
    ("l-pen-tool", "Площадь (свободно)", ""),
    ("l-layers", "Объём (свободно)", ""),
    ("l-audio-waveform", "Допплер", "V"),
    ("l-ruler", "Интервал", "T"),
    ("l-crosshair", "D/S маркеры", ""),
    ("l-sliders-horizontal", "Калибровка", "K"),
]
MODIFIERS = [("l-ruler", "Интервал"), ("l-crosshair", "D/S маркеры"), ("l-sliders-horizontal", "Калибровка")]
ANATOMY = [("ЛЖ", "14"), ("ЛП", "5"), ("ПЖ", "6"), ("Аорта", "9"), ("МК", "9"), ("ТК", "7"), ("Общее", "6")]
LV = [
    ("МЖП", "l-ruler", "1", "done"),
    ("КДР ЛЖ", "l-ruler", "2", "done"),
    ("ЗСЛЖ", "l-ruler", "3", ""),
    ("КСР ЛЖ", "l-ruler", "4", ""),
    ("КДО · 4-кам.", "l-spline", "5", ""),
    ("КСО · 4-кам.", "l-spline", "6", "current"),
]
PROTOCOLS = [("Симпсон бипланово", 1, 4, True), ("ЛЖ линейно", 2, 2, False), ("Объём ЛП", 0, 2, False)]


# ─────────────────────────────── shell ────────────────────────────────


def _canvas():
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    title(p)
    F.header(p, 0)
    return cv, p, TB + PL, H - SB


def _panel_bg(p, x, top, bottom):
    p.fillRect(QRectF(x, top, W - x, bottom - top), C(TH["bg1"]))
    vline(p, x, top, bottom - top, TH["line"])


def _viewer_shell(p, x, y, w, img_h, *, step=True):
    viewer_area(p, x, y, w, img_h, banner=False, pad=(24, 12, 58, 78))
    if step:
        step_bar(p, x, y + img_h, w, STEP_H)
    A.cine_bar(p, TH, x, y + img_h + (STEP_H if step else 0), w, CINE_H)


def _panel_tabs(p, x, top, w, items=("Измерения", "Расчёты", "Управление")):
    tx = x
    for index, label in enumerate(items):
        active = index == 0
        box_w = tw(label, 12, 600 if active else 500) + 20
        text(
            p,
            label,
            tx,
            top,
            12,
            600 if active else 500,
            TH["text"] if active else TH["text2"],
            w=box_w,
            h=34,
            va="c",
        )
        if active:
            rrect(p, tx, top + 34, box_w - 6, 2, 1, fill=TH["accent"])
        tx += box_w + 8
    hline(p, x - 12, top + 37, w + 24, TH["line"])


def _anatomy_chips(p, x, y, w, *, selected="ЛЖ", count_label=None):
    """Always-visible anatomy chips; the row scrolls sideways instead of hiding."""
    gap = 5
    cx = x
    limit = x + w - (26 if count_label else 0)
    for label, count in ANATOMY:
        bw = tw(label, 10.5, 600) + tw(count, 9, 600) + 26
        if cx + bw > limit:
            rrect(p, x + w - 22, y, 22, 26, 6, fill=TH["bg3"], stroke=TH["line"])
            icon(p, "l-chevron-right", x + w - 17, y + 7, 12, TH["text2"])
            break
        active = label == selected
        rrect(
            p,
            cx,
            y,
            bw,
            26,
            6,
            fill=C(TH["accent"], 0.18) if active else TH["bg2"],
            stroke=C(TH["accent"], 0.58) if active else TH["line"],
        )
        text(
            p,
            label,
            cx + 8,
            y,
            10.5,
            600 if active else 500,
            TH["accent_text"] if active else TH["text2"],
            w=bw - 26,
            h=26,
            va="c",
        )
        text(p, count, cx + bw - 18, y, 9, 600, TH["text3"], w=12, h=26, align="c", va="c")
        cx += bw + gap


def _measure_rows(p, x, y, w, items=LV, row_h=31, gap=4):
    used = 0
    for label, glyph, key, state in items:
        active = state == "current"
        rrect(
            p,
            x,
            y,
            w,
            row_h,
            6,
            fill=C(TH["accent"], 0.15) if active else TH["bg2"],
            stroke=C(TH["accent"], 0.5) if active else TH["line"],
        )
        if state == "done":
            icon(p, "l-circle-check", x + 8, y + (row_h - 14) / 2, 14, TH["ok"])
            fg = TH["text2"]
        elif active:
            icon(p, "l-circle-dot", x + 8, y + (row_h - 14) / 2, 14, TH["accent_text"])
            fg = TH["accent_text"]
        else:
            icon(p, glyph, x + 8, y + (row_h - 14) / 2, 14, TH["text3"])
            fg = TH["text"]
        text(p, label, x + 28, y, 10.5, 600 if active else 500, fg, w=w - 58, h=row_h, va="c", elide=True)
        text(p, key, x + w - 20, y, 9, 700, TH["text3"], w=14, h=row_h, align="r", va="c")
        y += row_h + gap
        used += row_h + gap
    return used


def _protocol_rows(p, x, y, w, rows=PROTOCOLS, compact=False):
    used = 0
    for label, done, total, active in rows:
        h = 34 if compact else 44
        rrect(
            p,
            x,
            y,
            w,
            h,
            7,
            fill=TH["bg2"] if active else None,
            stroke=C(TH["accent"], 0.42) if active else TH["line"],
        )
        icon(p, "l-activity", x + 9, y + (h - 15) / 2, 15, TH["accent_text"] if active else TH["text3"])
        text(
            p,
            label,
            x + 30,
            y,
            10.5,
            600 if active else 500,
            TH["text"] if active else TH["text2"],
            w=w - 80,
            h=h,
            va="c",
            elide=True,
        )
        pill(
            p,
            x + w - 46,
            y + (h - 18) / 2,
            f"{done}/{total}",
            TH["accent_text"] if active else TH["text3"],
            TH["bg3"],
            h=18,
            size=8.5,
        )
        y += h + 6
        used += h + 6
    return used


# ────────────────────────── concept 11 ──────────────────────────


def _row_active_tool(p, x, y, w, h):
    """Icons only; the armed tool opens as a labelled card with its own options.

    The row keeps its full set without folding: eleven 32 px cells plus the card
    of the armed tool fit a 1280 px viewer, and the card is the place where the
    options of that tool live («Сплайн | Свободно», «Замкнуть», «Допуск»).
    """
    p.fillRect(QRectF(x, y, w, h), C(TH["bg1"]))
    hline(p, x, y + h - 1, w, TH["line"])
    bx = x + 12
    by = y + (h - 30) / 2
    active_index = 2  # «Объём» armed
    for index, (glyph, label, key) in enumerate(TOOLS):
        if index == active_index:
            # The armed card: icon + name + key on the left edge of the card.
            card_w = tw(label, 11.5, 600) + 74
            rrect(p, bx, by, card_w, 30, 6, fill=C(TH["accent"], 0.16), stroke=C(TH["accent"], 0.55))
            icon(p, glyph, bx + 9, by + 7, 16, TH["accent_text"])
            text(p, label, bx + 31, by, 11.5, 600, TH["accent_text"], w=card_w - 60, h=30, va="c")
            if key:
                kbd(p, bx + card_w - 26, by + 6, key, TH)
            bx += card_w + 6
            continue
        icon(p, glyph, bx + 8, by + 7, 16, TH["text2"])
        if key:
            text(p, key, bx + 22, by + 15, 8.5, 700, TH["text3"])
        bx += 32

    # Options of the armed tool, attached to its card.
    options = [("Сплайн", True), ("Свободно", False)]
    ox = bx + 8
    for label, selected in options:
        seg_w = tw(label, 10.5, 600) + 20
        rrect(
            p,
            ox,
            by,
            seg_w,
            30,
            6,
            fill=TH["bg3"] if selected else None,
            stroke=TH["line2"] if selected else TH["line"],
        )
        text(
            p,
            label,
            ox,
            by,
            10.5,
            600 if selected else 500,
            TH["text"] if selected else TH["text2"],
            w=seg_w,
            h=30,
            align="c",
            va="c",
        )
        ox += seg_w + 4
    ox += 4
    icon(p, "l-sliders-horizontal", ox, by + 7, 16, TH["text3"])
    ox += 20
    # Modifiers sit apart, behind one hairline: they are not tools.
    vline(p, ox, by + 5, 20, TH["line2"])
    ox += 9
    text(p, "ИЗМЕНЯЮТ", ox, by, 8.5, 700, TH["text3"], w=60, h=30, va="c", spacing=0.4)
    ox += 58
    for glyph, label in ("l-ruler", "Интервал"), ("l-crosshair", "D/S"), ("l-sliders-horizontal", "Калибровка"):
        bw = tw(label, 10.5, 500) + 26
        icon(p, glyph, ox + 2, by + 7, 15, TH["text3"])
        text(p, label, ox + 21, by, 10.5, 500, TH["text3"], w=bw - 20, h=30, va="c")
        ox += bw + 4

    # Right: the reset and the whole list, with the count of what is hidden.
    xr = x + w - 12
    for glyph in ("l-undo-2", "l-panel-right"):
        xr -= 30
        icon(p, glyph, xr + 7, by + 7, 16, TH["text2"])
    xr -= 8
    bw = tw("Все", 10.5, 600) + 46
    xr -= bw
    rrect(p, xr, by, bw, 30, 6, fill=None, stroke=TH["line2"])
    icon(p, "l-layout-grid", xr + 8, by + 7, 16, TH["text2"])
    text(p, "Все", xr + 28, by, 10.5, 600, TH["text2"], w=18, h=30, va="c")


def render_11_active_tool():
    """Concept 11: the armed tool is the only caption in the row — and it carries its options."""
    cv, p, top, bottom = _canvas()
    panel_w = 340
    clips_grid(p, 0, top, CLIPS_W, bottom)
    vx, vw = CLIPS_W, W - CLIPS_W - panel_w
    row_h = 46
    _row_active_tool(p, vx, top, vw, row_h)
    _viewer_shell(p, vx, top + row_h, vw, bottom - top - row_h - CINE_H - STEP_H)

    _panel_bg(p, W - panel_w, top, bottom)
    x, w = W - panel_w + 12, panel_w - 24
    _panel_tabs(p, x, top, w)
    _anatomy_chips(p, x, top + 46, w)
    y = top + 80
    section_label(p, x, y, "ЛЕВЫЙ ЖЕЛУДОЧЕК · 6 ИЗ 14", TH, size=9)
    text(p, "свернуть", x + w - 52, y, 9, 500, TH["text3"], w=52, h=14, align="r")
    y += 18
    _measure_rows(p, x, y, w)
    y += 6 * 35 + 8
    hline(p, x, y, w, TH["line"])
    y += 10
    section_label(p, x, y, "ПРОТОКОЛ", TH, size=9)
    text(p, "1 из 4", x + w - 44, y, 9, 600, TH["accent_text"], w=44, h=14, align="r")
    y += 18
    _protocol_rows(p, x, y, w, PROTOCOLS[:1], compact=True)
    _panel_footer(p, x, y + 46, w, bottom)
    status(p)
    return cv.save(OUT / "11-active-tool.png")


def _panel_footer(p, x, y, w, bottom):
    """«Нормы» switch and «Открыть отчёт» pinned to the foot of the panel."""
    yb = bottom - 52
    hline(p, x - 12, yb, w + 24, TH["line"])
    text(p, "Нормы", x, yb + 17, 10.5, 500, TH["text2"])
    toggle(p, x + w - 32, yb + 15, True, TH)
    button(p, x, yb + 32 - 20, TH, None, None, "ghost", h=1)  # keep the rhythm of the sheet
    return yb


# ────────────────────────── concept 12 ──────────────────────────


def _row_tiered(p, x, y, w, h):
    """Six pinned actions with captions, one «Все инструменты» sheet at the right."""
    p.fillRect(QRectF(x, y, w, h), C(TH["bg1"]))
    hline(p, x, y + h - 1, w, TH["line"])
    bx = x + 10
    by = y + (h - 30) / 2
    pinned = [
        TOOLS[0],
        TOOLS[1],
        TOOLS[2],
        ("l-audio-waveform", "Допплер", "V"),
        ("l-sparkles", "Авто", "I"),
        ("l-search", "Лупа", ""),
    ]
    xr = x + w - 12
    sheet_w = tw("Все инструменты", 10.5, 600) + 52
    for index, (glyph, label, key) in enumerate(pinned):
        bw = tw(label, 10.5, 600) + (50 if key else 32)
        if bx + bw > xr - sheet_w - 16:
            # The strip is fixed: what does not fit is counted, not cut.
            text(p, f"+{len(pinned) - index}", bx, by, 10, 600, TH["text3"], w=26, h=30, va="c")
            break
        if label in ("Площадь",):
            rrect(p, bx, by, bw, 30, 6, fill=C(TH["accent"], 0.16), stroke=C(TH["accent"], 0.5))
            fg = TH["accent_text"]
        else:
            rrect(p, bx, by, bw, 30, 6, fill=TH["bg2"], stroke=TH["line"])
            fg = TH["text2"]
        icon(p, glyph, bx + 8, by + 7, 15, fg)
        text(p, label, bx + 27, by, 10.5, 600, fg, w=bw - 44, h=30, va="c", elide=True)
        if key:
            kbd(p, bx + bw - 21, by + 6, key, TH)
        bx += bw + 4
    # one sheet button, always in the same place
    rrect(p, xr - sheet_w, by, sheet_w, 30, 6, fill=None, stroke=TH["line2"])
    icon(p, "l-layout-grid", xr - sheet_w + 8, by + 7, 15, TH["text2"])
    text(p, "Все инструменты", xr - sheet_w + 27, by, 10.5, 600, TH["text2"], w=sheet_w - 36, h=30, va="c")
    # Counted badge: how many actions are behind the sheet.
    rrect(p, xr - 6, by + 2, 18, 18, 9, fill=TH["bg3"], stroke=TH["line2"])
    text(p, "6", xr - 6, by + 2, 8.5, 700, TH["text2"], w=18, h=18, align="c", va="c")


def _tool_rack(p, x, y, w):
    """The one full list of tools, in the panel: icon + name + key, 3 columns."""
    items = TOOLS + TOOLS_MORE
    # Two columns: a caption, a glyph and the key badge inside one cell of a
    # 400 px panel; three columns cut «Площадь (свободно)» to «Площадь (св…».
    cols, gap = 2, 6
    cell_w = (w - gap * (cols - 1)) / cols
    cell_h = 34
    for index, (glyph, label, key) in enumerate(items):
        row, col = divmod(index, cols)
        bx = x + col * (cell_w + gap)
        by = y + row * (cell_h + 6)
        active = label == "Площадь"
        available = cell_w - 26 - (tw(key, 8.5, 700) + 6 if key else 0)
        rrect(
            p,
            bx,
            by,
            cell_w,
            cell_h,
            6,
            fill=C(TH["accent"], 0.15) if active else TH["bg2"],
            stroke=C(TH["accent"], 0.5) if active else TH["line"],
        )
        icon(p, glyph, bx + 7, by + (cell_h - 14) / 2, 14, TH["accent_text"] if active else TH["text3"])
        text(
            p,
            label,
            bx + 26,
            by,
            9.5,
            600 if active else 500,
            TH["accent_text"] if active else TH["text"],
            w=available,
            h=cell_h,
            va="c",
            elide=True,
        )
        if key:
            text(p, key, bx + cell_w - 24, by, 8.5, 700, TH["text3"], w=16, h=cell_h, align="r", va="c")
    rows = (len(items) + cols - 1) // cols
    return rows * (cell_h + 6)


def render_12_two_tiers():
    """Concept 12: pinned strip over the image, one complete list in the panel."""
    cv, p, top, bottom = _canvas()
    panel_w = 396
    clips_grid(p, 0, top, CLIPS_W, bottom)
    vx, vw = CLIPS_W, W - CLIPS_W - panel_w
    row_h = 44
    _row_tiered(p, vx, top, vw, row_h)
    _viewer_shell(p, vx, top + row_h, vw, bottom - top - row_h - CINE_H - STEP_H)

    _panel_bg(p, W - panel_w, top, bottom)
    x, w = W - panel_w + 12, panel_w - 24
    _panel_tabs(p, x, top, w)
    search_field(p, x, top + 46, w, 30, "Найти измерение или действие…  (/ )", TH, size=10.5)
    y = top + 86
    section_label(p, x, y, "ИНСТРУМЕНТЫ", TH, size=9)
    text(p, "изменить набор", x + w - 92, y, 9, 500, TH["accent_text"], w=92, h=14, align="r")
    y += 18
    y += _tool_rack(p, x, y, w)
    y += 8
    hline(p, x, y, w, TH["line"])
    y += 10
    section_label(p, x, y, "АНАТОМИЯ", TH, size=9)
    y += 18
    _anatomy_chips(p, x, y, w)
    y += 34
    section_label(p, x, y, "ЛЕВЫЙ ЖЕЛУДОЧЕК · 6 ИЗ 14", TH, size=9)
    y += 18
    _measure_rows(p, x, y, w, LV[:4])
    _panel_footer(p, x, y + 4 * 35 + 10, w, bottom)
    status(p)
    return cv.save(OUT / "12-two-tiers.png")


# ────────────────────────── concept 13 ──────────────────────────


def _step_bar_with_tools(p, x, y, w, h=88):
    """The step bar under the image, carrying the tools of *this* step.

    Concept 13 has no tool row of its own: the instruction of the step and the
    two or three actions that step accepts are one strip, so the image keeps
    the height the row used to take and a tool can never disagree with the
    step.  The complete list stays one click away in the panel and in «Все».
    """
    p.fillRect(QRectF(x, y, w, h), C(TH["bg1"]))
    hline(p, x, y, w, TH["line"])
    rrect(p, x, y + 1, 3, h - 1, 0, fill=TH["accent"])
    tx = x + 18
    xx = tx + text(p, "СИМПСОН БИПЛАНОВО", tx, y + 10, 9.5, 700, TH["text2"], spacing=0.7) + 10
    xx += text(p, "шаг 2 из 4", xx, y + 10, 10, 600, TH["accent_text"]) + 10
    for state in ("done", "current", "todo", "todo"):
        icon(
            p,
            "l-circle-check" if state == "done" else ("l-circle-dot" if state == "current" else "l-circle"),
            xx,
            y + 9,
            12,
            TH["ok"] if state == "done" else (TH["accent_text"] if state == "current" else TH["text3"]),
        )
        xx += 16
    text(p, "КСО · 4-кам. — обведите эндокард ЛЖ", tx, y + 25, 13.5, 600, TH["text"], w=w - 420, h=20, elide=True)

    # The tools of this step: two measurement modes, then one way back.
    ax = tx
    for glyph, label, key, active in (
        ("l-spline", "Контур", "C", True),
        ("l-sparkles", "Авто-контур", "I", False),
    ):
        bw = tw(label, 11, 600) + 62
        rrect(
            p,
            ax,
            y + 50,
            bw,
            28,
            6,
            fill=C(TH["accent"], 0.17) if active else TH["bg2"],
            stroke=C(TH["accent"], 0.5) if active else TH["line"],
        )
        icon(p, glyph, ax + 9, y + 57, 15, TH["accent_text"] if active else TH["text2"])
        text(
            p,
            label,
            ax + 29,
            y + 50,
            11,
            600 if active else 500,
            TH["accent_text"] if active else TH["text"],
            w=bw - 52,
            h=28,
            va="c",
        )
        kbd(p, ax + bw - 24, y + 55, key, TH, h=17)
        ax += bw + 6
    vline(p, ax + 4, y + 54, 20, TH["line2"])
    ax += 13
    for label, key in (("Пропустить", "S"), ("Отмена", "Esc")):  # skip_step / cancel_tool
        bw = tw(label, 10.5, 500) + 50
        rrect(p, ax, y + 50, bw, 28, 6, fill=None, stroke=TH["line2"])
        text(p, label, ax + 10, y + 50, 10.5, 500, TH["text2"], w=bw - 34, h=28, va="c")
        kbd(p, ax + bw - 24, y + 55, key, TH, h=17)
        ax += bw + 6

    # Right: the primary action and the way to the whole list.
    xr = x + w - 16
    prim_w = tw("Готово", 11.5, 600) + 42
    xr -= prim_w
    button(p, xr, y + 50, TH, "Готово", "l-check", "primary", h=28, size=11.5)
    xr -= 10 + 30
    rrect(p, xr, y + 50, 30, 28, 6, fill=None, stroke=TH["line2"])
    icon(p, "l-layout-grid", xr + 7, y + 56, 16, TH["text2"])


def _panel_companion(p, x, top, w, bottom):
    """The panel beside the step pill: protocol first, then the anatomy of the study."""
    y = top + 46
    section_label(p, x, y, "ПРОТОКОЛ · 1 ИЗ 4", TH, size=9)
    text(p, "выйти", x + w - 34, y, 9, 500, TH["text3"], w=34, h=14, align="r")
    y += 18
    for label, state, detail in (
        ("КДО · 4-кам.", "done", "112 мл"),
        ("КСО · 4-кам.", "current", "оба эндокарда"),
        ("КДО · 2-кам.", "todo", ""),
        ("КСО · 2-кам.", "todo", ""),
    ):
        current = state == "current"
        rrect(
            p,
            x,
            y,
            w,
            34,
            7,
            fill=C(TH["accent"], 0.14) if current else None,
            stroke=C(TH["accent"], 0.45) if current else TH["line"],
        )
        icon(
            p,
            "l-circle-check" if state == "done" else ("l-circle-dot" if current else "l-circle"),
            x + 9,
            y + 10,
            14,
            TH["ok"] if state == "done" else (TH["accent_text"] if current else TH["text3"]),
        )
        text(
            p,
            label,
            x + 30,
            y,
            10.5,
            600 if current else 500,
            TH["text"] if current else TH["text2"],
            w=w - 110,
            h=34,
            va="c",
            elide=True,
        )
        if detail:
            text(p, detail, x + w - 74, y, 9, 500, TH["text3"], w=64, h=34, align="r", va="c")
        y += 38
    y += 4
    hline(p, x, y, w, TH["line"])
    y += 12
    section_label(p, x, y, "АНАТОМИЯ", TH, size=9)
    y += 18
    _anatomy_chips(p, x, y, w)
    y += 34
    section_label(p, x, y, "ЛЕВЫЙ ЖЕЛУДОЧЕК · 6 ИЗ 14", TH, size=9)
    y += 18
    _measure_rows(p, x, y, w, LV[:5])
    _panel_footer(p, x, y + 5 * 35 + 8, w, bottom)


def render_13_tool_in_step():
    """Concept 13: no tool row — the step bar under the image carries its tools."""
    cv, p, top, bottom = _canvas()
    panel_w = 332
    clips_grid(p, 0, top, CLIPS_W, bottom)
    vx, vw = CLIPS_W, W - CLIPS_W - panel_w
    bar_h = 88
    img_h = bottom - top - CINE_H - bar_h
    viewer_area(p, vx, top, vw, img_h, banner=False, pad=(24, 12, 58, 78))
    _step_bar_with_tools(p, vx, top + img_h, vw, bar_h)
    A.cine_bar(p, TH, vx, top + img_h + bar_h, vw, CINE_H)

    _panel_bg(p, W - panel_w, top, bottom)
    x, w = W - panel_w + 12, panel_w - 24
    _panel_tabs(p, x, top, w)
    _panel_companion(p, x, top, w, bottom)
    status(p)
    return cv.save(OUT / "13-tool-in-step.png")


def render_overview():
    """Contact sheet: the three concepts side by side with their trade-offs."""
    from kit import Canvas as _Canvas

    tiles = [
        ("11-active-tool.png", "Активный инструмент", "ряд = значки, у выбранного — свои опции"),
        ("12-two-tiers.png", "Две полосы", "6 закреплённых действий с подписями + один полный список в панели"),
        ("13-tool-in-step.png", "Инструмент в полосе шага", "нет отдельного ряда: действия живут в шаге"),
    ]
    tw_, gap = 520, 12
    cv = _Canvas(gap + len(tiles) * (tw_ + gap), 380, 1.0, bg=TH["bg0"])
    p = cv.p
    x = gap
    for name, head, sub in tiles:
        rrect(p, x, gap, tw_, 356, 8, fill=TH["bg1"], stroke=TH["line"])
        text(p, head, x + 14, gap + 12, 15, 600, TH["text"], w=tw_ - 28, h=22)
        text(p, sub, x + 14, gap + 36, 11, 400, TH["text2"], w=tw_ - 28, h=18, elide=True)
        from PySide6.QtGui import QImage

        img = QImage(str(OUT / name))
        if not img.isNull():
            target = QRectF(x + 14, gap + 62, tw_ - 28, 280)
            p.drawImage(target, img, QRectF(0, 0, img.width(), img.height()))
            p.setPen(C(TH["line"]))
            p.drawRect(target)
        x += tw_ + gap
    return cv.save(OUT / "10-overview.png")
