"""Shared building blocks for round 2: layout variations on top of variant A.

Round 2 fixes the user's choices — neutral graphite palette (THEME_A), Windows 11
window chrome, variant A as the base — and only varies where panels and buttons go.
Output: docs/images/layout-variants/.
"""

from __future__ import annotations

import screen_a as A
from common import (
    CLIPS,
    KEY_RESULTS,
    PROTO_ICON,
    PROTOCOLS,
    PT,
    THEME_A,
    C,
    QRectF,
    button,
    echo_view,
    hline,
    icon,
    info_overlay,
    kbd,
    pill,
    rrect,
    scrollbar,
    search_field,
    section_label,
    status_icon,
    text,
    thumb,
    tw,
    vline,
    win_controls,
)
from kit import REPO, logo, vgrad

OUT2 = REPO / "docs/images/layout-variants"
TH = THEME_A
S = 1.5
W, H = 1600, 1000
TB, SB = A.TB, A.SB  # 38 / 26
BY_ID = {c[0]: c for c in CLIPS}
TABS = [("l-heart-pulse", PT["short"], PT["date"]), ("l-heart-pulse", "Сидоров А. П.", "07.10.2026")]

CLIP_GROUPS = [
    ("2D", "14", ["c1", "c2", "c3", "c4", "c11", "c12", "c13", "c14"]),
    ("Допплер", "8", ["c7", "c8", "c16", "c15", "c9", "c10", "c6"]),
    ("M-режим", "2", ["c5", "c18"]),
]


def title(p, tabs=None, active=0):
    A.title_bar(p, TH, tabs or TABS, active)


def status(p, saved="10:42", left_extra=None):
    left = [("l-circle-check", f"Сохранено · {saved}", TH["ok"]), (None, "Калибровка: DICOM · 0,28 мм/пикс.", TH["text2"])]
    left += left_extra or [(None, "Кадры: 83/83 декодировано", TH["text2"])]
    A.status_bar(p, TH, left, [("l-triangle-alert", "Только для исследований", TH["warn"]), (None, "SonoForge 0.4.0", TH["text3"])])


def rbutton(p, xr, y, label, ico=None, kind="ghost", h=32, **kw) -> float:
    """Right-aligned button: draws so that it ends at xr, returns its left x."""
    bw = button(p, 0, -200, TH, label, ico, kind, h=h, **kw)
    button(p, xr - bw, y, TH, label, ico, kind, h=h, **kw)
    return xr - bw


def segmented(p, x, y, items, sel, h=28, size=12, pad=14, bg=None) -> float:
    widths = [tw(s, size, 600) + 2 * pad for s in items]
    w = sum(widths) + 4
    rrect(p, x, y, w, h, 7, fill=bg or TH["bg2"], stroke=TH["line"])
    cx = x + 2
    for i, (s, sw_) in enumerate(zip(items, widths)):
        if i == sel:
            rrect(p, cx, y + 2, sw_, h - 4, 6, fill=TH["bg3"], stroke=TH["line2"])
        text(p, s, cx, y, size, 600 if i == sel else 500, TH["text"] if i == sel else TH["text2"], w=sw_, h=h, align="c", va="c")
        cx += sw_
    return w


# ───────────────────────────── patient line (compact, one row) ─────────────────────────────


