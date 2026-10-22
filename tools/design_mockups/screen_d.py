"""Variant D — «Протокол → отчёт»: stepper workflow, protocol checklist and a live report."""

from __future__ import annotations

from common import (
    CLIPS,
    PT,
    REPORT_DIAST,
    REPORT_LV,
    REPORT_RIGHT,
    THEME_A,
    C,
    QRectF,
    button,
    cine_track,
    echo_view,
    hline,
    icon,
    kbd,
    line,
    pill,
    progress,
    ring,
    rrect,
    search_field,
    section_label,
    status_icon,
    text,
    thumb,
    tw,
    vline,
    win_controls,
    circle,
)
from kit import OUT, Canvas, logo, shadow, vgrad, draw_image_fit, pil_to_qimage, doppler_image
from screen_a import status_bar

S = 1.5
W, H = 1600, 1000
TB = 58
SB = 26
TH = THEME_A
PAPER = {
    "bg": "#f6f5f1",
    "text": "#1f2328",
    "text2": "#57606a",
    "text3": "#8c959f",
    "rule": "#d9dde2",
    "ph": "#9a5b00",
    "ph_bg": "#fff1d6",
    "ph_border": "#e9b562",
    "cur": "#0b8f8a",
    "cur_bg": "#dcf5f3",
}

STEPS = [("Клипы", "24 клипа"), ("Измерения", "11 из 18"), ("Заключение", "черновик"), ("Экспорт", "PDF · DICOM SR")]


def top_bar(p, active: int, saved: str = "10:42"):
    th = TH
    p.fillRect(QRectF(0, 0, W, TB), C(th["bg0"]))
    hline(p, 0, TB - 1, W, th["line"])
    logo(p, 16, 17, 24, light=True)
    # study chip
    x = 54
    s = f"{PT['short']} · {PT['date']}"
    cw = tw(s, 12.5, 600) + 56
    rrect(p, x, 12, cw, 34, 8, fill=th["bg2"], stroke=th["line"])
    icon(p, "l-heart-pulse", x + 10, 21, 16, th["accent"])
    text(p, s, x + 32, 12, 12.5, 600, th["text"], w=cw, h=34, va="c")
    icon(p, "l-chevron-down", x + cw - 22, 22, 13, th["text3"])
    # stepper
    sx0 = 470
    gap = 170
    for i, (lab, sub) in enumerate(STEPS):
        cx = sx0 + i * gap
        cy = 22
        if i < len(STEPS) - 1:
            col = th["ok"] if i < active else th["line2"]
            line(p, cx + 18, cy, cx + gap - 18, cy, col, 2.0)
        if i < active:
            circle(p, cx, cy, 12, fill=th["ok"])
            icon(p, "l-check", cx - 7, cy - 7, 14, "#0b1a10", sw=3)
        elif i == active:
            circle(p, cx, cy, 13, fill=th["accent"])
            text(p, str(i + 1), cx - 12, cy - 12, 12, 700, th["on_accent"], w=24, h=24, align="c", va="c")
            circle(p, cx, cy, 17, stroke=C(th["accent"], 0.35), sw=2)
        else:
            circle(p, cx, cy, 11.5, stroke=th["line2"], sw=1.5)
            text(p, str(i + 1), cx - 12, cy - 12, 11.5, 600, th["text3"], w=24, h=24, align="c", va="c")
        text(p, lab, cx - 60, 37, 12, 600 if i == active else 500, th["text"] if i <= active else th["text2"], w=120, h=16, align="c", va="c")
    # right
    xr = W - 3 * 46 - 12
    win_controls(p, W, 0, 40, th["text2"])
    xr -= 34
    icon(p, "l-ellipsis", xr + 8, 21, 16, th["text2"])
    bw = button(p, 0, -100, th, "Сравнить", "l-columns-2", "ghost", h=32)
    xr -= bw + 4
    button(p, xr, 13, th, "Сравнить", "l-columns-2", "ghost", h=32)
    s2 = f"Сохранено · {saved}"
    xr -= tw(s2, 11.5, 500) + 30
    icon(p, "l-circle-check", xr, 22, 14, th["ok"])
    text(p, s2, xr + 19, 13, 11.5, 500, th["text2"], w=140, h=32, va="c")


