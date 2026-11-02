"""Variant B — «Mac Pro»: native macOS look (menu bar, unified toolbar, glass sidebar/inspector)."""

from __future__ import annotations

import functools

import numpy as np
from PIL import Image, ImageFilter

from common import (
    CLIPS,
    PROTOCOLS,
    PT,
    SIMPSON_STEPS,
    C,
    QPen,
    QRectF,
    Qt,
    cine_track,
    echo_view,
    hline,
    icon,
    line,
    pill,
    rrect,
    status_icon,
    text,
    thumb,
    toggle,
    tw,
    vline,
    ring,
    circle,
    traffic_lights,
)
from kit import OUT, Canvas, glass, pil_to_qimage, shadow, logo, vgrad, draw_image_fit, qimage_to_pil

S = 1.5
W, H = 1600, 1000
MB = 24  # system menu bar

DARK = {
    "mode": "dark",
    "win_bg": "#1f1f22",
    "glass_tint": "#2b2b30",
    "glass_a": 0.66,
    "glass_border": "#ffffff",
    "glass_border_a": 0.11,
    "group": C("#ffffff", 0.055),
    "group_border": C("#ffffff", 0.06),
    "sep": C("#ffffff", 0.08),
    "text": "#f5f5f7",
    "text2": "#a1a1a6",
    "text3": "#6e6e73",
    "accent": "#0a84ff",
    "accent_text": "#3d9bff",
    "on_accent": "#ffffff",
    "ok": "#30d158",
    "warn": "#ff9f0a",
    "err": "#ff453a",
    "bg1": "#232326",
    "bg2": "#2c2c2e",
    "bg3": "#3a3a3c",
    "line": "#3a3a3c",
    "line2": "#48484a",
    "seg_thumb": C("#ffffff", 0.16),
    "capsule_tint": "#3a3a40",
    "capsule_a": 0.55,
    "menubar": C("#1c1c22", 0.55),
    "menubar_text": "#f5f5f7",
    "viewer_border": C("#ffffff", 0.06),
}
LIGHT = {
    "mode": "light",
    "win_bg": "#ececef",
    "glass_tint": "#fafafc",
    "glass_a": 0.78,
    "glass_border": "#000000",
    "glass_border_a": 0.09,
    "group": C("#ffffff", 0.9),
    "group_border": C("#000000", 0.07),
    "sep": C("#000000", 0.08),
    "text": "#1d1d1f",
    "text2": "#6e6e73",
    "text3": "#a1a1a6",
    "accent": "#007aff",
    "accent_text": "#0068da",
    "on_accent": "#ffffff",
    "ok": "#28a745",
    "warn": "#e08600",
    "err": "#ff3b30",
    "bg1": "#f5f5f7",
    "bg2": "#ffffff",
    "bg3": "#e5e5ea",
    "line": "#d9d9de",
    "line2": "#c7c7cc",
    "seg_thumb": C("#ffffff", 1.0),
    "capsule_tint": "#ffffff",
    "capsule_a": 0.7,
    "menubar": C("#f6f6f8", 0.6),
    "menubar_text": "#1d1d1f",
    "viewer_border": C("#000000", 0.12),
}


