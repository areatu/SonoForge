"""Variant A — «Клиническая станция»: dense three-column workstation (all OSes)."""

from __future__ import annotations

from common import *  # noqa: F401,F403
from common import (
    CLIPS,
    PROTOCOLS,
    PROTO_ICON,
    PT,
    SIMPSON_STEPS,
    THEME_A,
    C,
    QPen,
    QRectF,
    Qt,
    button,
    cine_track,
    echo_view,
    hline,
    icon,
    info_overlay,
    kbd,
    line,
    pill,
    progress,
    rrect,
    search_field,
    section_label,
    status_icon,
    text,
    thumb,
    toggle,
    tw,
    vline,
    win_controls,
)
from kit import Canvas, OUT, logo, vgrad, circle
from common import scrollbar

S = 1.5
W, H = 1600, 1000
TB = 38  # title bar
PB = 50  # patient bar
SB = 26  # status bar
LW = 216  # clips column
RW = 352  # tool panel


def title_bar(p, th, tabs, active=0, search_ph="Команда, измерение, клип…", chrome="win"):
    p.fillRect(QRectF(0, 0, W, TB), C(th["bg0"]))
    if chrome == "mac":
        from common import traffic_lights

        traffic_lights(p, 16, 13)
        logo(p, 84, 9, 20, light=True)
        x = 118
    else:
        logo(p, 14, 9, 20, light=True)
        x = 50
    for i, (ico, title, sub) in enumerate(tabs):
        tw_ = 34 + tw(title, 12.5, 600) + (tw(" · " + sub, 12.5) if sub else 0) + 30
        if i == active:
            path_y = 6
            rrect(p, x, path_y, tw_, TB - path_y + 10, 8, fill=th["bg1"])
            col, col2 = th["text"], th["text2"]
        else:
            col, col2 = th["text2"], th["text3"]
            if i != active - 1 and i + 1 != len(tabs):
                vline(p, x + tw_, 13, 14, th["line2"])
        icon(p, ico, x + 12, 6 + (TB - 6 - 14) / 2, 14, th["accent"] if i == active else th["text3"])
        tx = x + 32
        tx += text(p, title, tx, 6, 12.5, 600, col, w=400, h=TB - 6, va="c")
        if sub:
            text(p, " · " + sub, tx, 6, 12.5, 400, col2, w=300, h=TB - 6, va="c")
        icon(p, "l-x", x + tw_ - 22, 6 + (TB - 6 - 12) / 2, 12, th["text3"])
        x += tw_ + 4
    icon(p, "l-plus", x + 6, 13, 15, th["text2"])
    sw_ = 330
    if chrome == "mac":
        search_field(p, W - 16 - sw_, 6, sw_, 26, search_ph, th, kbd_s="Ctrl K", r=7, bg=th["bg2"], size=12)
        icon(p, "l-list", W - 16 - sw_ - 34, 11, 16, th["text2"])
    else:
        search_field(p, W - 3 * 46 - 18 - sw_, 6, sw_, 26, search_ph, th, kbd_s="Ctrl K", r=7, bg=th["bg2"], size=12)
        win_controls(p, W, 0, TB, th["text2"])


def status_bar(p, th, left_items, right_items):
    y = H - SB
    p.fillRect(QRectF(0, y, W, SB), C(th["bg0"]))
    hline(p, 0, y, W, th["line"])
    x = 14
    for ico, s, col in left_items:
        if ico:
            icon(p, ico, x, y + 6, 14, col)
            x += 19
        x += text(p, s, x, y, 11.5, 500, col, w=500, h=SB, va="c") + 10
        vline(p, x, y + 7, 12, th["line2"])
        x += 11
    xr = W - 14
    for ico, s, col in right_items:
        wv = tw(s, 11.5, 600 if col == th["warn"] else 500)
        xr -= wv
        text(p, s, xr, y, 11.5, 600 if col == th["warn"] else 500, col, w=wv + 2, h=SB, va="c")
        if ico:
            xr -= 19
            icon(p, ico, xr, y + 6, 14, col)
        xr -= 18