def patient_line(p, y, h=40, actions=True, mode=None, report_primary=True, mode_items=("Изображения", "Отчёт")):
    """One-row patient strip. ``mode`` = index for the «Изображения | Отчёт» switch (None = no switch)."""
    th = TH
    p.fillRect(QRectF(0, y, W, h), C(th["bg1"]))
    hline(p, 0, y + h - 1, W, th["line"])
    x = 16
    x += text(p, PT["name"], x, y, 14, 600, th["text"], w=400, h=h, va="c") + 10
    s = f"{PT['sex']} · {PT['age']} · ID {PT['pid']}"
    x += text(p, s, x, y, 12, 500, th["text2"], w=300, h=h, va="c") + 14
    for lab, val, edit in (("Рост", PT["height"], False), ("Вес", PT["weight"], False), ("ППТ", PT["bsa"], True), ("ЧСС", PT["hr"], False)):
        vline(p, x, y + 12, h - 24, th["line2"])
        x += 12
        x += text(p, lab, x, y, 11.5, 500, th["text3"], w=60, h=h, va="c") + 5
        x += text(p, val, x, y, 12.5, 600, th["text"], w=90, h=h, va="c", tnum=True)
        if edit:
            icon(p, "l-pencil", x + 5, y + h / 2 - 6, 12, th["text3"])
            x += 17
        x += 12
    vline(p, x, y + 12, h - 24, th["line2"])
    x += 12
    text(p, f"{PT['date']} {PT['time']} · {PT['device']}", x, y, 12, 500, th["text2"], w=260, h=h, va="c", tnum=True)
    xr = W - 14
    bh = min(30, h - 8)
    by = y + (h - bh) / 2
    if mode is not None:
        items = list(mode_items)
        sw_ = sum(tw(s, 12, 600) + 28 for s in items) + 4
        segmented(p, xr - sw_, by, items, mode, h=bh)
        return
    if actions:
        if report_primary:
            xr = rbutton(p, xr, by, "Отчёт", "l-file-text", "primary", h=bh, weight=600) - 10
        vline(p, xr, y + 11, h - 22, th["line2"])
        xr -= 8
        for lab, ico in (("Презентация", "l-presentation"), ("Сравнить", "l-columns-2"), ("PACS", "l-cloud-download"), ("Открыть", "l-folder-open")):
            xr = rbutton(p, xr, by, lab, ico, "ghost", h=bh) - 2


# ───────────────────────────── clips: grid column and filmstrip ─────────────────────────────


