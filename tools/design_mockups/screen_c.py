"""Variant C — «Изображение в фокусе»: full-bleed viewer with floating glass HUDs."""

from __future__ import annotations

from common import (
    CLIPS,
    KEY_RESULTS,
    PROTOCOLS,
    PT,
    SIMPSON_STEPS,
    THEME_A,
    C,
    QRectF,
    cine_track,
    echo_view,
    hline,
    icon,
    kbd,
    line,
    progress,
    rrect,
    status_icon,
    text,
    thumb,
    toggle,
    tw,
    vline,
    circle,
)
from kit import OUT, Canvas, glass, logo, vgrad

S = 1.5
W, H = 1600, 1000
TH = {**THEME_A, "bg2": "#1b1f24", "bg3": "#2a3037"}
G_TINT, G_A = "#14171b", 0.66


def hud(cv, x, y, w, h, r=14.0, a=G_A):
    glass(cv, x, y, w, h, r, blur=26, tint=G_TINT, tint_a=a, border="#ffffff", border_a=0.10)


def base_image(cv, pad=(18, 84, 0, 0), label=True):
    p = cv.p
    rect = echo_view(p, 0, 0, W, H, TH, pad=pad, lv_label="КДО · 4-кам.  112 мл" if label else None, depth=False)
    return rect


def top_left_pill(cv, compact=False):
    p = cv.p
    th = TH
    w = 300
    hud(cv, 16, 14, w, 46, 14)
    logo(p, 30, 26, 22, light=True)
    text(p, PT["short"], 66, 19, 13.5, 600, th["text"])
    icon(p, "l-chevron-down", 66 + tw(PT["short"], 13.5, 600) + 6, 22, 13, th["text2"])
    text(p, f"Ж · 59 лет · ППТ {PT['bsa']} · {PT['date']}", 66, 37, 11, 500, th["text2"])
    vline(p, 16 + w - 52, 24, 26, C("#ffffff", 0.12))
    rrect(p, 16 + w - 42, 26, 30, 22, 7, fill=C("#ffffff", 0.08))
    text(p, "2", 16 + w - 42, 26, 11.5, 700, th["text2"], w=30, h=22, align="c", va="c")


def top_right_pill(cv):
    p = cv.p
    th = TH
    items_w = 414
    x = W - 16 - items_w
    hud(cv, x, 14, items_w, 46, 14)
    bx = x + 8
    rrect(p, bx, 22, 150, 30, 9, fill=C("#ffffff", 0.07), stroke=C("#ffffff", 0.08))
    icon(p, "l-search", bx + 9, 29, 15, th["text2"])
    text(p, "Команды", bx + 31, 22, 12.5, 500, th["text2"], w=80, h=30, va="c")
    kbd(p, bx + 150 - 52, 28, "Ctrl K", th, fg=th["text2"], bg=C("#ffffff", 0.06), border=C("#ffffff", 0.12))
    bx += 160
    for ico, lab in (("l-file-text", "Отчёт"), ("l-columns-2", None), ("l-ellipsis", None)):
        if lab:
            icon(p, ico, bx + 8, 29, 16, th["text"])
            text(p, lab, bx + 30, 22, 12.5, 600, th["text"], w=60, h=30, va="c")
            bx += 30 + tw(lab, 12.5, 600) + 12
        else:
            icon(p, ico, bx + 8, 29, 16, th["text2"])
            bx += 34
    vline(p, bx + 2, 24, 26, C("#ffffff", 0.12))
    bx += 10
    for k, ico in enumerate(("l-minus", "l-square", "l-x")):
        icon(p, ico, bx + 2 + k * 26, 30, 14 if ico != "l-square" else 12, th["text2"])