def patient_bar(p, th):
    y = TB
    p.fillRect(QRectF(0, y, W, PB), C(th["bg1"]))
    hline(p, 0, y + PB - 1, W, th["line"])
    x = 16
    text(p, PT["name"], x, y + 8, 15, 600, th["text"])
    text(p, f"{PT['sex']} · {PT['age']} · ID {PT['pid']} · д. р. {PT['dob']}", x, y + 29, 11.5, 400, th["text2"])
    x = 16 + max(tw(PT["name"], 15, 600), tw(f"{PT['sex']} · {PT['age']} · ID {PT['pid']} · д. р. {PT['dob']}", 11.5)) + 26
    blocks = [
        ("РОСТ", PT["height"], False),
        ("ВЕС", PT["weight"], False),
        ("ППТ", PT["bsa"], True),
        ("ЧСС", PT["hr"] + " уд/мин", False),
        ("ИССЛЕДОВАНИЕ", f"{PT['date']} · {PT['time']}", False),
        ("АППАРАТ", PT["device"], False),
    ]
    for lab, val, edit in blocks:
        vline(p, x, y + 10, PB - 20, th["line2"])
        x += 14
        section_label(p, x, y + 9, lab, th, size=9.5)
        vw = text(p, val, x, y + 24, 13, 600, th["text"], tnum=True)
        if edit:
            icon(p, "l-pencil", x + vw + 6, y + 26, 12, th["text3"])
            vw += 18
        x += max(vw, tw(lab, 9.5, 600, spacing=0.6)) + 14
    # actions
    xr = W - 16
    bw = button(p, 0, -100, th, "Отчёт", "l-file-text", "primary", h=32, weight=600)
    xr -= bw
    button(p, xr, y + 9, th, "Отчёт", "l-file-text", "primary", h=32, weight=600)
    xr -= 12
    vline(p, xr, y + 14, 22, th["line2"])
    for lab, ico in (("Презентация", "l-presentation"), ("Сравнить", "l-columns-2")):
        bw = button(p, 0, -100, th, lab, ico, "ghost", h=32)
        xr -= bw + 4
        button(p, xr, y + 9, th, lab, ico, "ghost", h=32)
    xr -= 10
    vline(p, xr, y + 14, 22, th["line2"])
    for lab, ico in (("PACS", "l-cloud-download"), ("Открыть", "l-folder-open")):
        bw = button(p, 0, -100, th, lab, ico, "ghost", h=32)
        xr -= bw + 4
        button(p, xr, y + 9, th, lab, ico, "ghost", h=32)


