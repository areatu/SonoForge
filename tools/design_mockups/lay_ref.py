"""Round 2 · «Справочник по ЭхоКГ и УЗИ»: own window (S1) and in-context card (S2).

Norms and topics are taken from resources/references/references_structured_ru.yaml
(female ranges, ASE/EACVI 2015); the figure is the repo's LV_measures.jpg.
"""

from __future__ import annotations

import functools

import screen_a as A
from common import C, QPainterPath, QPointF, QRectF, button, circle, hline, icon, pill, rrect, section_label, text, toggle, tw, vline
from kit import REPO, Canvas, Image, draw_image_fit, pil_to_qimage, shadow
from lay_common import OUT2, SB, TB, TH, W, H, S, clips_grid, segmented, status, summary_block, title, viewer_area, win_title, wrap_lines

REF_IMG = REPO / "src/echo_personal_tool/resources/references/images"

HEART = [
    ("r-LV01", "Левый желудочек", "28"),
    ("r-LA01", "Левое предсердие", "6"),
    ("r-RV01", "Правый желудочек", "26"),
    ("r-RA01", "Правое предсердие", "6"),
    ("r-MV01", "Митральный клапан", "10"),
    ("r-AV01", "Аортальный клапан", "14"),
    ("r-TV01", "Трикуспидальный клапан", "6"),
    ("r-PV01", "Лёгочный клапан", "7"),
    ("r-AV01", "Аорта", "6"),
    ("r-MV01", "Протезы клапанов", "6"),
    ("r-LV01", "Прочее", "3"),
]
OTHER = [
    ("l-activity", "Сонные артерии", "12"),
    ("l-activity", "Позвоночные артерии", "13"),
    ("l-circle-dot", "Щитовидная железа", "4"),
    ("l-circle-dot", "Почки", "4"),
    ("l-circle-dot", "Брюшная полость", "20"),
    ("l-activity", "Брюшная аорта", "8"),
    ("l-circle-dot", "Лимфоузлы", "10"),
]
GRADE_COLORS = ["#3ccb7f", "#e8c547", "#f2a93b", "#f06a6a"]
# name, unit, (норма, лёгкое, умеренное, тяжёлое) — women, ASE/EACVI 2015; patient value, grade index
LV_ROWS = [
    ("КДР ЛЖ", "мм", ("36–51", "52–56", "57–61", "≥ 62"), "48", 0),
    ("КСР ЛЖ", "мм", ("20–35", "36–40", "41–45", "≥ 46"), "31", 0),
    ("КДО ЛЖ / ППТ", "мл/м²", ("32–87", "88–99", "100–112", "≥ 113"), "60", 0),
    ("КСО ЛЖ / ППТ", "мл/м²", ("9–32", "33–37", "38–42", "≥ 43"), "25", 0),
    ("МЖП", "мм", ("6–10", "11–12", "13–14", "≥ 15"), "10", 0),
    ("ЗСЛЖ", "мм", ("6–10", "11–12", "13–14", "≥ 15"), "9", 0),
]
HOWTO = [
    "Парастернальная позиция по длинной оси, уровень кончиков створок МК.",
    "Линия измерения — перпендикулярно длинной оси ЛЖ.",
    "Конец диастолы — первый кадр после закрытия МК (или наибольший размер).",
    "Конец систолы — кадр перед открытием МК (или наименьший размер).",
]


@functools.lru_cache(maxsize=None)
def ref_qimage(name: str):
    return pil_to_qimage(Image.open(REF_IMG / name).convert("RGB"))


def nav_item(p, x, y, w, ico, lab, cnt, sel=False, h=32):
    th = TH
    if sel:
        rrect(p, x + 6, y, w - 12, h, 7, fill=C(th["accent"], 0.13))
        rrect(p, x + 6, y + 9, 3, h - 18, 1.5, fill=th["accent"])
    if ico.startswith("r-"):
        icon(p, ico, x + 18, y + (h - 18) / 2, 18, "#ffffff")
    else:
        icon(p, ico, x + 19, y + (h - 16) / 2, 16, th["text3"])
    text(p, lab, x + 46, y, 12.5, 600 if sel else 500, th["text"] if sel else th["text2"], w=w - 90, h=h, va="c", elide=True)
    text(p, cnt, x + w - 18 - tw(cnt, 11, 500, tnum=True), y, 11, 500, th["text3"], w=30, h=h, va="c", tnum=True)