PLAN = [
    # name, done, total, state, steps (label, value, state)
    ("ЛЖ линейно", 2, 2, "done", None),
    ("Симпсон бипланово", 1, 4, "current", [("КДО · 4-кам.", "112 мл", "done"), ("КСО · 4-кам.", "сейчас", "current"), ("КДО · 2-кам.", "клип есть", "todo"), ("КСО · 2-кам.", "", "todo")]),
    ("Объём ЛП", 0, 2, "todo", None),
    ("Диастолическая функция", 5, 7, "partial", None),
    ("Аортальный стеноз", 0, 4, "warn", None),
    ("ТР / СДЛА", 2, 2, "done", None),
]


def plan_column(p, top, bottom, lw=304):
    th = TH
    p.fillRect(QRectF(0, top, lw, bottom - top), C(th["bg1"]))
    vline(p, lw - 1, top, bottom - top, th["line"])
    x = 18
    y = top + 16
    text(p, "План исследования", x, y, 14.5, 600, th["text"])
    text(p, "ASE 2025 · базовая ТТЭ", x, y + 22, 11, 500, th["text3"])
    ring(p, lw - 40, y + 18, 18, 10 / 21, th["accent"], th["bg3"], width=4)
    text(p, "48%", lw - 58, y + 9, 10.5, 700, th["text"], w=36, h=18, align="c", va="c", tnum=True)
    y += 50
    text(p, "10 из 21 обязательного шага · 2 протокола готовы", x, y, 11, 500, th["text2"])
    y += 26
    for name, done, total, state, steps in PLAN:
        rowh = 40
        if state == "current":
            rrect(p, 10, y, lw - 20, 40 + 4 * 34 + 14, 10, fill=th["bg2"], stroke=C(th["accent"], 0.5))
        st_icon = {"done": "done", "current": "current", "todo": "todo", "partial": "current", "warn": "todo"}[state]
        status_icon(p, x + 2, y + 13, st_icon, th, size=14)
        text(p, name, x + 26, y, 12.5, 600 if state == "current" else 500, th["text"], w=190, h=rowh, va="c")
        s = f"{done}/{total}"
        text(p, s, lw - 22 - tw(s, 11, 600, tnum=True), y, 11, 600, th["ok"] if done == total else (th["accent_text"] if done else th["text3"]), w=40, h=rowh, va="c", tnum=True)
        y += rowh
        if steps:
            for lab, val, st in steps:
                if st == "current":
                    rrect(p, 22, y + 2, lw - 44, 30, 7, fill=C(th["accent"], 0.15))
                status_icon(p, x + 16, y + 10, st, th, size=12)
                text(p, lab, x + 36, y, 12, 600 if st == "current" else 500, th["text"] if st != "todo" else th["text2"], w=150, h=34, va="c")
                vcol = th["accent_text"] if st == "current" else (th["text2"] if st == "done" else th["text3"])
                text(p, val, lw - 32 - tw(val, 11.5, 500, tnum=True), y, 11.5, 500, vcol, w=90, h=34, va="c", tnum=True)
                y += 34
            y += 14
        if state == "warn":
            y -= 6
            icon(p, "l-triangle-alert", x + 26, y + 2, 12, th["warn"])
            text(p, "нет клипа CW · АК", x + 42, y, 11, 500, th["warn"])
            y += 22
        if state == "partial":
            y -= 6
            text(p, "осталось: e′ лат., ИОЛП (из «Объём ЛП»)", x + 26, y, 11, 500, th["text3"])
            y += 22
    y += 6
    icon(p, "l-plus", x + 2, y + 1, 14, th["text3"])
    text(p, "Добавить протокол", x + 26, y, 12, 500, th["text3"])
    # mode switch at bottom
    by = bottom - 54
    hline(p, 0, by, lw - 1, th["line"])
    rrect(p, 14, by + 12, lw - 28, 30, 7, fill=th["bg2"], stroke=th["line"])
    half = (lw - 28) / 2
    rrect(p, 16, by + 14, half - 4, 26, 6, fill=th["bg3"], stroke=th["line2"])
    text(p, "По протоколу", 14, by + 12, 12, 600, th["text"], w=half, h=30, align="c", va="c")
    text(p, "Свободно", 14 + half, by + 12, 12, 500, th["text2"], w=half, h=30, align="c", va="c")


