"""Three quick-access concepts prompted by the Windows 10 UI review.

These are standalone QPainter mockups, not live application widgets. The goal is
that the common measurement actions and anatomy groups stay visible, with no
"General / LV / Aorta" dropdown needed to find an action.

Run from this directory:
    LD_LIBRARY_PATH=$V/stubs QT_QPA_PLATFORM=offscreen $V/bin/python quick_access_run.py

The runner starts a fresh process for each canvas; this avoids PySide6's
``none_dealloc`` shutdown issue after many QPainter calls.
"""
from __future__ import annotations

from pathlib import Path

import screen_a as A
from common import button, pill, search_field, section_label, toggle
from kit import C, QRectF, hline, icon, rrect, text, tw, vline
from lay_common import TH, W, clips_grid, status, step_bar, viewer_area
from lay_final import CLIPS_W, frame

OUT = Path(__file__).resolve().parents[2] / "docs/images/quick-access-concepts"

# Tool labels and accelerators used consistently across the concepts.
TOOLS = [
    ("l-mouse-pointer-2", "Указатель", None),
    ("l-ruler", "Калипер", "L"),
    ("l-square-dashed", "Площадь", "A"),
    ("l-spline", "Контур", "C"),
    ("l-audio-waveform", "Допплер", "V"),
    ("l-crosshair", "Маркер", "K"),
    ("l-sparkles", "Авто-контур", None),
    ("l-rotate-ccw", "Отменить", "Ctrl+Z"),
]
ANATOMY = [("ЛЖ", "14"), ("ЛП", "5"), ("ПЖ", "6"), ("Аорта", "9"), ("МК", "9"), ("ТК", "7"), ("Общее", "6"), ("Ещё", "12")]
LV_ITEMS = [
    ("МЖП", "l-ruler", "1"), ("КДР ЛЖ", "l-ruler", "2"),
    ("ЗСЛЖ", "l-ruler", "3"), ("КСР ЛЖ", "l-ruler", "4"),
    ("КДО · 4-кам.", "l-spline", "5"), ("КСО · 4-кам.", "l-spline", "6"),
]


def _panel_bg(p, x, top, w, bottom):
    p.fillRect(QRectF(x, top, w, bottom - top), C(TH["bg1"]))
    vline(p, x, top, bottom - top, TH["line"])


def _anatomy_chips(p, x, y, w, *, selected="ЛЖ", compact=False):
    """Always-visible anatomy chips; no dropdown or collapsing menu."""
    gap = 5
    h = 25 if compact else 29
    pad = 9 if compact else 11
    cx = x
    # Leave a visible sideways-scroll affordance rather than hiding categories in a menu.
    max_x = x + w - 25
    overflow = False
    for label, count in ANATOMY:
        label_w = tw(label, 10.5, 600 if label == selected else 500)
        count_w = tw(count, 9, 600) + 8
        bw = label_w + count_w + pad * 2 + 4
        if cx + bw > max_x:
            overflow = True
            break
        active = label == selected
        rrect(p, cx, y, bw, h, 6, fill=C(TH["accent"], .18) if active else TH["bg2"],
              stroke=C(TH["accent"], .58) if active else TH["line"])
        text(p, label, cx + pad, y, 10.5, 600 if active else 500,
             TH["accent_text"] if active else TH["text2"], w=label_w + 4, h=h, va="c")
        text(p, count, cx + bw - count_w - 5, y, 9, 600,
             TH["text3"], w=count_w, h=h, align="c", va="c")
        cx += bw + gap
    if overflow:
        rrect(p, x + w - 22, y, 22, h, 6, fill=TH["bg3"], stroke=TH["line"])
        icon(p, "l-chevron-right", x + w - 16, y + (h - 12) / 2, 12, TH["text2"])
    return h


def _tool_tile(p, x, y, w, h, label, glyph, key=None, *, active=False, muted=False, sub=None):
    """Labeled single-click action with a calm selected state and visible shortcut."""
    bg = C(TH["accent"], .16) if active else TH["bg2"]
    border = C(TH["accent"], .54) if active else TH["line"]
    rrect(p, x, y, w, h, 7, fill=bg, stroke=border)
    fg = TH["accent_text"] if active else (TH["text3"] if muted else TH["text"])
    icon(p, glyph, x + 10, y + (h - 17) / 2, 17, fg)
    label_y = y + (5 if sub else 0)
    text(p, label, x + 35, label_y, 10.5, 600 if active else 500, fg,
         w=w - 64 - (32 if key else 0), h= h - (10 if sub else 0), va="c", elide=True)
    if sub:
        text(p, sub, x + 35, y + h - 15, 8.5, 400, TH["text3"], w=w - 48, h=11, va="c", elide=True)
    if key:
        key_w = min(39, tw(key, 8.5, 600) + 10)
        rrect(p, x + w - key_w - 5, y + (h - 16) / 2, key_w, 16, 4,
              fill=TH["bg3"], stroke=TH["line2"])
        text(p, key, x + w - key_w - 5, y + (h - 16) / 2, 8.5, 600,
             TH["text3"], w=key_w, h=16, align="c", va="c")