def tool_rail(cv, cy=None, tooltip=True):
    p = cv.p
    th = TH
    tools = [
        ("l-mouse-pointer-2", None), ("l-move", None), ("l-zoom-in", None), ("l-sun-medium", None), None,
        ("l-ruler", "L"), ("l-square-dashed", "A"), ("l-spline", "C"), ("l-audio-waveform", "V"), None,
        ("l-crosshair", "K"), ("l-sparkles", None),
    ]
    n_items = sum(1 for t in tools if t)
    n_sep = sum(1 for t in tools if t is None)
    h = n_items * 42 + n_sep * 13 + 12
    y0 = (cy or H / 2) - h / 2
    hud(cv, 16, y0, 52, h, 16)
    y = y0 + 6
    active_y = None
    for t in tools:
        if t is None:
            hline(p, 28, y + 6, 28, C("#ffffff", 0.12))
            y += 13
            continue
        ico, key = t
        if ico == "l-spline":
            rrect(p, 22, y + 2, 40, 38, 10, fill=th["accent"])
            icon(p, ico, 32, y + 11, 20, th["on_accent"], sw=2.0)
            active_y = y
        else:
            dis = ico == "l-audio-waveform"
            icon(p, ico, 32, y + 11, 20, th["text3"] if dis else th["text"])
            if key:
                text(p, key, 51, y + 26, 8.5, 700, th["text3"])
        y += 42
    if tooltip and active_y is not None:
        tx, ty = 78, active_y + 4
        hud(cv, tx, ty, 150, 34, 10, a=0.8)
        text(p, "Контур", tx + 12, ty, 12.5, 600, th["text"], w=80, h=34, va="c")
        kbd(p, tx + 150 - 30, ty + 8, "C", th, fg=th["text2"], bg=C("#ffffff", 0.06), border=C("#ffffff", 0.14))
        text(p, "Симпсон", tx + 66, ty, 11, 500, th["text3"], w=60, h=34, va="c")