def clips_column(p, th, top, bottom, selected="c1"):
    p.fillRect(QRectF(0, top, LW, bottom - top), C(th["bg1"]))
    vline(p, LW - 1, top, bottom - top, th["line"])
    y = top + 12
    text(p, "Клипы", 14, y, 13, 600, th["text"])
    pill(p, 14 + tw("Клипы", 13, 600) + 8, y - 1, "24", th["text2"], th["bg3"], h=18, size=10.5)
    icon(p, "l-layout-grid", LW - 52, y, 15, th["accent"])
    icon(p, "l-list", LW - 30, y, 15, th["text3"])
    # segmented filter
    y += 30
    segs = [("Все", "24"), ("2D", "14"), ("Доп.", "8"), ("M", "2")]
    sx, sw_ = 12, LW - 24
    rrect(p, sx, y, sw_, 26, 6, fill=th["bg2"], stroke=th["line"])
    seg_w = sw_ / len(segs)
    for i, (lab, n) in enumerate(segs):
        xx = sx + i * seg_w
        if i == 0:
            rrect(p, xx + 2, y + 2, seg_w - 4, 22, 5, fill=th["bg3"], stroke=th["line2"])
        s = f"{lab} {n}"
        text(p, lab, xx, y, 11, 600 if i == 0 else 500, th["text"] if i == 0 else th["text2"], w=seg_w - tw(" " + n, 10) , h=26, align="c", va="c")
        text(p, n, xx + seg_w / 2 + tw(lab, 11, 600) / 2 - tw(n, 10) / 2 + 2, y, 10, 500, th["text3"], w=20, h=26, va="c")
    y += 38
    tw_, th_ = (LW - 28 - 8) / 2, 66
    groups = [
        ("2D", "14", ["c1", "c2", "c3", "c4", "c11", "c12", "c13", "c14"]),
        ("Допплер", "8", ["c7", "c8", "c16", "c15", "c9", "c10", "c6"]),
        ("M-режим", "2", ["c5", "c18"]),
    ]
    by_id = {c[0]: c for c in CLIPS}
    p.save()
    p.setClipRect(QRectF(0, y - 4, LW, bottom - y + 4))
    for gname, gn, ids in groups:
        section_label(p, 14, y, f"{gname} · {gn}", th, size=9.5)
        icon(p, "l-chevron-down", LW - 30, y - 1, 13, th["text3"])
        y += 18
        for k, cid in enumerate(ids):
            cx = 14 + (k % 2) * (tw_ + 8)
            cy = y + (k // 2) * (th_ + 10)
            thumb(p, cx, cy, tw_, th_, by_id[cid], th, selected=(cid == selected), r=6)
        y += ((len(ids) + 1) // 2) * (th_ + 10) + 8
    p.restore()
    # fade at bottom (more clips below)
    p.fillRect(QRectF(0, bottom - 36, LW - 1, 36), vgrad(bottom - 36, bottom, [(0, C(th["bg1"], 0.0)), (1, C(th["bg1"], 1.0))]))
    scrollbar(p, LW - 7, top + 80, bottom - top - 90, 0.0, 0.62, th["text2"], alpha=0.28)


def viewer_toolbar(p, th, x, y, w, h):
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y + h - 1, w, th["line"])
    bx = x + 12
    by = y + (h - 30) / 2

    def tool(ico, active=False, label=None, key=None, disabled=False):
        nonlocal bx
        if active:
            bw = button(p, bx, by, th, label, ico, "ghost", h=30, active=True, kbd_s=key, weight=600)
        else:
            bw = 32
            icon(p, ico, bx + 8, by + 7, 16, th["text3"] if disabled else th["text2"])
            if key:
                text(p, key, bx + 22, by + 15, 8.5, 700, th["text3"])
        bx += bw + 2

    def sep():
        nonlocal bx
        bx += 6
        vline(p, bx, by + 6, 18, th["line2"])
        bx += 8

    tool("l-mouse-pointer-2")
    tool("l-move")
    tool("l-zoom-in")
    tool("l-sun-medium")
    sep()
    tool("l-ruler", key="L")
    tool("l-square-dashed", key="A")
    tool("l-spline", active=True, label="Контур", key="C")
    tool("l-audio-waveform", key="V", disabled=True)
    sep()
    tool("l-crosshair", key="K")
    sep()
    tool("l-sparkles")
    text(p, "Авто-контур", bx - 4, y, 11.5, 500, th["text3"], w=80, h=h, va="c")
    # right side
    xr = x + w - 12
    for ico in ("l-maximize-2", "l-columns-2", "l-rotate-ccw"):
        xr -= 32
        icon(p, ico, xr + 8, by + 7, 16, th["text2"])
    xr -= 70
    rrect(p, xr, by + 2, 62, 26, 6, fill=th["bg2"], stroke=th["line"])
    text(p, "100 %", xr + 9, by + 2, 11.5, 500, th["text2"], w=40, h=26, va="c", tnum=True)
    icon(p, "l-chevron-down", xr + 44, by + 9, 12, th["text3"])


def step_banner(p, th, cx, y, w=600):
    x = cx - w / 2
    h = 74
    rrect(p, x, y, w, h, 10, fill=C("#0c0f12", 0.86), stroke=C(th["line2"], 0.9))
    rrect(p, x, y, 4, h, 2, fill=th["accent"])
    tx = x + 18
    yy = y + 10
    xx = tx + text(p, "СИМПСОН БИПЛАНОВО", tx, yy, 10, 700, th["text2"], spacing=0.7) + 10
    xx += text(p, "шаг 2 из 4", xx, yy, 10.5, 600, th["accent_text"]) + 10
    for st in ("done", "current", "todo", "todo"):
        status_icon(p, xx, yy, st, th, size=11)
        xx += 16
    text(p, "КСО · 4-кам. — перейдите к кадру конца систолы и обведите эндокард ЛЖ", tx, y + 27, 13.5, 600, th["text"])
    kx = tx
    for k, lab in (("Enter", "готово"), ("S", "пропустить"), ("ПКМ", "отменить точку"), ("Esc", "выйти")):
        kx += kbd(p, kx, y + 50, k, th) + 6
        kx += text(p, lab, kx, y + 50, 11.5, 500, th["text2"], w=200, h=17, va="c") + 14


def cine_bar(p, th, x, y, w, h):
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y, w, th["line"])
    cy = y + h / 2
    bx = x + 16
    for ico in ("l-skip-back", "l-step-back"):
        icon(p, ico, bx, cy - 9, 18, th["text2"])
        bx += 32
    circle(p, bx + 17, cy, 17, fill=th["accent"])
    icon(p, "l-play", bx + 10, cy - 7.5, 15, th["on_accent"], sw=2.4)
    bx += 44
    for ico in ("l-step-forward", "l-skip-forward"):
        icon(p, ico, bx, cy - 9, 18, th["text2"])
        bx += 32
    # right block
    xr = x + w - 16
    icon(p, "l-repeat", xr - 18, cy - 9, 18, th["accent"])
    xr -= 34
    rrect(p, xr - 44, cy - 13, 44, 26, 6, fill=th["bg2"], stroke=th["line"])
    text(p, "1×", xr - 44, cy - 13, 12, 600, th["text2"], w=44, h=26, align="c", va="c")
    xr -= 58
    text(p, "кадр", xr - tw("кадр", 10.5), cy + 2, 10.5, 500, th["text3"])
    text(p, "1 / 83", xr - tw("1 / 83", 14, 600, tnum=True), cy - 16, 14, 600, th["text"], tnum=True)
    xr -= 76
    track_x = bx + 14
    cine_track(p, track_x, cy - 17, xr - track_x, 34, th, cur=0)