def step_header(p, x, y, w):
    th = TH
    h = 66
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y + h - 1, w, th["line"])
    text(p, "ШАГ 2 ИЗ 4 · СИМПСОН БИПЛАНОВО", x + 18, y + 12, 10.5, 700, th["accent_text"], spacing=0.6)
    text(p, "КСО · 4-кам. — обведите эндокард ЛЖ в конце систолы", x + 18, y + 31, 15.5, 600, th["text"])
    xr = x + w - 16
    bw = button(p, 0, -100, th, "Готово", "l-check", "primary", h=34, kbd_s=None, weight=600)
    xr -= bw
    button(p, xr, y + 16, th, "Готово", "l-check", "primary", h=34, weight=600)
    kbd(p, xr - 50, y + 24, "Enter", th)
    xr -= 62
    bw = button(p, 0, -100, th, "Пропустить", None, "outline", h=34)
    xr -= bw + 8
    button(p, xr, y + 16, th, "Пропустить", None, "outline", h=34)
    return h


def suggested_strip(p, x, y, w, h):
    th = TH
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y, w, th["line"])
    text(p, "Подходят для шага", x + 18, y + 12, 12, 600, th["text"])
    text(p, "4-кам. · 3 из 24 клипов", x + 18, y + 30, 11, 500, th["text3"])
    by_id = {c[0]: c for c in CLIPS}
    tx = x + 190
    for i, cid in enumerate(["c1", "c13", "c12"]):
        thumb(p, tx, y + 10, 110, h - 20, by_id[cid], th, selected=(i == 0), r=7)
        if i == 0:
            rrect(p, tx + 110 - 66, y + h - 10 - 40, 60, 16, 4, fill=C("#000000", 0.6))
            text(p, "★ лучший", tx + 110 - 66, y + h - 10 - 40, 9.5, 700, th["warn"], w=60, h=16, align="c", va="c")
        tx += 122
    s = "Все клипы · 24"
    text(p, s, x + w - 36 - tw(s, 12, 600), y, 12, 600, th["accent_text"], w=140, h=h, va="c")
    icon(p, "l-chevron-right", x + w - 32, y + h / 2 - 8, 16, th["accent_text"])


def cine_strip(p, x, y, w, h):
    th = TH
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y, w, th["line"])
    cy = y + h / 2
    bx = x + 16
    icon(p, "l-step-back", bx, cy - 9, 18, th["text2"])
    circle(p, bx + 48, cy, 16, fill=th["accent"])
    icon(p, "l-play", bx + 41, cy - 7, 14, th["on_accent"], sw=2.4)
    icon(p, "l-step-forward", bx + 78, cy - 9, 18, th["text2"])
    tx0 = bx + 112
    tx1 = x + w - 230
    cine_track(p, tx0, cy - 15, tx1 - tx0, 30, th, cur=0)
    chip = "КС ≈ кадр 11 · по ЭКГ"
    cw = tw(chip, 11, 600) + 34
    rrect(p, tx1 + 12, cy - 13, cw, 26, 13, fill=C(th["warn"], 0.14), stroke=C(th["warn"], 0.5))
    icon(p, "l-arrow-right", tx1 + 22, cy - 6, 12, th["warn"], sw=2.2)
    text(p, chip, tx1 + 38, cy - 13, 11, 600, th["warn"], w=cw, h=26, va="c")