def render_s1():
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    th = TH
    tbh = 40
    win_title(p, "Справочник по ЭхоКГ и УЗИ", h=tbh, search="Параметр, патология, тема…")
    top = tbh
    # ── left: topics
    nw = 264
    p.fillRect(QRectF(0, top, nw, H - top), C(th["bg1"]))
    vline(p, nw - 1, top, H - top, th["line"])
    y = top + 14
    section_label(p, 16, y, "Сердце", th)
    y += 20
    for i, (ico, lab, cnt) in enumerate(HEART):
        nav_item(p, 0, y, nw, ico, lab, cnt, sel=(i == 0))
        y += 33
    y += 12
    section_label(p, 16, y, "Сосуды и органы", th)
    y += 20
    for ico, lab, cnt in OTHER:
        nav_item(p, 0, y, nw, ico, lab, cnt, h=30)
        y += 31
    hline(p, 0, H - 56, nw - 1, th["line"])
    button(p, 12, H - 44, th, "Конструктор", "l-pen-tool", "ghost", h=32)
    button(p, 140, H - 44, th, "Источники", "l-book-open", "ghost", h=32)
    # ── centre: topic page
    cx0, cx1 = nw, 1100
    x = cx0 + 28
    cw = cx1 - cx0 - 56
    y = top + 18
    text(p, "Сердце  ›  Левый желудочек", x, y, 11.5, 500, th["text3"])
    y += 22
    text(p, "Левый желудочек", x, y, 22, 600, th["text"])
    for i, ico in enumerate(("l-printer", "l-star")):
        icon(p, ico, cx1 - 44 - i * 32, y + 6, 17, th["text2"])
    y += 46
    tabs = ["Размеры", "Геометрия и гипертрофия", "Фракция выброса", "Диастолическая функция", "Сегменты"]
    tx = x
    for i, t in enumerate(tabs):
        wv = tw(t, 12.5, 600 if i == 0 else 500)
        text(p, t, tx, y, 12.5, 600 if i == 0 else 500, th["text"] if i == 0 else th["text2"], w=wv + 2, h=34, va="c")
        if i == 0:
            rrect(p, tx, y + 32, wv, 2, 1, fill=th["accent"])
        tx += wv + 22
    hline(p, x, y + 34, cw, th["line"])
    y += 50
    segmented(p, x, y, ["Мужчины", "Женщины", "Оба"], 1, h=30)
    text(p, "выбрано по пациентке · 59 лет", x + 282, y, 11.5, 500, th["text3"], w=260, h=30, va="c")
    lab = "Значения пациентки"
    toggle(p, cx1 - 28 - 30, y + 6, True, th, w=30, h=18)
    text(p, lab, cx1 - 28 - 40 - tw(lab, 12, 500), y, 12, 500, th["text2"], w=200, h=30, va="c")
    y += 46
    cols = [("Параметр", 214), ("Ед.", 66), ("Норма", 98), ("Лёгкое", 92), ("Умеренное", 102), ("Тяжёлое", 90), ("Пациентка", 0)]
    xs = []
    xx = x
    for _, wv in cols:
        xs.append(xx)
        xx += wv
    rrect(p, x, y, cw, 34, 8, fill=th["bg2"])
    for i, (name, wv) in enumerate(cols):
        cx_ = xs[i] + 12
        if 2 <= i <= 5:
            circle(p, cx_ + 4, y + 17, 4, fill=GRADE_COLORS[i - 2])
            cx_ += 13
        text(p, name.upper(), cx_, y, 10, 600, th["text2"], spacing=0.5, w=140, h=34, va="c")
    y += 38
    rh = 46
    for r, (name, unit, grades, val, gi) in enumerate(LV_ROWS):
        if r % 2 == 1:
            rrect(p, x, y, cw, rh, 6, fill=C("#ffffff", 0.018))
        text(p, name, xs[0] + 12, y, 13, 600, th["text"], w=200, h=rh, va="c")
        text(p, unit, xs[1] + 12, y, 12, 500, th["text3"], w=60, h=rh, va="c")
        for k, g in enumerate(grades):
            gx = xs[2 + k]
            gw = cols[2 + k][1]
            if k == gi:
                rrect(p, gx + 4, y + 7, gw - 10, rh - 14, 7, fill=C(th["accent"], 0.12), stroke=C(th["accent"], 0.6))
            text(p, g, gx + 12, y, 12.5, 600 if k == gi else 500, th["text"] if k == gi else th["text2"], w=gw - 14, h=rh, va="c", tnum=True)
        vx = xs[6] + 12
        vw = text(p, val, vx, y, 14, 700, th["text"], w=60, h=rh, va="c", tnum=True)
        text(p, unit, vx + vw + 4, y + 1, 11, 500, th["text3"], w=60, h=rh, va="c")
        pill(p, vx + vw + 10 + tw(unit, 11, 500), y + 13, "норма", th["ok"], C(th["ok"], 0.14), h=20, size=10.5)
        y += rh
    y += 14
    icon(p, "l-book-open", x, y + 1, 14, th["text3"])
    text(p, "ASE/EACVI 2015 — количественная оценка камер сердца у взрослых", x + 22, y, 11.5, 500, th["text2"])
    s = "Открыть PDF"
    text(p, s, cx1 - 28 - tw(s, 11.5, 600), y, 11.5, 600, th["accent_text"])
    y += 22
    text(p, "Объёмы индексируются на ППТ пациентки (1,79 м²). Значения — для взрослых.", x + 22, y, 11.5, 500, th["text3"])
    y += 40
    rrect(p, x, y, cw, 112, 10, fill=th["bg1"], stroke=th["line"])
    icon(p, "l-info", x + 16, y + 16, 16, th["accent_text"])
    text(p, "Когда линейных размеров недостаточно", x + 42, y + 14, 13, 600, th["text"])
    text(
        p,
        "Линейные размеры быстро измерить, но при изменённой форме ЛЖ (аневризма, асимметричная гипертрофия) они менее надёжны — опирайтесь на объёмы по Симпсону бипланово.",
        x + 42,
        y + 38,
        12,
        500,
        th["text2"],
        w=cw - 60,
        wrap=True,
        lh=18,
    )
    button(p, x + 42, y + 76, th, "Протокол «Симпсон бипланово»", "l-list-checks", "outline", h=28, size=12)
    # ── right: figure + how to measure
    rx = cx1
    rw = W - rx
    p.fillRect(QRectF(rx, top, rw, H - top), C(th["bg1"]))
    vline(p, rx, top, H - top, th["line"])
    ix = rx + 20
    iw = rw - 40
    y = top + 18
    text(p, "Иллюстрация", ix, y, 13, 600, th["text"])
    s = "1 / 2"
    text(p, s, rx + rw - 64 - tw(s, 11.5, 500), y + 1, 11.5, 500, th["text3"])
    icon(p, "l-chevron-left", rx + rw - 56, y, 16, th["text3"])
    icon(p, "l-chevron-right", rx + rw - 36, y, 16, th["text2"])
    y += 28
    fh = 360
    rrect(p, ix, y, iw, fh, 10, fill="#ffffff")
    draw_image_fit(p, ref_qimage("LV_measures.jpg"), ix + 12, y + 10, iw - 24, fh - 20)
    y += fh + 8
    text(p, "М-режим, парастернальная позиция по длинной оси: КДР, КСР, МЖП, ЗСЛЖ", ix, y, 11, 500, th["text3"], w=iw, wrap=True, lh=15)
    y += 40
    text(p, "Как измерять", ix, y, 13, 600, th["text"])
    y += 26
    for i, step in enumerate(HOWTO):
        circle(p, ix + 9, y + 9, 9, fill=th["bg3"])
        text(p, str(i + 1), ix, y, 10.5, 700, th["text2"], w=18, h=18, align="c", va="c")
        text(p, step, ix + 28, y + 1, 12, 500, th["text2"], w=iw - 30, wrap=True, lh=17)
        y += 17 * wrap_lines(step, 12, 500, iw - 30) + 12
    y += 4
    text(p, "Внутренний край — внутренний край (граница кровь/ткань).", ix + 28, y - 6, 11, 500, th["text3"], w=iw - 30)
    y += 24
    section_label(p, ix, y, "Связанные", th)
    y += 20
    cx = ix
    for s2 in ("ИММЛЖ", "ОТС", "ФВ ЛЖ", "Объём ЛП"):
        cw2 = tw(s2, 11.5, 500) + 22
        rrect(p, cx, y, cw2, 26, 13, fill=th["bg2"], stroke=th["line2"])
        text(p, s2, cx, y, 11.5, 500, th["text2"], w=cw2, h=26, align="c", va="c")
        cx += cw2 + 6
    return cv.save(OUT2 / "S1-reference-window.png")