def clips_grid(p, x, top, w, bottom, selected="c1", border="right"):
    th = TH
    p.fillRect(QRectF(x, top, w, bottom - top), C(th["bg1"]))
    vline(p, x + w - 1 if border == "right" else x, top, bottom - top, th["line"])
    y = top + 12
    text(p, "Клипы", x + 14, y, 13, 600, th["text"])
    pill(p, x + 14 + tw("Клипы", 13, 600) + 8, y - 1, "24", th["text2"], th["bg3"], h=18, size=10.5)
    icon(p, "l-layout-grid", x + w - 52, y, 15, th["accent"])
    icon(p, "l-list", x + w - 30, y, 15, th["text3"])
    y += 30
    segs = [("Все", "24"), ("2D", "14"), ("Доп.", "8"), ("M", "2")]
    sx, sw_ = x + 12, w - 24
    rrect(p, sx, y, sw_, 26, 6, fill=th["bg2"], stroke=th["line"])
    seg_w = sw_ / len(segs)
    for i, (lab, n) in enumerate(segs):
        xx = sx + i * seg_w
        if i == 0:
            rrect(p, xx + 2, y + 2, seg_w - 4, 22, 5, fill=th["bg3"], stroke=th["line2"])
        lw_ = tw(lab, 11, 600) + 3 + tw(n, 10)
        lx = xx + (seg_w - lw_) / 2
        lx += text(p, lab, lx, y, 11, 600 if i == 0 else 500, th["text"] if i == 0 else th["text2"], w=60, h=26, va="c") + 3
        text(p, n, lx, y, 10, 500, th["text3"], w=20, h=26, va="c")
    y += 38
    tw_, th_ = (w - 28 - 8) / 2, (w - 28 - 8) / 2 * 0.70
    p.save()
    p.setClipRect(QRectF(x, y - 4, w, bottom - y + 4))
    for gname, gn, ids in CLIP_GROUPS:
        section_label(p, x + 14, y, f"{gname} · {gn}", th, size=9.5)
        icon(p, "l-chevron-down", x + w - 30, y - 1, 13, th["text3"])
        y += 18
        for k, cid in enumerate(ids):
            cx = x + 14 + (k % 2) * (tw_ + 8)
            cy = y + (k // 2) * (th_ + 10)
            thumb(p, cx, cy, tw_, th_, BY_ID[cid], th, selected=(cid == selected), r=6)
        y += ((len(ids) + 1) // 2) * (th_ + 10) + 8
    p.restore()
    p.fillRect(QRectF(x, bottom - 36, w - 1, 36), vgrad(bottom - 36, bottom, [(0, C(th["bg1"], 0.0)), (1, C(th["bg1"], 1.0))]))
    scrollbar(p, x + w - 7, top + 80, bottom - top - 90, 0.0, 0.62, th["text2"], alpha=0.28)


def filmstrip(p, x, y, w, h, selected="c1"):
    """Horizontal clip tray, grouped by mode."""
    th = TH
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y, w, th["line"])
    text(p, "Клипы", x + 14, y + 10, 12.5, 600, th["text"])
    pill(p, x + 14, y + 32, "24", th["text2"], th["bg3"], h=18, size=10.5)
    icon(p, "l-filter", x + 50, y + 33, 15, th["text3"])
    icon(p, "l-panel-bottom", x + 14, y + h - 26, 15, th["text3"])
    text(p, "свернуть", x + 34, y + h - 28, 10.5, 500, th["text3"])
    cx = x + 104
    th_h = h - 34
    th_w = th_h * 1.36
    lim = x + w - 70
    rest = 0
    for gname, gn, ids in CLIP_GROUPS:
        if cx + th_w > lim:
            rest += len(ids)
            continue
        vline(p, cx - 9, y + 10, h - 20, th["line2"])
        section_label(p, cx, y + 7, f"{gname} · {gn}", th, size=9)
        shown = 0
        for cid in ids[:5]:
            if cx + th_w > lim:
                break
            thumb(p, cx, y + 24, th_w, th_h, BY_ID[cid], th, selected=(cid == selected), r=6)
            cx += th_w + 7
            shown += 1
        left = len(ids) - shown
        if left and shown == 5 and cx + 40 < lim:
            rrect(p, cx, y + 24, 40, th_h, 7, fill=th["bg2"], stroke=th["line"])
            text(p, f"+{left}", cx, y + 24, 12, 600, th["text2"], w=40, h=th_h, align="c", va="c")
            cx += 47
        else:
            rest += left
        cx += 18
    if rest > 0:
        bx = x + w - 62
        rrect(p, bx, y + 24, 50, th_h, 7, fill=th["bg2"], stroke=th["line"])
        text(p, f"+{rest}", bx, y + 24, 13, 600, th["text2"], w=50, h=th_h - 14, align="c", va="c")
        text(p, "ещё", bx, y + 24 + th_h - 26, 10, 500, th["text3"], w=50, h=16, align="c", va="c")


# ───────────────────────────── tools: docked rail, command bar ─────────────────────────────

RAIL_TOOLS = [
    ("l-mouse-pointer-2", "Выбор", None),
    ("l-move", "Сдвиг", None),
    ("l-zoom-in", "Лупа", None),
    ("l-sun-medium", "Яркость", None),
    None,
    ("l-ruler", "Линейка", "L"),
    ("l-square-dashed", "Площадь", "A"),
    ("l-spline", "Контур", "C"),
    ("l-audio-waveform", "Допплер", "V"),
    None,
    ("l-crosshair", "Маркер", "K"),
    ("l-sparkles", "Авто", None),
]


def tool_rail_docked(p, x, top, w, bottom, active="l-spline", labels=True):
    th = TH
    p.fillRect(QRectF(x, top, w, bottom - top), C(th["bg1"]))
    vline(p, x + w - 1, top, bottom - top, th["line"])
    y = top + 10
    bh = 52 if labels else 40
    for t in RAIL_TOOLS:
        if t is None:
            hline(p, x + 14, y + 4, w - 28, th["line2"])
            y += 10
            continue
        ico, lab, key = t
        act = ico == active
        dis = ico == "l-audio-waveform"
        if act:
            rrect(p, x + 6, y, w - 12, bh, 8, fill=C(th["accent"], 0.16), stroke=C(th["accent"], 0.5))
        col = th["accent_text"] if act else (th["text3"] if dis else th["text2"])
        icon(p, ico, x + w / 2 - 9, y + (9 if labels else 11), 18, col)
        if labels:
            text(p, lab, x, y + 31, 10, 600 if act else 500, col, w=w, h=14, align="c", va="c")
        if key:
            text(p, key, x + w - 17, y + 5, 8.5, 700, th["text3"])
        y += bh + 3
    # bottom: panel toggles
    for i, ico in enumerate(("l-panel-left", "l-panel-right")):
        icon(p, ico, x + w / 2 - 8, bottom - 56 + i * 26, 16, th["text3"])


def command_bar(p, y, h=46):
    """Windows 11-style command bar: labelled buttons in groups, primary action on the right."""
    th = TH
    p.fillRect(QRectF(0, y, W, h), C(th["bg1"]))
    hline(p, 0, y + h - 1, W, th["line"])
    bh = 32
    by = y + (h - bh) / 2
    x = 10

    def b(label, ico, active=False, caret=False, disabled=False, kbd_s=None):
        nonlocal x
        fg = th["text3"] if disabled else None
        bw = button(p, x, by, th, label, ico, "ghost", h=bh, active=active, fg=fg, weight=600 if active else 500, kbd_s=kbd_s)
        if caret:
            icon(p, "l-chevron-down", x + bw - 4, by + 10, 12, th["text3"])
            bw += 12
        x += bw + 2

    def sep():
        nonlocal x
        x += 5
        vline(p, x, by + 6, bh - 12, th["line2"])
        x += 7

    b("Открыть", "l-folder-open", caret=True)
    b("PACS", "l-cloud-download")
    sep()
    for ico in ("l-mouse-pointer-2", "l-move", "l-zoom-in", "l-sun-medium"):
        b(None, ico)
    sep()
    b("Линейка", "l-ruler")
    b("Площадь", "l-square-dashed")
    b("Контур", "l-spline", active=True, kbd_s="C")
    b("Допплер", "l-audio-waveform", disabled=True)
    b(None, "l-crosshair")
    sep()
    b("Авто-контур", "l-sparkles")
    sep()
    b("Сравнить", "l-columns-2")
    b("Презентация", "l-presentation")
    xr = W - 12
    xr = rbutton(p, xr, by, "Отчёт", "l-file-text", "primary", h=bh, weight=600) - 8
    for ico in ("l-panel-right", "l-panel-bottom", "l-panel-left"):
        xr -= 32
        icon(p, ico, xr + 8, by + 8, 16, th["text2"] if ico != "l-panel-bottom" else th["text3"])
    xr -= 4
    vline(p, xr, by + 6, bh - 12, th["line2"])
    xr -= 34
    icon(p, "l-ellipsis", xr + 8, by + 8, 16, th["text2"])


# ───────────────────────────── viewer pieces ─────────────────────────────


def viewer_area(p, x, y, w, h, pad=None, banner=True, chips=True, info=True, banner_w=610, lv_label="КДО · 4-кам.  112 мл", banner_msg=None, banner_dx=0):
    th = TH
    rect = echo_view(p, x, y, w, h, th, pad=pad or ((96 if banner else 26), 18, 70, 90), lv_label=lv_label)
    if info:
        info_overlay(p, x + 16, y + 14, ["SAMSUNG RS85 · PM1-6A", "2D · 16 см · 30 Гц · Gn 54 · DR 60"], lh=15)
        text(p, "Кадр 1 / 83 · КД", x + 16, y + 46, 10.5, 600, C(th["accent_text"], 0.9))
    if chips:
        xr = x + w - 16
        s1 = "4-кам."
        wv = pill(p, 0, -100, s1, "#ffffff", C("#000000", 0.6), h=22, size=11.5)
        pill(p, xr - wv, y + 14, s1, "#ffffff", C("#000000", 0.6), h=22, size=11.5, stroke=C("#ffffff", 0.25))
        s2 = "0,28 мм/пикс. · DICOM"
        wv2 = pill(p, 0, -100, s2, th["ok"], C("#000000", 0.6), h=22, size=11, icon_name="l-check")
        pill(p, xr - wv2, y + 42, s2, th["ok"], C("#000000", 0.6), h=22, size=11, icon_name="l-check", weight=500)
    if banner and banner_msg:
        step_banner2(p, x + w / 2 + banner_dx, y + 12, banner_w, banner_msg)
    elif banner:
        A.step_banner(p, th, x + w / 2, y + 12, w=banner_w)
    return rect


def step_banner2(p, cx, y, w, msg):
    """A.step_banner with a custom (shorter) instruction for narrow viewers."""
    th = TH
    x = cx - w / 2
    h = 74
    rrect(p, x, y, w, h, 10, fill=C("#0c0f12", 0.86), stroke=C(th["line2"], 0.9))
    rrect(p, x, y, 4, h, 2, fill=th["accent"])
    tx = x + 18
    xx = tx + text(p, "СИМПСОН БИПЛАНОВО", tx, y + 10, 10, 700, th["text2"], spacing=0.7) + 10
    xx += text(p, "шаг 2 из 4", xx, y + 10, 10.5, 600, th["accent_text"]) + 10
    for st in ("done", "current", "todo", "todo"):
        status_icon(p, xx, y + 10, st, th, size=11)
        xx += 16
    text(p, msg, tx, y + 27, 13.5, 600, th["text"], w=w - 30, h=20, elide=True)
    kx = tx
    for k, lab in (("Enter", "готово"), ("S", "пропустить"), ("Esc", "выйти")):
        kx += kbd(p, kx, y + 50, k, th) + 6
        kx += text(p, lab, kx, y + 50, 11.5, 500, th["text2"], w=200, h=17, va="c") + 14


def step_bar(p, x, y, w, h=58):
    """Protocol step docked under the image (nothing overlaps the picture)."""
    th = TH
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y, w, th["line"])
    rrect(p, x, y + 1, 3, h - 1, 0, fill=th["accent"])
    tx = x + 18
    xx = tx + text(p, "СИМПСОН БИПЛАНОВО", tx, y + 10, 10, 700, th["text2"], spacing=0.7) + 10
    xx += text(p, "шаг 2 из 4", xx, y + 9.5, 10.5, 600, th["accent_text"]) + 10
    for st in ("done", "current", "todo", "todo"):
        status_icon(p, xx, y + 10, st, th, size=11)
        xx += 16
    text(p, "КСО · 4-кам. — кадр конца систолы, обведите эндокард ЛЖ", tx, y + 28, 13.5, 600, th["text"])
    xr = x + w - 14
    xr = rbutton(p, xr, y + 13, "Готово", "l-check", "primary", h=32, weight=600) - 6
    xr -= kbd(p, 0, -100, "Enter", th)
    kbd(p, xr, y + 20, "Enter", th)
    xr -= 12
    xr = rbutton(p, xr, y + 13, "Пропустить", None, "outline", h=32) - 6
    xr = rbutton(p, xr, y + 13, None, "l-undo-2", "ghost", h=32)