def paper_value(p, x, y, lab, val, unit, state="done", w=196):
    P = PAPER
    text(p, lab, x, y, 11.5, 500, P["text2"])
    vx = max(x + 104, x + tw(lab, 11.5, 500) + 10)
    if state == "done":
        vw = text(p, val, vx, y - 0.5, 12, 700, P["text"], tnum=True)
        if unit:
            text(p, unit, vx + vw + 4, y, 11, 500, P["text2"])
    elif state == "current":
        s = "измеряется…"
        cw = tw(s, 10.5, 700) + 22
        rrect(p, vx - 4, y - 3, cw, 20, 5, fill=P["cur_bg"], stroke=P["cur"], sw=1.2)
        circle(p, vx + 5, y + 7, 3, fill=P["cur"])
        text(p, s, vx + 12, y - 3, 10.5, 700, P["cur"], w=cw, h=20, va="c")
    else:
        s = val
        cw = tw(s, 10.5, 600) + 14
        r = rrect(p, vx - 4, y - 3, cw, 20, 5, fill=P["ph_bg"])
        from kit import QPen, Qt

        pen = QPen(C(P["ph_border"]), 1.0)
        pen.setDashPattern([3, 2])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(vx - 3.5, y - 2.5, cw - 1, 19), 5, 5)
        text(p, s, vx - 4, y - 3, 10.5, 600, P["ph"], w=cw, h=20, align="c", va="c")


def paper_section(p, x, y, w, title):
    P = PAPER
    text(p, title, x, y, 12.5, 700, P["text"])
    hline(p, x, y + 20, w, P["rule"])
    return y + 30