# ───────────────────────────── S2: reference card in context ─────────────────────────────

LV_MEAS = [
    ("КДР ЛЖ", "48", "мм", "ok"),
    ("КСР ЛЖ", "31", "мм", "ok"),
    ("МЖП", "10", "мм", "edge"),
    ("ЗСЛЖ", "9", "мм", "ok"),
    ("ОТС", "0,38", "", "ok"),
    ("ИММЛЖ", "90", "г/м²", "ok"),
    ("КДО · 4-кам.", "112", "мл", None),
    ("ФВ ЛЖ", "—", "после КСО", "todo"),
]


def measurements_panel(p, x, top, w, bottom, hover=0):
    th = TH
    p.fillRect(QRectF(x, top, w, bottom - top), C(th["bg1"]))
    vline(p, x, top, bottom - top, th["line"])
    tx = x + 14
    for i, t in enumerate(("Измерения", "Расчёты", "Изображение", "DICOM")):
        wv = tw(t, 12.5, 600 if i == 0 else 500)
        text(p, t, tx, top, 12.5, 600 if i == 0 else 500, th["text"] if i == 0 else th["text2"], w=wv + 2, h=40, va="c")
        if i == 0:
            rrect(p, tx, top + 38, wv, 2, 1, fill=th["accent"])
        tx += wv + 18
    hline(p, x, top + 40, w, th["line"])
    y = top + 52
    segmented(p, x + 12, y, ["Протоколы", "По анатомии"], 1, h=28, size=11.5, pad=12)
    lab = "Нормы"
    toggle(p, x + w - 14 - 28, y + 6, True, th, w=28, h=16)
    text(p, lab, x + w - 14 - 36 - tw(lab, 11.5, 500), y, 11.5, 500, th["text2"], w=80, h=28, va="c")
    y += 42
    icon(p, "r-LV01", x + 16, y + 4, 18, "#ffffff")
    text(p, "Левый желудочек", x + 42, y, 13, 600, th["text"], w=200, h=26, va="c")
    text(p, "6/14", x + w - 40 - tw("6/14", 11, 500, tnum=True), y, 11, 500, th["text3"], w=40, h=26, va="c", tnum=True)
    icon(p, "l-chevron-down", x + w - 30, y + 6, 14, th["text3"])
    y += 32
    rows_y = []
    for i, (lab, val, unit, st) in enumerate(LV_MEAS):
        rh = 32
        rows_y.append(y)
        if i == hover:
            rrect(p, x + 8, y, w - 16, rh, 7, fill=C(th["accent"], 0.12), stroke=C(th["accent"], 0.5))
        text(p, lab, x + 42, y, 12.5, 600 if i == hover else 500, th["text"] if st != "todo" else th["text2"], w=150, h=rh, va="c")
        if st == "todo":
            text(p, unit, x + w - 20 - tw(unit, 11.5, 500), y, 11.5, 500, th["text3"], w=100, h=rh, va="c")
        else:
            ux = x + w - 20 - (tw(unit, 11, 500) if unit else 0)
            if unit:
                text(p, unit, ux, y + 1, 11, 500, th["text3"], w=60, h=rh, va="c")
            vw = tw(val, 13, 600, tnum=True)
            text(p, val, ux - 4 - vw, y, 13, 600, th["text"], w=vw + 2, h=rh, va="c", tnum=True)
            if st:
                col = th["ok"] if st == "ok" else "#e8c547"
                circle(p, ux - 4 - vw - 12, y + rh / 2, 3.5, fill=col)
        if i == hover:
            icon(p, "l-info", x + 18, y + 8, 15, th["accent_text"])
        y += rh + 2
    y += 8
    for ico, name, cnt in (
        ("LA01", "Левое предсердие", "0/5"),
        ("MV01", "Митральный клапан", "3/9"),
        ("AV01", "Аортальный клапан · ВТЛЖ", "0/9"),
        ("TV01", "Трикуспидальный клапан", "2/7"),
        ("RV01", "Правый желудочек", "0/6"),
    ):
        if y > bottom - 160:
            break
        icon(p, "r-" + ico, x + 16, y + 6, 16, "#ffffff")
        text(p, name, x + 42, y, 12, 500, th["text2"], w=w - 100, h=28, va="c")
        text(p, cnt, x + w - 44 - tw(cnt, 11, 500, tnum=True), y, 11, 500, th["text3"], w=40, h=28, va="c", tnum=True)
        icon(p, "l-chevron-right", x + w - 32, y + 7, 14, th["text3"])
        y += 28
    summary_block(p, x, bottom - 128, w, bottom)
    return rows_y