@functools.lru_cache(maxsize=None)
def wallpaper(mode: str, w: int, h: int) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if mode == "dark":
        base = np.array([12, 16, 34], np.float32)
        blobs = [((0.12, 0.15), 0.55, (92, 42, 140)), ((0.88, 0.95), 0.6, (14, 96, 112)), ((0.7, 0.05), 0.45, (30, 58, 138)), ((0.35, 1.0), 0.4, (60, 30, 90))]
    else:
        base = np.array([222, 230, 243], np.float32)
        blobs = [((0.1, 0.1), 0.6, (246, 210, 228)), ((0.9, 0.9), 0.6, (196, 222, 255)), ((0.75, 0.1), 0.45, (210, 243, 234)), ((0.3, 0.95), 0.5, (236, 226, 255))]
    img = np.zeros((h, w, 3), np.float32) + base
    for (cx, cy), r, col in blobs:
        d = np.sqrt(((xx / w - cx) / r) ** 2 + ((yy / h - cy) / (r * w / h)) ** 2)
        a = np.clip(1 - d, 0, 1) ** 1.6
        img = img * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def menu_bar(cv, th):
    p = cv.p
    glass(cv, 0, 0, W, MB, 0, blur=20, tint=th["menubar"], tint_a=th["menubar"].alphaF(), border=th["glass_border"], border_a=0.0, sheen=False)
    x = 16
    circle(p, x + 6, MB / 2, 6, fill=th["menubar_text"])
    x += 26
    x += text(p, "SonoForge", x, 0, 13, 700, th["menubar_text"], w=120, h=MB, va="c") + 18
    for m in ("Файл", "Правка", "Вид", "Исследование", "Измерения", "Окно", "Справка"):
        x += text(p, m, x, 0, 13, 500, th["menubar_text"], w=140, h=MB, va="c") + 18
    xr = W - 16
    s = "Чт 15 окт.  19:40"
    xr -= tw(s, 13, 500)
    text(p, s, xr, 0, 13, 500, th["menubar_text"], w=200, h=MB, va="c")
    for ico in ("p-magnifying-glass", "p-sliders-horizontal"):
        xr -= 30
        icon(p, ico, xr + 6, 4, 16, th["menubar_text"])


def capsule(cv, x, y, w, h, th, tint=None, alpha=None):
    glass(cv, x, y, w, h, h / 2, blur=16, tint=tint or th["capsule_tint"], tint_a=alpha if alpha is not None else th["capsule_a"], border=th["glass_border"], border_a=th["glass_border_a"] + 0.03)


def segmented(cv, x, y, w, h, items, sel, th, size=12.5):
    p = cv.p
    capsule(cv, x, y, w, h, th)
    sw = (w - 6) / len(items)
    for i, it in enumerate(items):
        sx = x + 3 + i * sw
        if i == sel:
            if th["mode"] == "light":
                shadow(cv, sx, y + 3, sw, h - 6, (h - 6) / 2, blur=6, dy=1, alpha=0.18)
            rrect(p, sx, y + 3, sw, h - 6, (h - 6) / 2, fill=th["seg_thumb"])
        text(p, it, sx, y, size, 600 if i == sel else 500, th["text"] if i == sel else th["text2"], w=sw, h=h, align="c", va="c")


def inset_group(p, x, y, w, rows, th, rh=38):
    h = rh * len(rows)
    rrect(p, x, y, w, h, 10, fill=th["group"], stroke=th["group_border"])
    for i in range(1, len(rows)):
        hline(p, x + 12, y + i * rh, w - 24, th["sep"])
    return h