def tool_panel(p, th, x, top, bottom):
    p.fillRect(QRectF(x, top, RW, bottom - top), C(th["bg1"]))
    vline(p, x, top, bottom - top, th["line"])
    # tabs
    tabs = ["Измерения", "Расчёты", "Изображение", "DICOM"]
    tx = x + 14
    for i, t in enumerate(tabs):
        wv = tw(t, 12.5, 600 if i == 0 else 500)
        text(p, t, tx, top, 12.5, 600 if i == 0 else 500, th["text"] if i == 0 else th["text2"], w=wv + 2, h=40, va="c")
        if i == 0:
            rrect(p, tx, top + 38, wv, 2, 1, fill=th["accent"])
        tx += wv + 20
    hline(p, x, top + 40, RW, th["line"])
    y = top + 52
    search_field(p, x + 12, y, RW - 24, 32, "Найти: КДР, LVEDD, СДЛА…", th, kbd_s="/", r=7)
    y += 46
    section_label(p, x + 14, y, "Протоколы", th)
    text(p, "настроить", x + RW - 14 - tw("настроить", 11), y - 1, 11, 500, th["text3"])
    y += 20
    for key, name, modes, done, total in PROTOCOLS:
        active = key == "simpson"
        rh = 34
        if active:
            rrect(p, x + 8, y, RW - 16, 262, 9, fill=th["bg2"], stroke=C(th["accent"], 0.45))
        icon(p, "r-" + PROTO_ICON[key], x + 18, y + 8, 18, "#ffffff")
        text(p, name, x + 44, y, 12.5, 600 if active else 500, th["text"], w=200, h=rh, va="c")
        # progress chip
        s = f"{done}/{total}"
        if done == total:
            fg, bg = th["ok"], C(th["ok"], 0.15)
        elif done > 0:
            fg, bg = th["accent_text"], C(th["accent"], 0.14)
        else:
            fg, bg = th["text3"], th["bg3"]
        cw = tw(s, 10.5, 700, tnum=True) + 14
        cx = x + RW - 18 - cw
        rrect(p, cx, y + 8, cw, 18, 9, fill=bg)
        text(p, s, cx, y + 8, 10.5, 700, fg, w=cw, h=18, align="c", va="c", tnum=True)
        mx = cx - 6
        for m in reversed(modes):
            mw = tw(m, 9, 600) + 8
            mx -= mw
            rrect(p, mx, y + 10, mw, 14, 3.5, fill=None, stroke=th["line2"])
            text(p, m, mx, y + 10, 9, 600, th["text3"], w=mw, h=14, align="c", va="c")
            mx -= 4
        y += rh
        if active:
            y = simpson_card(p, th, x + 18, y + 2, RW - 36)
            y += 12
    y += 8
    hline(p, x + 14, y, RW - 28, th["line"])
    y += 14
    section_label(p, x + 14, y, "Все измерения", th)
    text(p, "по анатомии", x + RW - 14 - tw("по анатомии", 11), y - 1, 11, 500, th["text3"])
    y += 20
    groups = [("LV01", "Левый желудочек", "6/14"), ("LA01", "Левое предсердие", "0/5"), ("MV01", "Митральный клапан", "3/9"), ("AV01", "Аортальный клапан · ВТЛЖ", "0/9"), ("TV01", "Трикуспидальный клапан", "2/7"), ("RV01", "Правый желудочек", "0/6")]
    for ico, name, cnt in groups:
        if y > bottom - 150:
            break
        icon(p, "r-" + ico, x + 18, y + 6, 16, "#ffffff")
        text(p, name, x + 44, y, 12, 500, th["text2"], w=220, h=28, va="c")
        text(p, cnt, x + RW - 44 - tw(cnt, 11, 500, tnum=True), y, 11, 500, th["text3"], w=40, h=28, va="c", tnum=True)
        icon(p, "l-chevron-right", x + RW - 32, y + 7, 14, th["text3"])
        y += 28
    # summary block pinned at the bottom
    sy = bottom - 128
    p.fillRect(QRectF(x + 1, sy, RW - 1, bottom - sy), C(th["bg1"]))
    hline(p, x, sy, RW, th["line"])
    section_label(p, x + 14, sy + 12, "Сводка", th)
    text(p, "14 измерений · 6 расчётов", x + RW - 14 - tw("14 измерений · 6 расчётов", 11), sy + 11, 11, 500, th["text3"])
    from common import KEY_RESULTS

    cw = (RW - 28) / 3
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