def grade_bar(p, x, y, w, lo, hi, cuts, value, labels):
    """Segmented norm bar: grey below the norm, then норма / лёгкое / умеренное / тяжёлое."""
    th = TH

    def fx(v):
        return x + (v - lo) / (hi - lo) * w

    segs = [(lo, cuts[0], "#3a4048")] + [(cuts[i], cuts[i + 1], GRADE_COLORS[i]) for i in range(len(cuts) - 1)] + [(cuts[-1], hi, GRADE_COLORS[3])]
    for i, (a, b, col) in enumerate(segs):
        x0, x1 = fx(a), fx(b)
        rrect(p, x0 + (1 if i else 0), y, x1 - x0 - 2, 10, 3, fill=C(col, 0.85 if i else 1.0))
    for c in cuts:
        text(p, labels.get(c, ""), fx(c) - 20, y + 14, 10, 500, th["text3"], w=40, h=14, align="c", va="c", tnum=True)
    mx = fx(value)
    path = QPainterPath()
    path.moveTo(QPointF(mx, y - 2))
    path.lineTo(QPointF(mx - 6, y - 10))
    path.lineTo(QPointF(mx + 6, y - 10))
    path.closeSubpath()
    p.setPen(C("#000000", 0.0))
    p.setBrush(C("#ffffff"))
    p.drawPath(path)
    rrect(p, mx - 1.2, y - 2, 2.4, 14, 1, fill="#ffffff")