def report_panel(p, cv, x, top, bottom):
    th = TH
    P = PAPER
    w = W - x
    p.fillRect(QRectF(x, top, w, bottom - top), C("#0e1013"))
    vline(p, x, top, bottom - top, th["line"])
    text(p, "Отчёт", x + 18, top + 12, 13.5, 600, th["text"])
    pill(p, x + 18 + tw("Отчёт", 13.5, 600) + 8, top + 12, "черновик", th["warn"], C(th["warn"], 0.14), h=18, size=10)
    text(p, "заполняется из измерений автоматически", x + 18, top + 32, 11, 500, th["text3"])
    for i, ico in enumerate(("l-maximize-2", "l-printer")):
        icon(p, ico, x + w - 30 - i * 30, top + 18, 16, th["text2"])
    px, py = x + 14, top + 58
    pw, ph = w - 28, bottom - py - 12
    shadow(cv, px, py, pw, ph, 6, blur=18, dy=6, alpha=0.5)
    rrect(p, px, py, pw, ph, 6, fill=P["bg"])
    p.save()
    p.setClipRect(QRectF(px, py, pw, ph))
    ix = px + 22
    iw = pw - 44
    y = py + 20
    text(p, "Протокол трансторакальной ЭхоКГ", ix, y, 15, 700, P["text"])
    y += 24
    text(p, f"{PT['name']} · {PT['sex']} · {PT['age']} · ID {PT['pid']}", ix, y, 11.5, 600, P["text"])
    y += 17
    text(p, f"{PT['date']} · {PT['device']} · {PT['height']} · {PT['weight']} · ППТ {PT['bsa']}", ix, y, 11, 500, P["text2"])
    y += 26
    colw = iw / 2
    y = paper_section(p, ix, y, iw, "Левый желудочек")
    items = REPORT_LV
    for i, (lab, val, unit) in enumerate(items):
        paper_value(p, ix + (i % 2) * colw, y + (i // 2) * 21, lab, val, unit)
    y += ((len(items) + 1) // 2) * 21 + 4
    paper_value(p, ix, y, "КДО · 4-кам.", "112", "мл")
    paper_value(p, ix + colw, y, "КСО · 4-кам.", "", "", state="current")
    y += 22
    paper_value(p, ix, y, "ФВ ЛЖ (Симпсон)", "ждёт 3 изм.", "", state="ph")
    y += 30
    y = paper_section(p, ix, y, iw, "Левое предсердие")
    paper_value(p, ix, y, "ОЛП · 4-кам.", "измерить", "", state="ph")
    paper_value(p, ix + colw, y, "ИОЛП", "—", "", state="ph")
    y += 30
    y = paper_section(p, ix, y, iw, "Диастолическая функция ЛЖ")
    diast_now = [("E", "78", "см/с", "done"), ("A", "64", "см/с", "done"), ("E/A", "1,2", "", "done"), ("e′ септ.", "8", "см/с", "done"), ("e′ лат.", "измерить", "", "ph"), ("E/e′ ср.", "—", "", "ph")]
    for i, (lab, val, unit, st) in enumerate(diast_now):
        paper_value(p, ix + (i % 2) * colw, y + (i // 2) * 21, lab, val, unit, state=st)
    y += 3 * 21 + 9
    y = paper_section(p, ix, y, iw, "Аортальный клапан")
    paper_value(p, ix, y, "Vmax АК", "измерить", "", state="ph")
    paper_value(p, ix + colw, y, "Град. ср. АК", "—", "", state="ph")
    y += 30
    y = paper_section(p, ix, y, iw, "Правые отделы · ТР")
    for i, (lab, val, unit) in enumerate(REPORT_RIGHT):
        paper_value(p, ix + (i % 2) * colw, y + (i // 2) * 21, lab, val, unit)
    y += 2 * 21 + 9
    y = paper_section(p, ix, y, iw, "Заключение")
    text(p, "Формулируется на шаге 3 — из фраз и измерений; врач подтверждает каждую формулировку.", ix, y, 11, 500, P["text3"], w=iw, wrap=True, lh=15)
    p.restore()
    # fade bottom of the paper
    p.fillRect(QRectF(px, py + ph - 30, pw, 30), vgrad(py + ph - 30, py + ph, [(0, C(P["bg"], 0.0)), (1, C(P["bg"], 1.0))]))


def render_d1():
    th = TH
    cv = Canvas(W, H, S, bg=th["bg0"])
    p = cv.p
    top_bar(p, active=1)
    top, bottom = TB, H - SB
    LW = 304
    RX = W - 452
    plan_column(p, top, bottom, LW)
    cx, cw = LW, RX - LW
    hh = step_header(p, cx, top, cw)
    sug_h, cine_h = 92, 58
    vy = top + hh
    vh = bottom - sug_h - cine_h - vy
    echo_view(p, cx, vy, cw, vh, th, pad=(16, 16, 40, 70), lv_label="КДО · 4-кам.  112 мл")
    # minimal viewer tools (top-right)
    tx = cx + 20
    ty = vy + vh - 50
    rrect(p, tx - 6, ty, 4 * 32 + 12, 36, 9, fill=C("#000000", 0.6), stroke=C("#ffffff", 0.1))
    for i, ico in enumerate(("l-move", "l-zoom-in", "l-sun-medium", "l-rotate-ccw")):
        icon(p, ico, tx + i * 32 + 8, ty + 10, 16, th["text2"])
    rrect(p, cx + 14, vy + 12, 150, 36, 9, fill=C("#000000", 0.6), stroke=C(th["accent"], 0.5))
    icon(p, "l-spline", cx + 26, vy + 22, 16, th["accent_text"])
    text(p, "Контур", cx + 50, vy + 12, 12.5, 600, th["accent_text"], w=80, h=36, va="c")
    kbd(p, cx + 14 + 150 - 30, vy + 21, "C", th)
    text(p, "4-кам. · кадр 1 / 83 · КД", cx + 16, vy + 56, 10.5, 600, C("#ffffff", 0.6))
    suggested_strip(p, cx, bottom - sug_h - cine_h, cw, sug_h)
    cine_strip(p, cx, bottom - cine_h, cw, cine_h)
    report_panel(p, cv, RX, top, bottom)
    status_bar(
        p,
        th,
        [("l-circle-check", "Сохранено · 10:42", th["ok"]), (None, "Калибровка: DICOM · 0,28 мм/пикс.", th["text2"])],
        [("l-triangle-alert", "Только для исследований", th["warn"]), (None, "SonoForge 0.4.0", th["text3"])],
    )
    return cv.save(OUT / "D1-workflow-measure.png")


# ───────────────────────────── D2: conclusion stage ─────────────────────────────

SECTIONS = [
    ("Пациент и исследование", "done", None),
    ("Левый желудочек", "done", None),
    ("Левое предсердие", "done", None),
    ("Диастолическая функция", "done", None),
    ("Клапаны", "done", None),
    ("Правые отделы", "done", None),
    ("Заключение", "current", None),
    ("Ключевые изображения · 2", "done", None),
]

PHRASES = [
    ("Левый желудочек", ["Полость ЛЖ не расширена", "Толщина стенок ЛЖ в норме", "Глобальная систолическая функция ЛЖ сохранена (ФВ 59 %)", "Зон нарушения локальной сократимости не выявлено"]),
    ("Диастолическая функция", ["Диастолическая функция ЛЖ не нарушена", "Давление наполнения ЛЖ не повышено"]),
    ("Клапаны", ["Клапанный аппарат без гемодинамически значимых изменений"]),
    ("Правые отделы", ["Признаков лёгочной гипертензии нет (СДЛА 26 мм рт. ст.)"]),
]


USED_PHRASES = {
    "Полость ЛЖ не расширена",
    "Толщина стенок ЛЖ в норме",
    "Глобальная систолическая функция ЛЖ сохранена (ФВ 59 %)",
    "Диастолическая функция ЛЖ не нарушена",
    "Признаков лёгочной гипертензии нет (СДЛА 26 мм рт. ст.)",
}


def render_d2():
    th = TH
    P = PAPER
    cv = Canvas(W, H, S, bg=th["bg0"])
    p = cv.p
    top_bar(p, active=2, saved="10:58")
    top, bottom = TB, H - SB
    LW = 280
    p.fillRect(QRectF(0, top, LW, bottom - top), C(th["bg1"]))
    vline(p, LW - 1, top, bottom - top, th["line"])
    x = 18
    y = top + 16
    text(p, "Разделы отчёта", x, y, 14.5, 600, th["text"])
    y += 34
    for name, st, _ in SECTIONS:
        if st == "current":
            rrect(p, 10, y, LW - 20, 34, 8, fill=C(th["accent"], 0.14), stroke=C(th["accent"], 0.45))
        status_icon(p, x + 2, y + 10, st, th, size=14)
        text(p, name, x + 26, y, 12.5, 600 if st == "current" else 500, th["text"], w=210, h=34, va="c")
        y += 36
    y += 14
    hline(p, 14, y, LW - 28, th["line"])
    y += 16
    text(p, "Полнота · ASE 2025", x, y, 12.5, 600, th["text"])
    y += 24
    rrect(p, 14, y, LW - 28, 50, 8, fill=C(th["ok"], 0.10), stroke=C(th["ok"], 0.35))
    icon(p, "l-circle-check", 26, y + 16, 18, th["ok"])
    text(p, "Обязательные шаги: 21 из 21", 52, y + 8, 12.5, 600, th["text"])
    text(p, "все протоколы завершены", 52, y + 27, 11, 500, th["text2"])
    y += 62
    rrect(p, 14, y, LW - 28, 92, 8, fill=th["bg2"], stroke=th["line"])
    text(p, "Рекомендуемые: 2 не заполнены", 26, y + 10, 12, 600, th["text"])
    for i, lab in enumerate(("TAPSE", "S′ ПЖ (TDI)")):
        yy = y + 34 + i * 26
        status_icon(p, 26, yy + 2, "todo", th, size=12)
        text(p, lab, 46, yy, 12, 500, th["text2"])
        s = "измерить"
        text(p, s, LW - 26 - tw(s, 11.5, 600), yy, 11.5, 600, th["accent_text"])
    # centre: A4 page preview
    RW = 336
    cx0, cx1 = LW, W - RW
    p.fillRect(QRectF(cx0, top, cx1 - cx0, bottom - top), C("#0e1013"))
    # page toolbar
    text(p, "Предпросмотр · A4", cx0 + 18, top + 12, 12, 600, th["text2"])
    zx = cx1 - 150
    rrect(p, zx, top + 8, 132, 28, 7, fill=th["bg2"], stroke=th["line"])
    icon(p, "l-minus", zx + 10, top + 15, 14, th["text2"])
    text(p, "100 %", zx + 30, top + 8, 11.5, 600, th["text2"], w=72, h=28, align="c", va="c", tnum=True)
    icon(p, "l-plus", zx + 108, top + 15, 14, th["text2"])
    pw = 640
    px = (cx0 + cx1) / 2 - pw / 2
    py = top + 48
    ph = bottom - py + 40
    shadow(cv, px, py, pw, ph, 4, blur=22, dy=8, alpha=0.6)
    p.save()
    p.setClipRect(QRectF(cx0, top, cx1 - cx0, bottom - top))
    rrect(p, px, py, pw, ph, 3, fill="#ffffff")
    ix, iw = px + 44, pw - 88
    y = py + 34
    logo(p, ix, y, 26, light=False)
    text(p, "Отделение функциональной диагностики", ix + 34, y + 1, 11, 600, P["text"])
    text(p, "Медицинский центр «Пример» · бланк настраивается", ix + 34, y + 16, 10, 500, P["text2"])
    s = "SonoForge · только для исследований"
    text(p, s, ix + iw - tw(s, 9.5, 500), y + 8, 9.5, 500, P["text3"])
    y += 44
    hline(p, ix, y, iw, P["rule"])
    y += 16
    text(p, "Протокол трансторакальной эхокардиографии", ix, y, 16, 700, P["text"])
    y += 28
    meta = [("Пациент", PT["name"]), ("Пол, возраст", "Ж, 59 лет (12.03.1967)"), ("ID", PT["pid"]), ("Дата", f"{PT['date']} {PT['time']}"), ("Рост / вес / ППТ", f"{PT['height']} / {PT['weight']} / {PT['bsa']}"), ("ЧСС, ритм", "68 уд/мин, синусовый")]
    for i, (a, b) in enumerate(meta):
        mx = ix + (i % 2) * (iw / 2)
        my = y + (i // 2) * 17
        text(p, a, mx, my, 10.5, 500, P["text2"])
        text(p, b, mx + 104, my, 10.5, 600, P["text"])
    y += 3 * 17 + 14
    # table
    rows = [
        ("Левый желудочек", None),
        ("КДР ЛЖ / КСР ЛЖ", "48 / 31 мм"),
        ("МЖП / ЗСЛЖ", "10 / 9 мм"),
        ("ОТС · ММЛЖ · ИММЛЖ", "0,38 · 162 г · 90 г/м²"),
        ("КДО / КСО (бипланово)", "108 / 44 мл"),
        ("ФВ ЛЖ (Симпсон бипланово)", "59 %"),
        ("Левое предсердие", None),
        ("ОЛП · ИОЛП", "52 мл · 29 мл/м²"),
        ("Диастолическая функция", None),
        ("E / A · E/A", "78 / 64 см/с · 1,2"),
        ("e′ септ. / лат. · E/e′ ср.", "8 / 11 см/с · 8,2"),
        ("Аортальный клапан · правые отделы", None),
        ("Vmax АК · Град. ср. АК", "1,4 м/с · 4 мм рт. ст."),
        ("Vmax ТР · ДПП · СДЛА", "2,4 м/с · 3 · 26 мм рт. ст."),
    ]
    for lab, val in rows:
        if val is None:
            p.fillRect(QRectF(ix, y, iw, 20), C("#f1f3f5"))
            text(p, lab, ix + 8, y, 10.5, 700, P["text"], w=iw, h=20, va="c")
            y += 21
        else:
            text(p, lab, ix + 8, y, 10.5, 500, P["text2"], w=260, h=19, va="c")
            text(p, val, ix + 280, y, 10.5, 600, P["text"], w=260, h=19, va="c", tnum=True)
            hline(p, ix, y + 19, iw, "#eef0f2")
            y += 20
    y += 12
    # key images
    iw2 = (iw - 12) / 2
    ih = 120
    rrect(p, ix, y, iw2, ih, 3, fill="#000000")
    p.save()
    p.setClipRect(QRectF(ix, y, iw2, ih))
    echo_view(p, ix, y, iw2, ih, th, pad=(4, 4, 4, 4), lv_label=None, depth=False, points=False)
    p.restore()
    rrect(p, ix + iw2 + 12, y, iw2, ih, 3, fill="#000000")
    q = pil_to_qimage(doppler_image("pw_mv", 480, 220, px_per_s=480 / 3.2))
    p.drawImage(QRectF(ix + iw2 + 12, y + 6, iw2, ih - 12), q)
    text(p, "Рис. 1. 4-кам., КДО (Симпсон)", ix, y + ih + 4, 9.5, 500, P["text2"])
    text(p, "Рис. 2. PW, трансмитральный поток", ix + iw2 + 12, y + ih + 4, 9.5, 500, P["text2"])
    y += ih + 26
    text(p, "Заключение", ix, y, 12, 700, P["text"])
    y += 20
    concl = [
        ("Полость ЛЖ не расширена, толщина стенок в норме. ", False),
        ("Глобальная систолическая функция ЛЖ сохранена (ФВ 59 %). ", True),
        ("Диастолическая функция ЛЖ не нарушена. Признаков лёгочной гипертензии нет (СДЛА 26 мм рт. ст.).", False),
    ]
    # simple flowing paragraph with one highlighted (just inserted) sentence
    line_y = y
    cur_x = ix
    for sent, hl in concl:
        for word in sent.split(" "):
            if not word:
                continue
            ww = tw(word + " ", 11, 500)
            if cur_x + ww > ix + iw:
                cur_x = ix
                line_y += 17
            if hl:
                p.fillRect(QRectF(cur_x - 1, line_y - 1, ww, 16), C(P["cur_bg"]))
            text(p, word + " ", cur_x, line_y, 11, 500, P["text"])
            cur_x += ww
    p.fillRect(QRectF(cur_x, line_y, 1.4, 15), C(P["cur"]))
    y = line_y + 34
    text(p, "Врач: ______________________      Подпись: __________", ix, y, 10.5, 500, P["text2"])
    p.restore()
    # right: phrases + export
    rx = W - RW
    p.fillRect(QRectF(rx, top, RW, bottom - top), C(th["bg1"]))
    vline(p, rx, top, bottom - top, th["line"])
    x = rx + 16
    y = top + 14
    text(p, "Фразы", x, y, 14.5, 600, th["text"])
    text(p, "клик — вставить в заключение", x + 60, y + 3, 11, 500, th["text3"])
    y += 30
    search_field(p, x, y, RW - 32, 30, "Найти фразу…", th, r=7)
    y += 42
    for grp, items in PHRASES:
        section_label(p, x, y, grp, th)
        y += 18
        for it in items:
            used = it in USED_PHRASES
            lines = 2 if tw(it, 11.5, 500) > RW - 32 - 36 else 1
            hh = 22 + 15 * lines - 8
            rrect(p, x, y, RW - 32, hh, 7, fill=C(th["accent"], 0.12) if used else th["bg2"], stroke=C(th["accent"], 0.45) if used else th["line"])
            icon(p, "l-check" if used else "l-plus", x + 9, y + 7, 13, th["accent_text"] if used else th["text3"], sw=2.2)
            text(p, it, x + 28, y + 5, 11.5, 500, th["text"] if used else th["text2"], w=RW - 32 - 36, wrap=True, lh=15)
            y += hh + 6
        y += 6
    # export block
    by = bottom - 160
    hline(p, rx, by, RW, th["line"])
    text(p, "Экспорт", x, by + 14, 12.5, 600, th["text"])
    bw = (RW - 32 - 8) / 2
    for i, (lab, ico) in enumerate((("PDF", "l-file-down"), ("DICOM SR", "l-file-output"), ("Печать", "l-printer"), ("В PACS", "l-send"))):
        bx = x + (i % 2) * (bw + 8)
        byy = by + 38 + (i // 2) * 38
        button(p, bx, byy, th, lab, ico, "outline", h=32, w=bw)
    button(p, x, bottom - 44, th, "Подписать и завершить", "l-badge-check", "primary", h=34, w=RW - 32, weight=600)
    status_bar(
        p,
        th,
        [("l-circle-check", "Сохранено · 10:58", th["ok"]), (None, "Отчёт: черновик v3", th["text2"])],
        [("l-triangle-alert", "Только для исследований", th["warn"]), (None, "SonoForge 0.4.0", th["text3"])],
    )
    return cv.save(OUT / "D2-workflow-report.png")


if __name__ == "__main__":
    print(render_d1())
    print(render_d2())