# ───────────────────────────── protocol / tool panel (any x, any width) ─────────────────────────────


def proto_panel(p, x, top, w, bottom, border="left", tabs=("Измерения", "Расчёты", "Изображение", "DICOM"), active_tab=0, summary=True, groups=True, simpson=True, header=None):
    th = TH
    p.fillRect(QRectF(x, top, w, bottom - top), C(th["bg1"]))
    vline(p, x if border == "left" else x + w - 1, top, bottom - top, th["line"])
    y = top
    if not tabs and header:
        text(p, header, x + 14, top, 13.5, 600, th["text"], w=200, h=40, va="c")
        icon(p, "l-pin", x + w - 56, top + 12, 15, th["accent_text"])
        icon(p, "l-x", x + w - 30, top + 12, 15, th["text3"])
        hline(p, x, top + 40, w, th["line"])
        y = top + 40
    if tabs:
        tx = x + 14
        for i, t in enumerate(tabs):
            wv = tw(t, 12.5, 600 if i == active_tab else 500)
            text(p, t, tx, top, 12.5, 600 if i == active_tab else 500, th["text"] if i == active_tab else th["text2"], w=wv + 2, h=40, va="c")
            if i == active_tab:
                rrect(p, tx, top + 38, wv, 2, 1, fill=th["accent"])
            tx += wv + 18
        hline(p, x, top + 40, w, th["line"])
        y = top + 40
    y += 12
    search_field(p, x + 12, y, w - 24, 32, "Найти: КДР, LVEDD, СДЛА…", th, kbd_s="/", r=7)
    y += 46
    if not header:
        section_label(p, x + 14, y, "Протоколы", th)
        text(p, "настроить", x + w - 14 - tw("настроить", 11), y - 1, 11, 500, th["text3"])
        y += 20
    else:
        y -= 6
    for key, name, modes, done, total in PROTOCOLS:
        active = key == "simpson" and simpson
        rh = 34
        if active:
            rrect(p, x + 8, y, w - 16, 262, 9, fill=th["bg2"], stroke=C(th["accent"], 0.45))
        icon(p, "r-" + PROTO_ICON[key], x + 18, y + 8, 18, "#ffffff")
        text(p, name, x + 44, y, 12.5, 600 if active else 500, th["text"], w=w - 150, h=rh, va="c", elide=True)
        s = f"{done}/{total}"
        if done == total:
            fg, bg = th["ok"], C(th["ok"], 0.15)
        elif done > 0:
            fg, bg = th["accent_text"], C(th["accent"], 0.14)
        else:
            fg, bg = th["text3"], th["bg3"]
        cw = tw(s, 10.5, 700, tnum=True) + 14
        cx = x + w - 18 - cw
        rrect(p, cx, y + 8, cw, 18, 9, fill=bg)
        text(p, s, cx, y + 8, 10.5, 700, fg, w=cw, h=18, align="c", va="c", tnum=True)
        badges_w = sum(tw(m, 9, 600) + 12 for m in modes)
        name_end = x + 44 + tw(name, 12.5, 600 if active else 500) + 8
        if name_end < cx - 6 - badges_w:
            mx = cx - 6
            for m in reversed(modes):
                mw = tw(m, 9, 600) + 8
                mx -= mw
                rrect(p, mx, y + 10, mw, 14, 3.5, fill=None, stroke=th["line2"])
                text(p, m, mx, y + 10, 9, 600, th["text3"], w=mw, h=14, align="c", va="c")
                mx -= 4
        y += rh
        if active:
            y = A.simpson_card(p, th, x + 18, y + 2, w - 36)
            y += 12
    if groups:
        y += 8
        hline(p, x + 14, y, w - 28, th["line"])
        y += 14
        section_label(p, x + 14, y, "Все измерения", th)
        text(p, "по анатомии", x + w - 14 - tw("по анатомии", 11), y - 1, 11, 500, th["text3"])
        y += 20
        grp = [
            ("LV01", "Левый желудочек", "6/14"),
            ("LA01", "Левое предсердие", "0/5"),
            ("MV01", "Митральный клапан", "3/9"),
            ("AV01", "Аортальный клапан · ВТЛЖ", "0/9"),
            ("TV01", "Трикуспидальный клапан", "2/7"),
            ("RV01", "Правый желудочек", "0/6"),
        ]
        lim = bottom - (150 if summary else 30)
        for ico, name, cnt in grp:
            if y > lim:
                break
            icon(p, "r-" + ico, x + 18, y + 6, 16, "#ffffff")
            text(p, name, x + 44, y, 12, 500, th["text2"], w=w - 100, h=28, va="c", elide=True)
            text(p, cnt, x + w - 44 - tw(cnt, 11, 500, tnum=True), y, 11, 500, th["text3"], w=40, h=28, va="c", tnum=True)
            icon(p, "l-chevron-right", x + w - 32, y + 7, 14, th["text3"])
            y += 28
    if summary:
        summary_block(p, x, bottom - 128, w, bottom)