def _viewer(p, x, top, w, bottom, *, toolrow=None, step=True):
    y = top
    if toolrow == "labeled":
        hh = 48
        p.fillRect(QRectF(x, y, w, hh), C(TH["bg1"]))
        hline(p, x, y + hh - 1, w, TH["line"])
        bx = x + 9
        by = y + 8
        for i, (glyph, label, key) in enumerate(TOOLS):
            bw = button(p, bx, by, TH, label, glyph,
                        "tinted" if label == "Контур" else "filled", h=31,
                        size=10.5, kbd_s=key, weight=600 if label == "Контур" else 500)
            bx += bw + 3
            if i in (0, 3, 5):
                bx += 5
                vline(p, bx, by + 6, 19, TH["line2"])
                bx += 7
        y += hh
    elif toolrow == "compact":
        A.viewer_toolbar(p, TH, x, y, w, 42)
        y += 42
    cine_h, step_h = 66, (58 if step else 0)
    img_h = bottom - cine_h - step_h - y
    viewer_area(p, x, y, w, img_h, banner=False, pad=(24, 12, 58, 76))
    if step:
        step_bar(p, x, y + img_h, w, step_h)
    A.cine_bar(p, TH, x, bottom - cine_h, w, cine_h)


def _screen_base(*, gallery=True):
    cv, p, top, bottom = frame()
    if gallery:
        clips_grid(p, 0, top, CLIPS_W, bottom, border="right")
        return cv, p, top, bottom, CLIPS_W
    return cv, p, top, bottom, 0


def render_01_labeled_toolbar():
    """Concept 1: labeled, grouped one-click tools above the viewer."""
    cv, p, top, bottom, vx = _screen_base()
    panel_w = 378
    vw = W - vx - panel_w
    _viewer(p, vx, top, vw, bottom, toolrow="labeled")
    _panel_bg(p, W - panel_w, top, panel_w, bottom)
    x, w = W - panel_w + 12, panel_w - 24
    # Clear panel destinations, not a nested drop-down menu.
    tabs = [("Измерения", True), ("Расчёты", False), ("DICOM", False)]
    tx = x
    for label, active in tabs:
        tw_ = tw(label, 11.5, 600 if active else 500) + 16
        text(p, label, tx, top + 3, 11.5, 600 if active else 500,
             TH["text"] if active else TH["text2"], w=tw_, h=34, va="c")
        if active:
            rrect(p, tx, top + 35, tw_ - 4, 2, 1, fill=TH["accent"])
        tx += tw_ + 8
    hline(p, W - panel_w, top + 38, panel_w, TH["line"])
    search_y = top + 48
    search_field(p, x, search_y, w, 31, "Найти измерение или действие…", TH, kbd_s="/", size=10.5)
    cy = search_y + 40
    _anatomy_chips(p, x, cy, w, compact=True)
    cy += 35
    text(p, "ЛЕВЫЙ ЖЕЛУДОЧЕК", x, cy, 9, 700, TH["text3"], spacing=.6)
    text(p, "6 из 14", W - panel_w + panel_w - 16 - tw("6 из 14", 9, 600), cy,
         9, 600, TH["text3"])
    cy += 17
    # Rows give the operator a generous hit target and keep all common measurements in view.
    for i, (label, glyph, key) in enumerate(LV_ITEMS):
        _tool_tile(p, x, cy, w, 34, label, glyph, key, active=(i == 5),
                   sub="текущий шаг · Симпсон" if i == 5 else None)
        cy += 39 if i != 5 else 45
    cy += 4
    hline(p, x, cy, w, TH["line"])
    cy += 10
    section_label(p, x, cy, "ПРОТОКОЛЫ", TH, size=9)
    cy += 17
    for label, done, total, active in (("Симпсон бипланово", 1, 4, True), ("ЛЖ линейно", 2, 2, False), ("Объём ЛП", 0, 2, False)):
        rrect(p, x, cy, w, 42, 7, fill=TH["bg2"] if active else None,
              stroke=C(TH["accent"], .4) if active else TH["line"])
        icon(p, "l-heart-pulse", x + 9, cy + 12, 16, TH["accent_text"] if active else TH["text3"])
        text(p, label, x + 33, cy, 10, 600 if active else 500,
             TH["text"] if active else TH["text2"], w=w - 83, h=42, va="c", elide=True)
        pill(p, x + w - 42, cy + 12, f"{done}/{total}", TH["text2"], TH["bg3"], h=18, size=8.5)
        cy += 47
    # At the foot, compact status and action remain visible.
    yb = bottom - 51
    hline(p, W - panel_w, yb, panel_w, TH["line"])
    text(p, "Нормы", x + 1, yb + 17, 10, 500, TH["text2"])
    toggle(p, x + w - 37, yb + 15, True, TH, w=32, h=18)
    status(p)
    return cv.save(OUT / "01-labeled-toolbar.png")