def render_main(th, out_name=None, cv=None):
    own = cv is None
    if own:
        cv = Canvas(W, H, S, bg="#000000")
        cv.p.drawImage(QRectF(0, 0, W, H), pil_to_qimage(wallpaper(th["mode"], 800, 500)))
    p = cv.p
    menu_bar(cv, th)
    wx, wy, ww, wh = 22, MB + 14, W - 44, H - MB - 14 - 16
    shadow(cv, wx, wy, ww, wh, 18, blur=60, dy=24, alpha=0.55 if th["mode"] == "dark" else 0.28)
    p.save()
    p.setClipPath(__import__("kit").rr_path(wx, wy, ww, wh, 18))
    p.fillRect(QRectF(wx, wy, ww, wh), C(th["win_bg"]))
    # geometry
    SBW, INW = 258, 306
    sx, sy, sh = wx + 8, wy + 8, wh - 16
    ix = wx + ww - 8 - INW
    cx0, cx1 = sx + SBW + 8, ix - 8
    vy = wy + 64
    vh = wy + wh - 8 - vy
    # viewer card
    rrect(p, cx0, vy, cx1 - cx0, vh, 14, fill="#000000")
    p.save()
    p.setClipPath(__import__("kit").rr_path(cx0, vy, cx1 - cx0, vh, 14))
    vth = {"accent": th["accent"], "accent_text": th["accent_text"], "warn": th["warn"], "ok": th["ok"], "bg2": "#1c1c1e", "line": "#2c2c2e", "text2": "#a1a1a6"}
    rect = echo_view(p, cx0, vy, cx1 - cx0, vh, vth, pad=(70, 96, 40, 70), lv_color="#64d2ff", lv_label="КДО · 4-кам.  112 мл", bg=None)
    p.restore()
    rrect(p, cx0, vy, cx1 - cx0, vh, 14, stroke=th["viewer_border"])
    text(p, "4-кам. · 2D", cx0 + 18, vy + 16, 13, 600, "#ffffff")
    text(p, "Кадр 1 из 83 · КД", cx0 + 18, vy + 36, 11.5, 500, C("#ffffff", 0.55))
    circle(p, cx0 + 18 + tw("4-кам. · 2D", 13, 600) + 16, vy + 24, 9, stroke=C("#ffffff", 0.4), sw=1.2)
    text(p, "i", cx0 + 18 + tw("4-кам. · 2D", 13, 600) + 7, vy + 15, 11, 700, C("#ffffff", 0.6), w=18, h=18, align="c", va="c")
    # step capsule (top centre of the viewer)
    msg = "Шаг 2 из 4 · КСО · 4-кам. — перейдите к кадру конца систолы"
    mw = tw(msg, 12.5, 500) + 130
    mx = (cx0 + cx1) / 2 - mw / 2
    dark_cap = {**th, "capsule_tint": "#26262b", "capsule_a": 0.78, "glass_border": "#ffffff", "glass_border_a": 0.12}
    capsule(cv, mx, vy + 14, mw, 36, dark_cap)
    status_icon(p, mx + 14, vy + 25, "current", {"accent": "#64d2ff", "ok": th["ok"], "warn": th["warn"], "text3": "#6e6e73"}, size=14)
    text(p, msg, mx + 36, vy + 14, 12.5, 500, "#f5f5f7", w=mw, h=36, va="c")
    bw = 84
    rrect(p, mx + mw - bw - 6, vy + 20, bw, 24, 12, fill=th["accent"])
    text(p, "Готово  ⏎", mx + mw - bw - 6, vy + 20, 12, 600, "#ffffff", w=bw, h=24, align="c", va="c")
    # transport capsule
    tw_ = 640
    tx = (cx0 + cx1) / 2 - tw_ / 2
    ty = vy + vh - 18 - 54
    capsule(cv, tx, ty, tw_, 54, dark_cap)
    icon(p, "p-skip-back", tx + 18, ty + 17, 20, "#f5f5f7")
    circle(p, tx + 70, ty + 27, 17, fill="#f5f5f7")
    icon(p, "p-play", tx + 62, ty + 19, 16, "#000000")
    icon(p, "p-skip-forward", tx + 100, ty + 17, 20, "#f5f5f7")
    track_th = {"bg2": C("#ffffff", 0.06), "line": C("#ffffff", 0.08), "ok": "#30d158", "accent": "#64d2ff", "accent_text": "#64d2ff", "warn": "#ff9f0a"}
    cine_track(p, tx + 138, ty + 13, tw_ - 138 - 106, 28, track_th, cur=0, track_bg=C("#ffffff", 0.06), r=8, labels=False)
    text(p, "1 / 83", tx + tw_ - 96, ty + 9, 13, 600, "#f5f5f7", tnum=True)
    text(p, "кадр · 30 к/с", tx + tw_ - 96, ty + 28, 10.5, 500, C("#ffffff", 0.5))
    # toolbar (title + controls)
    tbx = cx0 + 6
    text(p, PT["name"], tbx, wy + 14, 15, 700, th["text"])
    text(p, f"ЭхоКГ · {PT['date']} · {PT['device']}", tbx, wy + 35, 11.5, 500, th["text2"])
    seg_w = 300
    segmented(cv, (cx0 + cx1) / 2 - seg_w / 2 - 34, wy + 16, seg_w, 32, ["Просмотр", "Измерения", "Отчёт"], 1, th)
    # tools capsule
    tools = ["p-ruler", "p-polygon", "p-pen-nib", "p-waveform"]
    capw = 38 * len(tools) + 8
    capx = cx1 - capw
    capsule(cv, capx, wy + 15, capw, 34, th)
    for i, ico in enumerate(tools):
        bx = capx + 4 + i * 38
        if ico == "p-pen-nib":
            rrect(p, bx + 2, wy + 19, 34, 26, 13, fill=C(th["accent"], 0.9))
            icon(p, ico, bx + 10, wy + 23, 18, "#ffffff")
        else:
            icon(p, ico, bx + 10, wy + 23, 18, th["text"] if ico != "p-waveform" else th["text3"])
    cap2 = ["p-magnifying-glass", "p-square-split-horizontal", "p-share-network"]
    c2w = 38 * len(cap2) + 8
    c2x = capx - 10 - c2w
    capsule(cv, c2x, wy + 15, c2w, 34, th)
    for i, ico in enumerate(cap2):
        icon(p, ico, c2x + 4 + i * 38 + 10, wy + 23, 18, th["text"])
    # sidebar (glass)
    glass(cv, sx, sy, SBW, sh, 16, blur=24, tint=th["glass_tint"], tint_a=th["glass_a"], border=th["glass_border"], border_a=th["glass_border_a"])
    traffic_lights(p, sx + 16, sy + 16)
    icon(p, "p-sidebar-simple", sx + SBW - 36, sy + 12, 19, th["text2"])
    y = sy + 50
    text(p, "Исследования", sx + 16, y, 11, 700, th["text3"])
    icon(p, "p-plus", sx + SBW - 30, y - 1, 14, th["text3"])
    y += 22
    icon(p, "p-caret-down", sx + 12, y + 7, 12, th["text2"])
    icon(p, "p-folder-simple", sx + 28, y + 5, 16, th["accent_text"])
    text(p, PT["short"], sx + 50, y, 13, 600, th["text"], w=150, h=28, va="c")
    text(p, "24", sx + SBW - 18 - tw("24", 11.5), y, 11.5, 500, th["text3"], w=30, h=28, va="c")
    y += 32
    by_id = {c[0]: c for c in CLIPS}
    groups = [("2D · 14", ["c1", "c2", "c3", "c4", "c13"]), ("Допплер · 8", ["c7", "c8", "c9", "c10"]), ("M-режим · 2", ["c5"])]
    p.save()
    p.setClipRect(QRectF(sx, y, SBW, sh - (y - sy) - 96))
    for gname, ids in groups:
        text(p, gname, sx + 30, y + 2, 10.5, 600, th["text3"])
        y += 20
        for cid in ids:
            clip = by_id[cid]
            sel = cid == "c1"
            if sel:
                rrect(p, sx + 8, y, SBW - 16, 56, 9, fill=th["accent"])
            thumb(p, sx + 30, y + 6, 62, 44, clip, {**th, "accent": "#ffffff", "on_accent": th["accent"]}, show_label=False, badge=False, measured=False, r=5)
            title = clip[1] if clip[2] in ("2D", "M") else f"{clip[2]} · {clip[1]}"
            sub = {"2D": f"2D · {clip[4].replace(' к.', ' кадр.')}", "M": f"M-режим · {clip[4]}"}.get(clip[2], f"Допплер · {clip[4]}")
            text(p, title, sx + 102, y + 11, 13, 600, "#ffffff" if sel else th["text"], w=SBW - 140, h=18, va="c", elide=True)
            text(p, sub, sx + 102, y + 29, 11, 500, C("#ffffff", 0.75) if sel else th["text2"], w=SBW - 140, h=16, va="c", elide=True)
            if clip[5]:
                n = str(clip[5])
                circle(p, sx + SBW - 26, y + 28, 9, fill="#ffffff" if sel else C(th["accent"], 0.9))
                text(p, n, sx + SBW - 35, y + 19, 10.5, 700, th["accent"] if sel else "#ffffff", w=18, h=18, align="c", va="c")
            y += 58
        y += 6
    p.restore()
    yb = sy + sh - 92
    hline(p, sx + 14, yb, SBW - 28, th["sep"])
    for name, n in (("Сидоров А. П.", "31"), ("Кузнецова О. Л.", "18")):
        yb += 8
        icon(p, "p-caret-right", sx + 12, yb + 7, 12, th["text3"])
        icon(p, "p-folder-simple", sx + 28, yb + 5, 16, th["text2"])
        text(p, name, sx + 50, yb, 13, 500, th["text2"], w=150, h=28, va="c")
        text(p, n, sx + SBW - 18 - tw(n, 11.5), yb, 11.5, 500, th["text3"], w=30, h=28, va="c")
        yb += 30
    # inspector (glass)
    glass(cv, ix, sy, INW, sh, 16, blur=24, tint=th["glass_tint"], tint_a=th["glass_a"], border=th["glass_border"], border_a=th["glass_border_a"])
    x = ix + 14
    y = sy + 12
    segmented(cv, x, y, INW - 28 - 34, 30, ["Протокол", "Значения", "Снимок"], 0, th, size=12)
    icon(p, "p-sidebar-simple", ix + INW - 36, y + 6, 19, th["text2"])
    y += 46
    text(p, "Симпсон бипланово", x + 2, y, 16, 700, th["text"])
    text(p, "ЛЖ · объёмы и ФВ · ASE 2025", x + 2, y + 23, 11.5, 500, th["text2"])
    ring(p, ix + INW - 34, y + 18, 14, 0.25, th["accent"], th["bg3"], width=3.5)
    text(p, "1/4", ix + INW - 48, y + 9, 10, 700, th["text2"], w=28, h=18, align="c", va="c", tnum=True)
    y += 52
    rh = 40
    inset_group(p, x, y, INW - 28, SIMPSON_STEPS, th, rh=rh)
    sth = {"accent": th["accent"], "ok": th["ok"], "warn": th["warn"], "text3": th["text3"]}
    for i, (lab, val, st) in enumerate(SIMPSON_STEPS):
        ry = y + i * rh
        status_icon(p, x + 12, ry + 13, st, sth, size=15)
        text(p, lab, x + 36, ry, 13, 600 if st == "current" else 500, th["text"] if st != "todo" else th["text2"], w=160, h=rh, va="c")
        if st == "done":
            text(p, val, x + INW - 28 - 12 - tw(val, 13, 500, tnum=True), ry, 13, 500, th["text2"], w=80, h=rh, va="c", tnum=True)
        elif st == "current":
            s = "Измерить"
            text(p, s, x + INW - 28 - 12 - tw(s, 12.5, 600), ry, 12.5, 600, th["accent_text"], w=80, h=rh, va="c")
        else:
            text(p, "—", x + INW - 28 - 22, ry, 13, 500, th["text3"], w=20, h=rh, va="c")
    y += rh * 4 + 14
    rows = [("ФВ ЛЖ (4-кам.)", "—"), ("ФВ ЛЖ бипланово", "—")]
    inset_group(p, x, y, INW - 28, rows, th, rh=34)
    for i, (a, b) in enumerate(rows):
        text(p, a, x + 12, y + i * 34, 12.5, 500, th["text2"], w=200, h=34, va="c")
        text(p, b, x + INW - 28 - 24, y + i * 34, 12.5, 500, th["text3"], w=20, h=34, va="c")
    y += 68 + 6
    text(p, "Появится после КСО · 4-кам.", x + 12, y, 11, 500, th["text3"])
    y += 24
    inset_group(p, x, y, INW - 28, [0], th, rh=38)
    text(p, "Автопереход к шагу", x + 12, y, 12.5, 500, th["text"], w=200, h=38, va="c")
    toggle(p, x + INW - 28 - 12 - 34, y + 9, True, {"accent": th["ok"], "bg3": th["bg3"], "line2": th["line2"]}, w=34, h=20)
    y += 52
    text(p, "Другие протоколы", x + 2, y, 11, 700, th["text3"])
    y += 20
    others = [pr for pr in PROTOCOLS if pr[0] != "simpson"]
    inset_group(p, x, y, INW - 28, others, th, rh=36)
    for i, (key, name, modes, done, total) in enumerate(others):
        ry = y + i * 36
        col = th["ok"] if done == total else th["accent"]
        ring(p, x + 20, ry + 18, 7.5, done / total, col, C(th["text3"], 0.55), width=2.6)
        text(p, name, x + 38, ry, 12.5, 500, th["text"], w=180, h=36, va="c")
        s = f"{done}/{total}"
        text(p, s, x + INW - 28 - 34 - tw(s, 11.5, 500, tnum=True), ry, 11.5, 500, th["text2"], w=40, h=36, va="c", tnum=True)
        icon(p, "p-caret-right", x + INW - 28 - 24, ry + 12, 12, th["text3"])
    y += 36 * len(others) + 16
    # bottom: report button
    by = sy + sh - 52
    rrect(p, x, by, INW - 28, 34, 9, fill=th["group"], stroke=th["group_border"])
    icon(p, "p-file-text", x + 12, by + 8, 18, th["text"])
    text(p, "Отчёт", x + 38, by, 13, 600, th["text"], w=100, h=34, va="c")
    s = "14 измерений  ⌘R"
    text(p, s, x + INW - 28 - 12 - tw(s, 11.5, 500), by, 11.5, 500, th["text2"], w=140, h=34, va="c")
    p.restore()
    rrect(p, wx, wy, ww, wh, 18, stroke=C("#ffffff", 0.14) if th["mode"] == "dark" else C("#000000", 0.18))
    if own:
        return cv.save(OUT / out_name)
    return cv