def summary_block(p, x, sy, w, bottom):
    th = TH
    p.fillRect(QRectF(x + 1, sy, w - 1, bottom - sy), C(th["bg1"]))
    hline(p, x, sy, w, th["line"])
    section_label(p, x + 14, sy + 12, "Сводка", th)
    s = "14 измерений · 6 расчётов"
    text(p, s, x + w - 14 - tw(s, 11), sy + 11, 11, 500, th["text3"])
    cw = (w - 28) / 3
    for i, (lab, val, unit) in enumerate(KEY_RESULTS):
        cx = x + 14 + (i % 3) * cw
        cy = sy + 34 + (i // 3) * 46
        text(p, lab, cx, cy, 10.5, 500, th["text3"])
        if val == "—":
            text(p, "—", cx, cy + 14, 16, 600, th["text3"])
            text(p, unit, cx + 22, cy + 19, 10.5, 500, th["text3"])
        else:
            vw = text(p, val, cx, cy + 14, 16, 600, th["text"], tnum=True)
            text(p, unit, cx + vw + 4, cy + 19, 10.5, 500, th["text2"])


def side_tabs(p, x, top, bottom, items, active, w=44):
    """Vertical icon strip at the window edge that switches the side panel."""
    th = TH
    p.fillRect(QRectF(x, top, w, bottom - top), C(th["bg0"]))
    vline(p, x, top, bottom - top, th["line"])
    y = top + 8
    for i, (ico, lab, badge) in enumerate(items):
        if ico is None:
            hline(p, x + 10, y + 4, w - 20, th["line2"])
            y += 10
            continue
        act = i == active
        if act:
            rrect(p, x + 5, y, w - 10, 40, 8, fill=C(th["accent"], 0.16))
            rrect(p, x + 1, y + 10, 3, 20, 1.5, fill=th["accent"])
        icon(p, ico, x + w / 2 - 9, y + 11, 18, th["accent_text"] if act else th["text2"])
        if badge:
            bw_ = tw(badge, 8.5, 700) + 7
            rrect(p, x + w - 6 - bw_, y + 4, bw_, 13, 6.5, fill=th["accent"] if act else th["bg3"])
            text(p, badge, x + w - 6 - bw_, y + 4, 8.5, 700, th["on_accent"] if act else th["text2"], w=bw_, h=13, align="c", va="c")
        y += 46


def win_title(p, title_s, sub=None, h=34, bg=None, search=None, controls=True):
    """Plain Windows 11 title bar for secondary windows (dialogs, reference)."""
    th = TH
    p.fillRect(QRectF(0, 0, W, h), C(bg or th["bg0"]))
    logo(p, 12, (h - 18) / 2, 18, light=True)
    x = 42 + text(p, title_s, 42, 0, 12.5, 600, th["text"], w=600, h=h, va="c")
    if sub:
        text(p, " · " + sub, x, 0, 12.5, 400, th["text3"], w=500, h=h, va="c")
    if search:
        sw_ = 420
        search_field(p, W / 2 - sw_ / 2, (h - 26) / 2, sw_, 26, search, th, kbd_s="Ctrl F", r=7, bg=th["bg2"], size=12)
    if controls:
        win_controls(p, W, 0, h, th["text2"])


def viewer_corner(p, xr, yb, items=("l-rotate-ccw", "l-columns-2", "l-maximize-2")):
    """Small zoom / layout cluster in the image corner (when there is no viewer toolbar)."""
    th = TH
    w = 74 + 30 * len(items)
    x, y = xr - w, yb - 32
    rrect(p, x, y, w, 32, 8, fill=C("#0b0d0f", 0.82), stroke=C("#ffffff", 0.10))
    text(p, "100 %", x + 10, y, 11.5, 600, th["text2"], w=50, h=32, va="c", tnum=True)
    icon(p, "l-chevron-down", x + 52, y + 10, 12, th["text3"])
    vline(p, x + 70, y + 8, 16, C("#ffffff", 0.12))
    for i, ico in enumerate(items):
        icon(p, ico, x + 78 + i * 30, y + 8, 16, th["text2"])


def wrap_lines(s, size, weight, width) -> int:
    """How many lines ``text(..., wrap=True)`` will take (greedy word wrap)."""
    lines, cur = 1, 0.0
    for word in s.split(" "):
        ww = tw(word + " ", size, weight)
        if cur + ww > width and cur > 0:
            lines += 1
            cur = 0.0
        cur += ww
    return lines