def render_02_pinned_tool_rail():
    """Concept 2: persistent left-side tool rail plus searchable anatomy panel."""
    cv, p, top, bottom, _ = _screen_base()
    rail_w, panel_w = 74, 360
    rx = CLIPS_W
    vx = rx + rail_w
    vw = W - vx - panel_w
    # Rail: actions remain fixed, text labels don't rely on hover.
    _panel_bg(p, rx, top, rail_w, bottom)
    y = top + 10
    rail_tools = [TOOLS[0], ("l-move", "Сдвиг", None), ("l-zoom-in", "Лупа", None),
                  ("l-sun-medium", "Яркость", None), None, *TOOLS[1:7]]
    for item in rail_tools:
        if item is None:
            hline(p, rx + 13, y + 4, rail_w - 26, TH["line2"])
            y += 11
            continue
        glyph, label, key = item
        active = label == "Контур"
        if active:
            rrect(p, rx + 5, y, rail_w - 10, 48, 7,
                  fill=C(TH["accent"], .16), stroke=C(TH["accent"], .48))
        icon(p, glyph, rx + rail_w / 2 - 8, y + 4, 16,
             TH["accent_text"] if active else TH["text2"])
        text(p, label, rx + 2, y + 23, 8.5, 600 if active else 500,
             TH["accent_text"] if active else TH["text2"], w=rail_w - 4, h=17, align="c", va="c", elide=True)
        if key:
            text(p, key, rx + rail_w - 13, y + 3, 7.5, 700, TH["text3"], w=11, h=10, align="r")
        y += 51
    _viewer(p, vx, top, vw, bottom, toolrow=None)
    _panel_bg(p, W - panel_w, top, panel_w, bottom)
    x, w = W - panel_w + 12, panel_w - 24
    text(p, "БЫСТРЫЙ ДОСТУП", x, top + 5, 10, 700, TH["text"], spacing=.2)
    text(p, "Настроить", x + w - 55, top + 5, 9, 500, TH["accent_text"], w=55, h=20, align="r", va="c")
    search_field(p, x, top + 31, w, 31, "Поиск: КДР, LVEDD, СДЛЖ…", TH, kbd_s="/", size=10.5)
    # A visibly persistent anatomy selector; selected family uses a single click.
    y = top + 73
    _anatomy_chips(p, x, y, w, compact=True)
    y += 38
    section_label(p, x, y, "ИЗБРАННОЕ · 1–6", TH, size=9)
    y += 20
    favs = [("МЖП", "l-ruler", "1"), ("КДР ЛЖ", "l-ruler", "2"), ("ЗСЛЖ", "l-ruler", "3"),
            ("КСР ЛЖ", "l-ruler", "4"), ("КДО · 4-кам.", "l-spline", "5"), ("КСО · 4-кам.", "l-spline", "6")]
    for i, (label, glyph, key) in enumerate(favs):
        row = i // 2
        col = i % 2
        bw = (w - 7) / 2
        _tool_tile(p, x + col * (bw + 7), y + row * 44, bw, 38, label, glyph, key,
                   active=False, sub="готово" if i == 0 else None)
    y += 3 * 44 + 8
    hline(p, x, y, w, TH["line"])
    y += 10
    section_label(p, x, y, "ПРОТОКОЛЫ", TH, size=9)
    y += 18
    for label, done, total, active in (("Симпсон бипланово", 1, 4, True), ("Диастолическая функция", 5, 7, False)):
        rrect(p, x, y, w, 50, 8, fill=TH["bg2"] if active else None,
              stroke=C(TH["accent"], .42) if active else TH["line"])
        text(p, label, x + 10, y + 6, 10, 600, TH["text"], w=w - 64, h=17, elide=True)
        text(p, f"{done}/{total}", x + w - 48, y + 6, 9, 600,
             TH["accent_text"] if active else TH["text3"], w=38, h=17, align="r")
        progress_w = w - 20
        rrect(p, x + 10, y + 32, progress_w, 4, 2, fill=TH["bg3"])
        rrect(p, x + 10, y + 32, progress_w * done / total, 4, 2, fill=TH["accent"])
        y += 56
    yb = bottom - 51
    hline(p, W - panel_w, yb, panel_w, TH["line"])
    text(p, "Нормы", x + 1, yb + 17, 10, 500, TH["text2"])
    toggle(p, x + w - 37, yb + 15, True, TH, w=32, h=18)
    status(p)
    return cv.save(OUT / "02-pinned-rail.png")