def render_b1():
    return render_main(DARK, "B1-mac-main-dark.png")


# ───────────────────────────── B2: Settings (light) ─────────────────────────────

CATS = [
    ("p-gear-six", "#8e8e93", "Основные"),
    ("p-circle-half", "#1c1c1e", "Внешний вид"),
    ("p-ruler", "#0a84ff", "Инструменты"),
    ("p-keyboard", "#8e8e93", "Клавиатура"),
    ("p-heartbeat", "#ff3b30", "Измерения и нормы"),
    ("p-file-text", "#ff9500", "Отчёт"),
    ("p-hard-drives", "#af52de", "DICOM и PACS"),
    ("p-folder-simple", "#34c759", "Хранение"),
    ("p-shield-check", "#007aff", "Конфиденциальность"),
    ("p-bell", "#ff2d55", "Уведомления"),
]


def popup(p, x, y, label, th, w=None):
    w = w or tw(label, 12.5, 500) + 34
    rrect(p, x, y, w, 24, 6, fill="#ffffff", stroke=C("#000000", 0.12))
    text(p, label, x + 10, y, 12.5, 500, th["text"], w=w, h=24, va="c")
    icon(p, "p-caret-up-down", x + w - 20, y + 5, 14, th["text2"])
    return w


def seg_small(cv, x, y, items, sel, th):
    p = cv.p
    w = sum(tw(i, 12, 500) + 26 for i in items) + 4
    rrect(p, x, y, w, 24, 7, fill=C("#000000", 0.06))
    cx = x + 2
    for i, it in enumerate(items):
        iw = tw(it, 12, 500) + 26
        if i == sel:
            shadow(cv, cx, y + 2, iw, 20, 5, blur=4, dy=1, alpha=0.2)
            rrect(p, cx, y + 2, iw, 20, 5, fill="#ffffff")
        text(p, it, cx, y, 12, 600 if i == sel else 500, th["text"], w=iw, h=24, align="c", va="c")
        cx += iw
    return w