def right_card(cv):
    p = cv.p
    th = TH
    w = 324
    x = W - 16 - w
    y = 74
    h = 548
    hud(cv, x, y, w, h, 16)
    ix = x + 16
    yy = y + 14
    icon(p, "r-LV01", ix, yy, 18, "#ffffff")
    text(p, "Симпсон бипланово", ix + 26, yy, 14, 600, th["text"])
    s = "1/4"
    cw = tw(s, 10.5, 700, tnum=True) + 14
    rrect(p, x + w - 16 - 24 - cw, yy, cw, 18, 9, fill=C(th["accent"], 0.18))
    text(p, s, x + w - 16 - 24 - cw, yy, 10.5, 700, th["accent_text"], w=cw, h=18, align="c", va="c", tnum=True)
    icon(p, "l-chevron-up", x + w - 16 - 16, yy + 1, 16, th["text2"])
    yy += 28
    progress(p, ix, yy, w - 32, 4, 0.25, th["accent"], C("#ffffff", 0.1))
    yy += 14
    for lab, val, st in SIMPSON_STEPS:
        if st == "current":
            rrect(p, x + 8, yy, w - 16, 36, 9, fill=C(th["accent"], 0.16), stroke=C(th["accent"], 0.55))
        status_icon(p, ix, yy + 11, st, th, size=14)
        text(p, lab, ix + 24, yy, 12.5, 600 if st == "current" else 500, th["text"] if st != "todo" else th["text2"], w=170, h=36, va="c")
        if st == "done":
            text(p, val, x + w - 16 - tw(val, 12.5, 600, tnum=True), yy, 12.5, 600, th["text"], w=80, h=36, va="c", tnum=True)
        elif st == "current":
            s2 = "кадр КС"
            text(p, s2, x + w - 16 - tw(s2, 11.5, 600), yy, 11.5, 600, th["accent_text"], w=80, h=36, va="c")
        else:
            text(p, "—", x + w - 26, yy, 12.5, 500, th["text3"], w=20, h=36, va="c")
        yy += 38
    yy += 4
    hline(p, ix, yy, w - 32, C("#ffffff", 0.08))
    yy += 10
    for a, b in (("ФВ ЛЖ (4-кам.)", "после КСО"), ("ФВ ЛЖ бипланово", "после 2-кам.")):
        text(p, a, ix, yy, 12, 500, th["text2"])
        text(p, b, x + w - 16 - tw(b, 11.5), yy, 11.5, 500, th["text3"])
        yy += 22
    yy += 6
    toggle(p, ix, yy, True, th, w=28, h=16)
    text(p, "Авто-переход", ix + 36, yy - 1, 11.5, 500, th["text2"])
    s3 = "Пропустить  S"
    text(p, s3, x + w - 16 - tw(s3, 11.5, 500), yy - 1, 11.5, 500, th["text2"])
    yy += 30
    hline(p, x, yy, w, C("#ffffff", 0.08))
    yy += 12
    text(p, "ДРУГИЕ ПРОТОКОЛЫ", ix, yy, 10, 600, th["text3"], spacing=0.6)
    yy += 20
    chips = [(name, done, total) for key, name, modes, done, total in PROTOCOLS if key != "simpson"]
    cx = ix
    for name, done, total in chips:
        s4 = f"{name}  {done}/{total}"
        cw2 = tw(s4, 11, 500, tnum=True) + 30
        if cx + cw2 > x + w - 16:
            cx = ix
            yy += 30
        rrect(p, cx, yy, cw2, 24, 12, fill=C("#ffffff", 0.06), stroke=C("#ffffff", 0.08))
        col = th["ok"] if done == total else (th["accent"] if done else th["text3"])
        circle(p, cx + 11, yy + 12, 3.5, fill=col)
        text(p, s4, cx + 20, yy, 11, 500, th["text2"], w=cw2, h=24, va="c", tnum=True)
        cx += cw2 + 6
    yy += 38
    hline(p, x, yy, w, C("#ffffff", 0.08))
    yy += 12
    text(p, "СВОДКА", ix, yy, 10, 600, th["text3"], spacing=0.6)
    yy += 20
    cw3 = (w - 32) / 3
    for i, (lab, val, unit) in enumerate(KEY_RESULTS):
        cx = ix + (i % 3) * cw3
        cy = yy + (i // 3) * 42
        text(p, lab, cx, cy, 10.5, 500, th["text3"])
        if val == "—":
            text(p, "—", cx, cy + 14, 15, 600, th["text3"])
        else:
            vw = text(p, val, cx, cy + 13, 15, 600, th["text"], tnum=True)
            text(p, unit, cx + vw + 3, cy + 18, 10, 500, th["text2"])


def top_center_hud(cv):
    p = cv.p
    th = TH
    w = 560
    x = W / 2 - w / 2
    hud(cv, x, 14, w, 62, 14)
    text(p, "4-кам. · 2D · 16 см · кадр 1 / 83 · КД", x + 16, 22, 11, 600, th["text2"])
    st = "СИМПСОН · ШАГ 2/4"
    text(p, st, x + w - 16 - tw(st, 10, 700, spacing=0.6), 22, 10, 700, th["accent_text"], spacing=0.6)
    text(p, "КСО · 4-кам. — перейдите к кадру конца систолы", x + 16, 40, 13.5, 600, th["text"])
    kx = x + w - 16
    for k, lab in reversed((("Enter", "готово"), ("Esc", "выйти"))):
        lw = tw(lab, 11, 500)
        kx -= lw
        text(p, lab, kx, 42, 11, 500, th["text2"])
        kw = tw(k, 10, 600) + 10
        kx -= kw + 5
        kbd(p, kx, 42, k, th, fg=th["text2"], bg=C("#ffffff", 0.06), border=C("#ffffff", 0.14))
        kx -= 12


def bottom_dock(cv):
    p = cv.p
    th = TH
    # cine capsule
    cw = 720
    cx = W / 2 - cw / 2
    cy = H - 16 - 96 - 10 - 48
    hud(cv, cx, cy, cw, 48, 24)
    icon(p, "l-step-back", cx + 18, cy + 15, 18, th["text"])
    circle(p, cx + 66, cy + 24, 17, fill=th["accent"])
    icon(p, "l-play", cx + 59, cy + 16.5, 15, th["on_accent"], sw=2.4)
    icon(p, "l-step-forward", cx + 96, cy + 15, 18, th["text"])
    cine_track(p, cx + 132, cy + 10, cw - 132 - 120, 28, th, track_bg=C("#ffffff", 0.05), r=8)
    text(p, "1 / 83", cx + cw - 104, cy + 7, 13, 600, th["text"], tnum=True)
    text(p, "1× · 30 к/с", cx + cw - 104, cy + 25, 10.5, 500, th["text3"])
    icon(p, "l-repeat", cx + cw - 34, cy + 15, 18, th["accent"])
    # filmstrip tray
    fw = 1000
    fx = W / 2 - fw / 2
    fy = H - 16 - 96
    hud(cv, fx, fy, fw, 96, 16)
    by_id = {c[0]: c for c in CLIPS}
    ids = ["c1", "c2", "c3", "c4", "c5", "c7", "c8", "c9", "c10"]
    tx = fx + 12
    for cid in ids:
        thumb(p, tx, fy + 12, 96, 72, by_id[cid], th, selected=cid == "c1", r=8)
        tx += 104
    rrect(p, tx, fy + 12, 50, 72, 8, fill=C("#ffffff", 0.06), stroke=C("#ffffff", 0.1))
    text(p, "+15", tx, fy + 12, 13, 600, th["text2"], w=50, h=56, align="c", va="c")
    text(p, "G", tx, fy + 52, 10, 700, th["text3"], w=50, h=20, align="c", va="c")


def render_c1():
    cv = Canvas(W, H, S, bg="#000000")
    base_image(cv)
    top_left_pill(cv)
    top_center_hud(cv)
    top_right_pill(cv)
    tool_rail(cv, cy=470)
    right_card(cv)
    bottom_dock(cv)
    return cv.save(OUT / "C1-focus-main.png")


PALETTE = [
    ("Протокол", [("r-LV01", "Симпсон бипланово — продолжить", "шаг 2 из 4 · КСО · 4-кам.", "Enter", True), ("r-LV01", "Симпсон бипланово — начать заново", "сбросит 1 измерение", None, False)]),
    ("Измерения", [("l-spline", "КСО · 2-кам.", "Симпсон · контур · 2D", "", False), ("l-spline", "КДО · 2-кам.", "Симпсон · контур · 2D", "", False), ("l-chart-line", "ФВ ЛЖ (Симпсон, 4-кам.)", "расчёт · появится после КСО · 4-кам.", None, False)]),
    ("Команды", [("l-columns-2", "Сравнить: 4-кам. ↔ 2-кам.", "две панели · синхронный кадр", "Ctrl 2", False), ("l-settings", "Настройки → Инструменты", "протоколы, клавиши, единицы", None, False)]),
]


def render_c2():
    th = TH
    cv = Canvas(W, H, S, bg="#000000")
    p = cv.p
    base_image(cv, pad=(12, 30, 0, 0))
    # faint corner info (no chrome)
    text(p, f"{PT['short']} · 4-кам. · 16 см · кадр 1/83", 20, 16, 11.5, 600, C("#ffffff", 0.55))
    text(p, "СИМПСОН · ШАГ 2/4", 20, 34, 10, 700, C(th["accent_text"], 0.7), spacing=0.6)
    # thin cine line at the very bottom
    p.fillRect(QRectF(0, H - 3, W, 3), C("#ffffff", 0.08))
    p.fillRect(QRectF(0, H - 3, 18, 3), C(th["accent"], 0.9))
    # edge hints
    hints = [
        (16, H / 2 - 40, "T", "Инструменты", "v"),
        (W - 16, H / 2 - 40, "R", "Результаты", "v"),
        (W / 2, H - 46, "G", "Клипы и кино", "h"),
    ]
    for x, y, k, lab, orient in hints:
        lw = tw(lab, 11, 500) + 40
        if orient == "v":
            bx = x if x < W / 2 else x - lw
        else:
            bx = x - lw / 2
        hud(cv, bx, y, lw, 26, 13, a=0.5)
        kbd(p, bx + 5, y + 4.5, k, th, h=17, fg=th["text2"], bg=C("#ffffff", 0.06), border=C("#ffffff", 0.14))
        text(p, lab, bx + 30, y, 11, 500, C("#ffffff", 0.6), w=lw, h=26, va="c")
    # dim behind the palette
    p.fillRect(QRectF(0, 0, W, H), C("#000000", 0.38))
    pw, px = 680, W / 2 - 340
    py = 150
    ph = 524
    hud(cv, px, py, pw, ph, 16, a=0.82)
    # input
    icon(p, "l-search", px + 18, py + 18, 18, th["text2"])
    text(p, "сим", px + 46, py + 12, 17, 500, th["text"])
    cx = px + 46 + tw("сим", 17, 500) + 2
    p.fillRect(QRectF(cx, py + 16, 1.6, 22), C(th["accent"]))
    s = "Ctrl K"
    kbd(p, px + pw - 16 - tw(s, 10, 600) - 10, py + 18, s, th, fg=th["text2"], bg=C("#ffffff", 0.06), border=C("#ffffff", 0.14))
    hline(p, px, py + 54, pw, C("#ffffff", 0.08))
    y = py + 64
    for sec, rows in PALETTE:
        text(p, sec.upper(), px + 18, y, 10, 600, th["text3"], spacing=0.6)
        y += 18
        for ico, title, sub, key, sel in rows:
            if sel:
                rrect(p, px + 8, y, pw - 16, 46, 10, fill=C(th["accent"], 0.18), stroke=C(th["accent"], 0.5))
            icon(p, ico, px + 20, y + 13, 20, "#ffffff" if ico.startswith("r-") else (th["accent_text"] if sel else th["text2"]))
            # highlight the matched prefix
            if title.lower().startswith("сим"):
                xx = px + 52
                xx += text(p, title[:3], xx, y + 6, 13.5, 700, th["accent_text"])
                text(p, title[3:], xx, y + 6, 13.5, 600, th["text"])
            else:
                text(p, title, px + 52, y + 6, 13.5, 600 if sel else 500, th["text"])
            text(p, sub, px + 52, y + 25, 11, 500, th["text3"])
            if key:
                kbd(p, px + pw - 22 - tw(key, 10, 600) - 10, y + 14, key, th, fg=th["text2"], bg=C("#ffffff", 0.06), border=C("#ffffff", 0.14))
            y += 48
        y += 6
    hline(p, px, py + ph - 36, pw, C("#ffffff", 0.08))
    fx = px + 18
    for k, lab in (("↑↓", "выбор"), ("Enter", "выполнить"), ("Tab", "уточнить"), ("Esc", "закрыть")):
        fx += kbd(p, fx, py + ph - 27, k, th, fg=th["text2"], bg=C("#ffffff", 0.06), border=C("#ffffff", 0.14)) + 6
        fx += text(p, lab, fx, py + ph - 27, 11, 500, th["text3"], w=120, h=17, va="c") + 16
    s = "ищет по RU, EN (LVESV) и синонимам"
    text(p, s, px + pw - 18 - tw(s, 11, 500), py + ph - 27, 11, 500, th["text3"], w=300, h=17, va="c")
    return cv.save(OUT / "C2-focus-clean-palette.png")


if __name__ == "__main__":
    print(render_c1())
    print(render_c2())