def render_03_anatomy_board():
    """Concept 3: visible anatomy board and direct measurement tiles, no accordion."""
    cv, p, top, bottom, vx = _screen_base()
    panel_w = 405
    vw = W - vx - panel_w
    _viewer(p, vx, top, vw, bottom, toolrow="compact")
    _panel_bg(p, W - panel_w, top, panel_w, bottom)
    x, w = W - panel_w + 12, panel_w - 24
    # Header tabs identify major tasks; no nested menu.
    for i, label in enumerate(("Измерения", "Расчёты", "Управление")):
        bx = x + i * 120
        active = i == 0
        text(p, label, bx, top + 2, 10.5, 600 if active else 500,
             TH["text"] if active else TH["text2"], w=112, h=30, va="c")
        if active:
            rrect(p, bx, top + 31, min(100, tw(label, 10.5, 600)), 2, 1, fill=TH["accent"])
    hline(p, W - panel_w, top + 35, panel_w, TH["line"])
    search_field(p, x, top + 43, w, 32, "Поиск измерений…  (/) ", TH, size=10.5)
    y = top + 84
    section_label(p, x, y, "АНАТОМИЯ", TH, size=9)
    text(p, "Выберите область", x + w - 112, y, 9, 500, TH["text3"], w=112, h=15, align="r")
    y += 18
    # Two-row board keeps every family directly visible.
    gap, cols, tile_h = 6, 4, 44
    bw = (w - gap * (cols - 1)) / cols
    for i, (label, count) in enumerate(ANATOMY):
        row, col = divmod(i, cols)
        bx, by = x + col * (bw + gap), y + row * (tile_h + 6)
        active = label == "ЛЖ"
        rrect(p, bx, by, bw, tile_h, 7,
              fill=C(TH["accent"], .16) if active else TH["bg2"],
              stroke=C(TH["accent"], .55) if active else TH["line"])
        icon(p, ("l-heart-pulse" if label in ("ЛЖ", "ЛП", "ПЖ") else "l-scan-line"), bx + 8, by + 7, 14,
             TH["accent_text"] if active else TH["text3"])
        text(p, label, bx + 27, by + 4, 10, 600 if active else 500,
             TH["accent_text"] if active else TH["text2"], w=bw - 31, h=20, va="c")
        text(p, count, bx + 27, by + 23, 8, 500, TH["text3"], w=bw - 32, h=13, va="c")
    y += 2 * (tile_h + 6) + 8
    # One-tap actions are grouped by anatomy and shown as clean, familiar rows.
    hline(p, x, y, w, TH["line"])
    y += 9
    text(p, "ЛЕВЫЙ ЖЕЛУДОЧЕК", x, y, 9, 700, TH["text3"], spacing=.5)
    text(p, "Избранное  ★", x + w - 82, y, 9, 500, TH["accent_text"], w=82, h=15, align="r")
    y += 19
    cols, gap, th = 2, 7, 39
    bw = (w - gap) / 2
    for i, (label, glyph, key) in enumerate(LV_ITEMS):
        row, col = divmod(i, cols)
        _tool_tile(p, x + col * (bw + gap), y + row * (th + 6), bw, th, label, glyph, key,
                   active=(i == 5), sub="Шаг 2/4" if i == 5 else None)
    y += 3 * (th + 6) + 2
    hline(p, x, y, w, TH["line"])
    y += 10
    section_label(p, x, y, "ПРОТОКОЛЫ · БЫСТРЫЙ СТАРТ", TH, size=9)
    y += 19
    for i, (label, detail, done) in enumerate((("Симпсон бипланово", "4 шага", "1/4"),
                                               ("ЛЖ линейно", "КДР · КСР · МЖП · ЗСЛЖ", "2/2"))):
        rrect(p, x, y, w, 44, 7, fill=TH["bg2"] if i == 0 else None,
              stroke=C(TH["accent"], .42) if i == 0 else TH["line"])
        icon(p, "l-heart-pulse", x + 9, y + 13, 16, TH["accent_text"] if i == 0 else TH["text3"])
        text(p, label, x + 34, y + 4, 10, 600, TH["text"], w=w - 91, h=18, va="c", elide=True)
        text(p, detail, x + 34, y + 23, 8.5, 400, TH["text3"], w=w - 94, h=14, va="c", elide=True)
        text(p, done, x + w - 47, y + 12, 9, 600, TH["accent_text"], w=36, h=20, align="r", va="c")
        y += 49
    yb = bottom - 51
    hline(p, W - panel_w, yb, panel_w, TH["line"])
    text(p, "Нормы", x + 1, yb + 17, 10, 500, TH["text2"])
    toggle(p, x + w - 37, yb + 15, True, TH, w=32, h=18)
    status(p)
    return cv.save(OUT / "03-anatomy-board.png")