def render_b2():
    th = LIGHT
    cv = Canvas(W, H, S, bg="#000000")
    cv.p.drawImage(QRectF(0, 0, W, H), pil_to_qimage(wallpaper("light", 800, 500)))
    render_main(th, cv=cv)
    p = cv.p
    # dim the main window slightly (inactive behind the settings sheet)
    p.fillRect(QRectF(0, MB, W, H - MB), C("#000000", 0.06))
    sw_, sh_ = 940, 772
    sx, sy = (W - sw_) / 2 + 30, (H - sh_) / 2 + 20
    shadow(cv, sx, sy, sw_, sh_, 20, blur=70, dy=30, alpha=0.32)
    p.save()
    p.setClipPath(__import__("kit").rr_path(sx, sy, sw_, sh_, 20))
    p.fillRect(QRectF(sx, sy, sw_, sh_), C("#f2f2f5"))
    SBW = 236
    # sidebar glass
    glass(cv, sx + 8, sy + 8, SBW, sh_ - 16, 14, blur=20, tint="#e9e9ee", tint_a=0.85, border="#000000", border_a=0.06)
    traffic_lights(p, sx + 22, sy + 22)
    y = sy + 52
    rrect(p, sx + 18, y, SBW - 20, 28, 8, fill=C("#000000", 0.06))
    icon(p, "p-magnifying-glass", sx + 26, y + 6, 15, th["text2"])
    text(p, "Поиск", sx + 48, y, 12.5, 500, th["text3"], w=100, h=28, va="c")
    y += 42
    for ico, col, lab in CATS:
        sel = lab == "Инструменты"
        if sel:
            rrect(p, sx + 16, y, SBW - 16, 32, 8, fill=th["accent"])
        rrect(p, sx + 24, y + 5, 22, 22, 6, fill=col)
        icon(p, ico, sx + 28, y + 9, 14, "#ffffff")
        text(p, lab, sx + 56, y, 13, 500, "#ffffff" if sel else th["text"], w=170, h=32, va="c")
        y += 34
    # content
    cx = sx + SBW + 30
    cw = sw_ - SBW - 56
    y = sy + 20
    icon(p, "l-chevron-left", cx - 6, y + 3, 16, th["text2"])
    icon(p, "l-chevron-right", cx + 14, y + 3, 16, th["text3"])
    text(p, "Инструменты", cx + 42, y, 17, 700, th["text"])
    y += 46

    def group(rows_h):
        rrect(p, cx, y, cw, rows_h, 11, fill="#ffffff", stroke=C("#000000", 0.07))

    def sep_at(yy):
        hline(p, cx + 14, yy, cw - 28, C("#000000", 0.07))

    text(p, "Панель инструментов", cx + 4, y, 12, 700, th["text2"])
    y += 22
    rows = [
        ("Расположение панели", ("popup", "Справа")),
        ("Показывать протоколы", ("toggle", True)),
        ("Автопереход к следующему шагу", ("toggle", True)),
        ("Подписи измерений", ("popup", "Русские · ASE 2025")),
    ]
    rh = 40
    group(rh * len(rows))
    for i, (lab, (kind, val)) in enumerate(rows):
        ry = y + i * rh
        if i:
            sep_at(ry)
        text(p, lab, cx + 14, ry, 13, 500, th["text"], w=300, h=rh, va="c")
        if kind == "popup":
            pw = tw(val, 12.5, 500) + 34
            popup(p, cx + cw - 14 - pw, ry + 8, val, th)
        else:
            toggle(p, cx + cw - 14 - 38, ry + 10, val, {"accent": th["accent"], "bg3": "#e5e5ea", "line2": "#d1d1d6"}, w=38, h=21)
    y += rh * len(rows) + 22
    text(p, "Единицы", cx + 4, y, 12, 700, th["text2"])
    y += 22
    group(rh * 2)
    text(p, "Линейные размеры", cx + 14, y, 13, 500, th["text"], w=300, h=rh, va="c")
    w1 = sum(tw(i, 12, 500) + 26 for i in ("мм", "см")) + 4
    seg_small(cv, cx + cw - 14 - w1, y + 8, ["мм", "см"], 0, th)
    sep_at(y + rh)
    text(p, "Скорости PW и TDI", cx + 14, y + rh, 13, 500, th["text"], w=300, h=rh, va="c")
    w2 = sum(tw(i, 12, 500) + 26 for i in ("см/с", "м/с")) + 4
    seg_small(cv, cx + cw - 14 - w2, y + rh + 8, ["см/с", "м/с"], 0, th)
    y += rh * 2 + 6
    text(p, "CW всегда в м/с. Значения пересчитываются в отчёте и экспорте.", cx + 14, y, 11, 500, th["text2"])
    y += 30
    text(p, "Мышь и клавиатура", cx + 4, y, 12, 700, th["text2"])
    y += 22
    rows = [
        ("Правая кнопка в окне снимка", ("popup", "Радиальное меню")),
        ("Подсказки клавиш при удержании ⌥", ("toggle", True)),
        ("Горячие клавиши инструментов", ("button", "Изменить…")),
    ]
    group(rh * len(rows))
    for i, (lab, (kind, val)) in enumerate(rows):
        ry = y + i * rh
        if i:
            sep_at(ry)
        text(p, lab, cx + 14, ry, 13, 500, th["text"], w=320, h=rh, va="c")
        if kind == "popup":
            pw = tw(val, 12.5, 500) + 34
            popup(p, cx + cw - 14 - pw, ry + 8, val, th)
        elif kind == "toggle":
            toggle(p, cx + cw - 14 - 38, ry + 10, val, {"accent": th["accent"], "bg3": "#e5e5ea", "line2": "#d1d1d6"}, w=38, h=21)
        else:
            bw = tw(val, 12.5, 500) + 24
            rrect(p, cx + cw - 14 - bw, ry + 8, bw, 24, 6, fill="#ffffff", stroke=C("#000000", 0.14))
            text(p, val, cx + cw - 14 - bw, ry + 8, 12.5, 500, th["text"], w=bw, h=24, align="c", va="c")
    y += rh * len(rows) + 22
    text(p, "Избранное · клавиши 1–9", cx + 4, y, 12, 700, th["text2"])
    y += 22
    favs = [("1", "МЖП · КДР ЛЖ · ЗСЛЖ"), ("2", "КСР ЛЖ"), ("3", "Симпсон · 4-кам."), ("4", "ОЛП · 4-кам.")]
    fh = 32
    group(fh * len(favs) + 34)
    for i, (k, lab) in enumerate(favs):
        ry = y + i * fh
        if i:
            sep_at(ry)
        rrect(p, cx + 14, ry + 7, 18, 18, 5, fill="#f2f2f5", stroke=C("#000000", 0.1))
        text(p, k, cx + 14, ry + 7, 11, 700, th["text2"], w=18, h=18, align="c", va="c")
        text(p, lab, cx + 44, ry, 13, 500, th["text"], w=300, h=fh, va="c")
        for j in range(3):
            hline(p, cx + cw - 30, ry + 12 + j * 4, 14, C("#000000", 0.25))
    ry = y + fh * len(favs)
    sep_at(ry)
    text(p, "+", cx + 16, ry + 4, 16, 500, th["text2"], w=20, h=26, align="c", va="c")
    vline(p, cx + 42, ry + 9, 16, C("#000000", 0.12))
    text(p, "−", cx + 48, ry + 4, 16, 500, th["text2"], w=20, h=26, align="c", va="c")
    p.restore()
    rrect(p, sx, sy, sw_, sh_, 20, stroke=C("#000000", 0.16))
    return cv.save(OUT / "B2-mac-settings-light.png")


if __name__ == "__main__":
    print(render_b1())
    print(render_b2())