def ref_popover(cv, p, panel_x, ay, figure=True):
    """Norm card for «КДР ЛЖ», anchored to the left edge of the measurements panel at height ``ay``.

    ``figure=False`` is the approved variant: text only, the figure stays in the reference window.
    """
    th = TH
    pw, ph = 392, (452 if figure else 404)
    px = panel_x - 12 - pw
    py = ay - 60
    shadow(cv, px, py, pw, ph, 12, blur=26, dy=10, alpha=0.65)
    rrect(p, px, py, pw, ph, 12, fill=th["bg2"], stroke=th["line2"])
    tri = QPainterPath()
    tri.moveTo(QPointF(px + pw - 0.5, ay - 9))
    tri.lineTo(QPointF(px + pw + 9, ay))
    tri.lineTo(QPointF(px + pw - 0.5, ay + 9))
    tri.closeSubpath()
    p.setPen(C(th["line2"]))
    p.setBrush(C(th["bg2"]))
    p.drawPath(tri)
    ix, iw = px + 18, pw - 36
    y = py + 16
    text(p, "КДР ЛЖ", ix, y, 15, 700, th["text"])
    text(p, "конечно-диастолический размер", ix + tw("КДР ЛЖ", 15, 700) + 8, y + 3, 11.5, 500, th["text3"])
    y += 30
    vw_ = text(p, "48", ix, y, 30, 600, th["text"], tnum=True)
    text(p, "мм", ix + vw_ + 6, y + 14, 13, 500, th["text2"])
    pill(p, ix + vw_ + 34, y + 10, "норма", th["ok"], C(th["ok"], 0.15), h=22, size=11.5, icon_name="l-check")
    text(p, "женщины · 36–51 мм", ix + iw - tw("женщины · 36–51 мм", 11.5, 500), y + 13, 11.5, 500, th["text2"])
    y += 58
    grade_bar(p, ix, y, iw, 30, 66, [36, 51.5, 56.5, 61.5], 48, {36: "36", 51.5: "51", 56.5: "56", 61.5: "61"})
    y += 32
    lx = ix
    for name, col in zip(("норма", "лёгкое", "умеренное", "тяжёлое"), GRADE_COLORS):
        circle(p, lx + 4, y + 7, 4, fill=col)
        lx += 12 + text(p, name, lx + 12, y, 11, 500, th["text2"]) + 14
    y += 28
    hline(p, px + 1, y, pw - 2, th["line2"])
    y += 14
    how = ("ПЛАКС, кончики створок МК", "перпендикулярно оси ЛЖ", "конец диастолы", "внутренний край — внутренний край")
    if figure:
        fw, fh = 176, 150
        rrect(p, ix, y, fw, fh, 8, fill="#ffffff")
        draw_image_fit(p, ref_qimage("LV_measures.jpg"), ix + 6, y + 6, fw - 12, fh - 12)
        tx = ix + fw + 14
        text(p, "Как измерять", tx, y, 12.5, 600, th["text"])
        yy = y + 22
        for s in how:
            circle(p, tx + 3, yy + 8, 2.2, fill=th["text3"])
            text(p, s, tx + 12, yy, 11.5, 500, th["text2"], w=iw - fw - 26, wrap=True, lh=15)
            yy += 15 * wrap_lines(s, 11.5, 500, iw - fw - 26) + 5
        y += fh + 14
    else:
        # no attached images in the overlay: their captions are too small at this size (user's round-2 answer)
        text(p, "Как измерять", ix, y, 12.5, 600, th["text"])
        yy = y + 24
        for s in how:
            circle(p, ix + 3, yy + 8, 2.2, fill=th["text3"])
            text(p, s, ix + 12, yy, 12, 500, th["text2"], w=iw - 12, h=17, va="c")
            yy += 21
        text(p, "Рисунок и подробная методика — в справочнике", ix, yy + 4, 11, 500, th["text3"])
        y = yy + 30
    text(p, "ASE/EACVI 2015 · количественная оценка камер", ix, y, 11, 500, th["text3"])
    y += 26
    button(p, ix, y, th, "Открыть в справочнике", "l-book-open", "outline", h=30, size=12)
    s = "Esc — закрыть"
    text(p, s, px + pw - 18 - tw(s, 11, 500), y, 11, 500, th["text3"], w=120, h=30, va="c")


def render_s2():
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    th = TH
    title(p)
    A.patient_bar(p, th)
    top, bottom = TB + A.PB, H - SB
    lw, rw = 216, 352
    clips_grid(p, 0, top, lw, bottom)
    vx, vw = lw, W - lw - rw
    A.viewer_toolbar(p, th, vx, top, vw, 42)
    cine_h = 66
    viewer_area(p, vx, top + 42, vw, bottom - cine_h - top - 42, banner=False, pad=(26, 16, 70, 90))
    A.cine_bar(p, th, vx, bottom - cine_h, vw, cine_h)
    rows_y = measurements_panel(p, W - rw, top, rw, bottom, hover=0)
    ref_popover(cv, p, W - rw, rows_y[0] + 16)
    status(p)
    return cv.save(OUT2 / "S2-reference-in-context.png")


if __name__ == "__main__":
    print(render_s1())
    print(render_s2())