def simpson_card(p, th, x, y, w):
    # progress
    text(p, "шаг 2 из 4", x, y, 11, 600, th["accent_text"])
    progress(p, x + 74, y + 6, w - 74, 4, 0.25, th["accent"], th["bg3"])
    y += 20
    tile_w = (w - 8) / 2
    tile_h = 48
    for i, (lab, val, st) in enumerate(SIMPSON_STEPS):
        tx = x + (i % 2) * (tile_w + 8)
        ty = y + (i // 2) * (tile_h + 8)
        if st == "current":
            rrect(p, tx, ty, tile_w, tile_h, 7, fill=C(th["accent"], 0.13), stroke=C(th["accent"], 0.8), sw=1.2)
        elif st == "done":
            rrect(p, tx, ty, tile_w, tile_h, 7, fill=th["bg1"], stroke=C(th["ok"], 0.35))
        else:
            rrect(p, tx, ty, tile_w, tile_h, 7, fill=th["bg1"], stroke=th["line2"])
        status_icon(p, tx + 9, ty + 9, st, th, size=13)
        text(p, lab, tx + 28, ty + 7, 12, 600, th["text"] if st != "todo" else th["text2"])
        if st == "done":
            text(p, val, tx + 28, ty + 26, 12, 500, th["text2"], tnum=True)
        elif st == "current":
            icon(p, "l-arrow-left", tx + 28, ty + 28, 12, th["accent_text"], sw=2.2)
            text(p, "кадр КС · 11", tx + 44, ty + 26, 11.5, 600, th["accent_text"])
        else:
            text(p, "—", tx + 28, ty + 26, 12, 500, th["text3"])
    y += 2 * (tile_h + 8) + 2
    rrect(p, x, y, w, 52, 7, fill=th["bg1"], stroke=th["line"])
    rows = [("ФВ ЛЖ (4-кам.)", "— после КСО"), ("ФВ ЛЖ бипланово", "— после 2-кам.")]
    for i, (a, b) in enumerate(rows):
        text(p, a, x + 10, y + 7 + i * 20, 11.5, 500, th["text2"])
        text(p, b, x + w - 10 - tw(b, 11.5), y + 7 + i * 20, 11.5, 500, th["text3"])
    y += 62
    toggle(p, x, y, True, th, w=28, h=16)
    text(p, "Авто-переход", x + 36, y - 1, 11.5, 500, th["text2"])
    sx = x + w - tw("Пропустить", 11.5, 500) - 2
    text(p, "Пропустить", sx, y - 1, 11.5, 500, th["text2"])
    icon(p, "l-skip-forward", sx - 18, y, 13, th["text3"])
    return y + 18


def render_a1():
    th = THEME_A
    cv = Canvas(W, H, S, bg=th["bg0"])
    p = cv.p
    title_bar(p, th, [("l-heart-pulse", PT["short"], PT["date"]), ("l-heart-pulse", "Сидоров А. П.", "07.10.2026")])
    patient_bar(p, th)
    top = TB + PB
    bottom = H - SB
    clips_column(p, th, top, bottom)
    vx, vw = LW, W - LW - RW
    viewer_toolbar(p, th, vx, top, vw, 42)
    img_top = top + 42
    cine_h = 66
    img_h = bottom - cine_h - img_top
    rect = echo_view(p, vx, img_top, vw, img_h, th, pad=(96, 18, 70, 90))
    info_overlay(p, vx + 16, img_top + 14, ["SAMSUNG RS85 · PM1-6A", "2D · 16 см · 30 Гц · Gn 54 · DR 60"], lh=15)
    text(p, "Кадр 1 / 83 · КД", vx + 16, img_top + 46, 10.5, 600, C(th["accent_text"], 0.9))
    # right overlay chips
    xr = vx + vw - 16
    s1 = "4-кам."
    wv = pill(p, 0, -100, s1, "#ffffff", C("#000000", 0.6), h=22, size=11.5)
    pill(p, xr - wv, img_top + 14, s1, "#ffffff", C("#000000", 0.6), h=22, size=11.5, stroke=C("#ffffff", 0.25))
    s2 = "0,28 мм/пикс. · DICOM"
    wv2 = pill(p, 0, -100, s2, th["ok"], C("#000000", 0.6), h=22, size=11, icon_name="l-check")
    pill(p, xr - wv2, img_top + 42, s2, th["ok"], C("#000000", 0.6), h=22, size=11, icon_name="l-check", weight=500)
    step_banner(p, th, vx + vw / 2, img_top + 12, w=610)
    cine_bar(p, th, vx, bottom - cine_h, vw, cine_h)
    tool_panel(p, th, W - RW, top, bottom)
    status_bar(
        p,
        th,
        [("l-circle-check", "Сохранено · 10:42", th["ok"]), (None, "Калибровка: DICOM · 0,28 мм/пикс.", th["text2"]), (None, "Кадры: 83/83 декодировано", th["text2"])],
        [("l-triangle-alert", "Только для исследований", th["warn"]), (None, "SonoForge 0.4.0", th["text3"])],
    )
    return cv.save(OUT / "A1-workstation-main.png")


# ───────────────────────────── A2: study browser ─────────────────────────────

STUDIES = [
    ("Петрова Мария Ивановна", "Ж · 59", "0004127", "08.10.2026", "10:14", "ЭхоКГ трансторакальная", "24", ("draft", "14 изм. · черновик"), "folder", "Echo cases"),
    ("Сидоров Алексей Петрович", "М · 64", "0004119", "07.10.2026", "16:40", "ЭхоКГ трансторакальная", "31", ("done", "Отчёт готов"), "server", "Orthanc"),
    ("Кузнецова Ольга Львовна", "Ж · 47", "0004102", "07.10.2026", "11:05", "ЭхоКГ трансторакальная", "18", ("new", "Новое"), "server", "Orthanc"),
    ("Морозов Игорь Сергеевич", "М · 71", "0003987", "06.10.2026", "09:30", "Стресс-ЭхоКГ", "46", ("draft", "9 изм. · черновик"), "server", "Orthanc"),
    ("Волкова Анна Дмитриевна", "Ж · 38", "0003950", "03.10.2026", "14:12", "ЭхоКГ трансторакальная", "22", ("done", "Отчёт готов"), "folder", "Echo cases"),
    ("Новиков Павел Андреевич", "М · 55", "0003921", "02.10.2026", "10:48", "ЭхоКГ трансторакальная", "27", ("new", "Новое"), "folder", "Follow-up"),
    ("Лебедева Ирина Викторовна", "Ж · 62", "0003899", "01.10.2026", "15:20", "ЭхоКГ трансторакальная", "20", ("done", "Отчёт готов"), "server", "Orthanc"),
    ("Соколов Дмитрий Олегович", "М · 49", "0003874", "30.09.2026", "12:02", "Деформация (STE)", "12", ("draft", "6 изм. · черновик"), "folder", "Echo cases"),
    ("Попова Елена Николаевна", "Ж · 66", "0003860", "29.09.2026", "09:15", "ЭхоКГ трансторакальная", "25", ("done", "Отчёт готов"), "server", "Orthanc"),
    ("Козлов Артём Ильич", "М · 33", "0003841", "26.09.2026", "17:30", "ЭхоКГ трансторакальная", "19", ("new", "Новое"), "server", "Orthanc"),
    ("Фёдорова Светлана Павловна", "Ж · 58", "0003833", "25.09.2026", "11:40", "ЭхоКГ трансторакальная", "23", ("done", "Отчёт готов"), "folder", "Follow-up"),
    ("Орлов Виктор Семёнович", "М · 77", "0003810", "24.09.2026", "08:55", "ЭхоКГ трансторакальная", "29", ("done", "Отчёт готов"), "server", "Orthanc"),
]


def render_a2():
    th = THEME_A
    cv = Canvas(W, H, S, bg=th["bg0"])
    p = cv.p
    title_bar(p, th, [("l-layout-grid", "Исследования", None), ("l-heart-pulse", PT["short"], PT["date"])], active=0)
    top = TB
    bottom = H - SB
    # header row
    p.fillRect(QRectF(0, top, W, 60), C(th["bg1"]))
    hline(p, 0, top + 59, W, th["line"])
    text(p, "Исследования", 20, top, 19, 600, th["text"], w=300, h=60, va="c")
    search_field(p, 200, top + 13, 420, 34, "Пациент, ID, дата, аппарат…", th, kbd_s="Ctrl F", r=8, bg=th["bg2"], size=12.5)
    segs = ["Сегодня", "7 дней", "30 дней", "Все"]
    sx = 640
    rrect(p, sx, top + 13, 300, 34, 8, fill=th["bg2"], stroke=th["line"])
    sw_ = 300 / 4
    for i, s in enumerate(segs):
        if i == 1:
            rrect(p, sx + i * sw_ + 3, top + 16, sw_ - 6, 28, 6, fill=th["bg3"], stroke=th["line2"])
        text(p, s, sx + i * sw_, top + 13, 12, 600 if i == 1 else 500, th["text"] if i == 1 else th["text2"], w=sw_, h=34, align="c", va="c")
    xr = W - 20
    bw = button(p, 0, -100, th, "Загрузить с PACS", "l-cloud-download", "primary", h=34, weight=600)
    xr -= bw
    button(p, xr, top + 13, th, "Загрузить с PACS", "l-cloud-download", "primary", h=34, weight=600)
    bw = button(p, 0, -100, th, "Открыть папку…", "l-folder-open", "outline", h=34)
    xr -= bw + 8
    button(p, xr, top + 13, th, "Открыть папку…", "l-folder-open", "outline", h=34)
    top += 60
    # left nav
    NW = 236
    p.fillRect(QRectF(0, top, NW, bottom - top), C(th["bg1"]))
    vline(p, NW - 1, top, bottom - top, th["line"])
    y = top + 16
    section_label(p, 16, y, "Источники", th)
    y += 22
    nav = [
        ("l-history", "Недавние", "12", True, None),
        ("l-folder", "Локальные папки", "3", False, None),
        ("l-server", "Orthanc · клиника", None, False, th["ok"]),
        ("l-database", "Хранилище измерений", "37", False, None),
    ]
    for ico, lab, cnt, sel, dot in nav:
        if sel:
            rrect(p, 8, y, NW - 16, 32, 7, fill=C(th["accent"], 0.13))
        icon(p, ico, 18, y + 8, 16, th["accent_text"] if sel else th["text2"])
        text(p, lab, 42, y, 12.5, 600 if sel else 500, th["text"] if sel else th["text2"], w=160, h=32, va="c", elide=True)
        if cnt:
            text(p, cnt, NW - 22 - tw(cnt, 11, tnum=True), y, 11, 500, th["text3"], w=30, h=32, va="c", tnum=True)
        if dot:
            circle(p, NW - 24, y + 16, 4, fill=dot)
        y += 34
    y += 14
    section_label(p, 16, y, "Избранные папки", th)
    y += 22
    for lab, star in (("Echo cases", True), ("Follow-up studies", False), ("Клинический разбор", False)):
        icon(p, "l-star" if star else "l-folder", 18, y + 8, 15, th["warn"] if star else th["text3"])
        text(p, lab, 42, y, 12.5, 500, th["text2"], w=170, h=32, va="c")
        y += 32
    y += 14
    section_label(p, 16, y, "Фильтры", th)
    y += 22
    for lab, n in (("Без отчёта", "5"), ("Черновики", "3"), ("Мои за неделю", "9")):
        icon(p, "l-filter", 18, y + 8, 15, th["text3"])
        text(p, lab, 42, y, 12.5, 500, th["text2"], w=150, h=32, va="c")
        text(p, n, NW - 22 - tw(n, 11), y, 11, 500, th["text3"], w=30, h=32, va="c")
        y += 32
    # bottom profile box
    by = bottom - 104
    hline(p, 0, by, NW - 1, th["line"])
    text(p, "Профиль: Полный", 16, by + 14, 12, 600, th["text"])
    text(p, "Сохранение измерений: включено", 16, by + 34, 11, 500, th["text2"])
    bx = 16
    for ico, lab in (("l-settings", "Настройки"), ("l-book-open", "Справка"), ("l-message-square-warning", "")):
        icon(p, ico, bx, by + 64, 14, th["text2"])
        bx += 18 + (text(p, lab, bx + 18, by + 62, 11.5, 500, th["text2"]) if lab else 0) + 14
    # table
    PX = W - 410
    tx0, tx1 = NW, PX
    p.fillRect(QRectF(tx0, top, tx1 - tx0, bottom - top), C(th["bg0"]))
    cols = [("Пациент", 232), ("ID", 76), ("Дата", 106), ("Исследование", 178), ("Клипы", 54), ("Статус", 150), ("Источник", 0)]
    hy = top + 10
    cx = tx0 + 20
    xs = []
    for lab, wv in cols:
        xs.append(cx)
        col = th["text"] if lab == "Дата" else th["text3"]
        text(p, lab.upper(), cx, hy, 10, 600, col, spacing=0.6, w=200, h=26, va="c")
        if lab == "Дата":
            icon(p, "l-chevron-down", cx + tw("ДАТА", 10, 600, spacing=0.6) + 4, hy + 7, 12, th["text"])
        cx += wv
    hline(p, tx0, hy + 30, tx1 - tx0, th["line"])
    ry = hy + 34
    rh = 50
    stc = {"draft": (th["warn"], C(th["warn"], 0.13), "l-pencil"), "done": (th["ok"], C(th["ok"], 0.13), "l-check"), "new": (th["blue"], C(th["blue"], 0.13), "l-circle-dot")}
    for i, (name, sa, pid, d, t, kind, n, (st, stl), src, srcl) in enumerate(STUDIES):
        if ry + rh > bottom:
            break
        sel = i == 0
        if sel:
            rrect(p, tx0 + 8, ry, tx1 - tx0 - 16, rh - 4, 8, fill=C(th["accent"], 0.11), stroke=C(th["accent"], 0.45))
        elif i % 2 == 1:
            rrect(p, tx0 + 8, ry, tx1 - tx0 - 16, rh - 4, 8, fill=C("#ffffff", 0.018))
        cy = ry + (rh - 4) / 2
        text(p, name, xs[0], cy - 16, 12.5, 600, th["text"], w=240, h=18, va="c", elide=True)
        text(p, sa + " лет", xs[0], cy + 1, 11, 500, th["text3"], w=200, h=16, va="c")
        text(p, pid, xs[1], cy - 9, 12, 500, th["text2"], w=80, h=18, va="c", tnum=True)
        text(p, d, xs[2], cy - 16, 12, 500, th["text"], w=120, h=18, va="c", tnum=True)
        text(p, t, xs[2], cy + 1, 11, 500, th["text3"], w=120, h=16, va="c", tnum=True)
        text(p, kind, xs[3], cy - 9, 12, 500, th["text2"], w=185, h=18, va="c", elide=True)
        text(p, n, xs[4], cy - 9, 12, 500, th["text2"], w=50, h=18, va="c", tnum=True)
        fg, bg, ico = stc[st]
        pill(p, xs[5], cy - 10, stl, fg, bg, h=20, size=10.5, icon_name=ico)
        icon(p, "l-folder" if src == "folder" else "l-server", xs[6], cy - 7, 14, th["text3"])
        text(p, srcl, xs[6] + 20, cy - 9, 11.5, 500, th["text3"], w=110, h=18, va="c")
        ry += rh
    hline(p, tx0 + 20, ry + 6, tx1 - tx0 - 40, th["line"])
    text(p, "12 из 148 исследований за 7 дней", tx0 + 20, ry + 18, 11.5, 500, th["text3"])
    text(p, "Показать ещё", tx1 - 20 - tw("Показать ещё", 11.5, 600), ry + 18, 11.5, 600, th["accent_text"])
    # preview panel
    p.fillRect(QRectF(PX, top, W - PX, bottom - top), C(th["bg1"]))
    vline(p, PX, top, bottom - top, th["line"])
    x = PX + 20
    y = top + 18
    text(p, PT["name"], x, y, 16, 600, th["text"])
    text(p, f"{PT['sex']} · {PT['age']} · ID {PT['pid']} · д. р. {PT['dob']}", x, y + 24, 11.5, 500, th["text2"])
    y += 52
    meta = [("Исследование", "ЭхоКГ трансторакальная"), ("Дата", f"{PT['date']} · {PT['time']}"), ("Аппарат", f"{PT['device']} · 24 клипа"), ("Источник", "Echo cases · локально"), ("Прошлые", "07.04.2026 · 18.10.2025")]
    for lab, val in meta:
        text(p, lab, x, y, 11.5, 500, th["text3"])
        text(p, val, x + 110, y, 11.5, 500, th["text"] if lab != "Прошлые" else th["accent_text"])
        y += 20
    y += 10
    section_label(p, x, y, "Клипы · 24", th)
    y += 20
    gw = (W - PX - 40 - 16) / 3
    gh = gw * 0.72
    for k, cid in enumerate(["c1", "c2", "c3", "c7", "c8", "c9", "c10", "c5", "c6"]):
        clip = [c for c in CLIPS if c[0] == cid][0]
        thumb(p, x + (k % 3) * (gw + 8), y + (k // 3) * (gh + 8), gw, gh, clip, th, r=6)
    y += 3 * (gh + 8) + 10
    section_label(p, x, y, "Протоколы", th)
    y += 20
    for key, name, modes, done, total in PROTOCOLS:
        text(p, name, x, y, 12, 500, th["text2"], w=200, h=18, va="c")
        col = th["ok"] if done == total else (th["accent"] if done else th["bg3"])
        progress(p, x + 200, y + 7, W - PX - 40 - 200 - 46, 5, done / total, col, th["bg3"])
        s = f"{done}/{total}"
        text(p, s, W - 20 - tw(s, 11, 600, tnum=True), y, 11, 600, th["text2"], w=40, h=18, va="c", tnum=True)
        y += 24
    # actions
    by = bottom - 70
    hline(p, PX, by - 14, W - PX, th["line"])
    bw = (W - PX - 40 - 10) / 2
    button(p, x, by, th, "Открыть исследование", "l-arrow-right", "primary", h=38, w=bw, weight=600)
    button(p, x + bw + 10, by, th, "Сравнить с 07.04.2026", "l-columns-2", "outline", h=38, w=bw)
    text(p, "Enter — открыть  ·  Пробел — быстрый просмотр", x, by + 44, 10.5, 500, th["text3"])
    status_bar(
        p,
        th,
        [("l-circle-check", "Orthanc · клиника: подключено", th["ok"]), (None, "Кэш: 2,4 ГБ из 10 ГБ", th["text2"])],
        [("l-triangle-alert", "Только для исследований", th["warn"]), (None, "SonoForge 0.4.0", th["text3"])],
    )
    return cv.save(OUT / "A2-workstation-study-browser.png")


if __name__ == "__main__":
    print(render_a1())
    print(render_a2())
