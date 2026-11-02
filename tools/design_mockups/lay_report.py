"""Round 2 · report: three layouts between D1 (live report while measuring) and D2 (report editor)."""

from __future__ import annotations

import screen_a as A
import screen_d as D
from common import (
    PT,
    REPORT_LV,
    REPORT_RIGHT,
    C,
    QPen,
    QRectF,
    Qt,
    button,
    echo_view,
    hline,
    icon,
    pill,
    rrect,
    search_field,
    section_label,
    status_icon,
    text,
    thumb,
    tw,
    vline,
)
from kit import Canvas, doppler_image, logo, pil_to_qimage, shadow, vgrad
from lay_common import BY_ID, OUT2, SB, TB, TH, W, H, S, clips_grid, patient_line, status, title, viewer_area, viewer_corner, wrap_lines

P = D.PAPER
MODES3 = ("Изображения", "Вместе", "Отчёт")


# ───────────────────────────── shared report pieces ─────────────────────────────


def ph_chip(p, x, y, s, h=20, size=10.5, dark=False):
    """Dashed amber placeholder: value not measured yet (click → jump to the clip)."""
    cw = tw(s, size, 600) + 16
    rrect(p, x, y, cw, h, 5, fill=C(TH["warn"], 0.13) if dark else P["ph_bg"])
    pen = QPen(C(TH["warn"] if dark else P["ph_border"]), 1.0)
    pen.setDashPattern([3, 2])
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(x + 0.5, y + 0.5, cw - 1, h - 1), 5, 5)
    text(p, s, x, y, size, 600, TH["warn"] if dark else P["ph"], w=cw, h=h, align="c", va="c")
    return cw


def tab_row(p, x, y, w, tabs, active, h=40):
    tx = x + 14
    for i, t in enumerate(tabs):
        wv = tw(t, 12.5, 600 if i == active else 500)
        text(p, t, tx, y, 12.5, 600 if i == active else 500, TH["text"] if i == active else TH["text2"], w=wv + 2, h=h, va="c")
        if i == active:
            rrect(p, tx, y + h - 2, wv, 2, 1, fill=TH["accent"])
        tx += wv + 18
    hline(p, x, y + h, w, TH["line"])


def live_paper(p, cv, px, py, pw, ph):
    """D1-style paper: fills itself from measurements; amber chips = still to measure."""
    shadow(cv, px, py, pw, ph, 6, blur=16, dy=5, alpha=0.5)
    rrect(p, px, py, pw, ph, 6, fill=P["bg"])
    p.save()
    p.setClipRect(QRectF(px, py, pw, ph))
    ix, iw = px + 18, pw - 36
    y = py + 16
    text(p, "Протокол трансторакальной ЭхоКГ", ix, y, 14, 700, P["text"])
    y += 22
    text(p, f"{PT['name']} · {PT['sex']} · {PT['age']} · ППТ {PT['bsa']}", ix, y, 11, 600, P["text"])
    y += 24
    colw = iw / 2
    y = D.paper_section(p, ix, y, iw, "Левый желудочек")
    for i, (lab, val, unit) in enumerate(REPORT_LV[:6]):
        D.paper_value(p, ix + (i % 2) * colw, y + (i // 2) * 21, lab, val, unit)
    y += 3 * 21 + 2
    D.paper_value(p, ix, y, "КДО · 4-кам.", "112", "мл")
    D.paper_value(p, ix + colw, y, "КСО · 4-кам.", "", "", state="current")
    y += 22
    D.paper_value(p, ix, y, "ФВ ЛЖ (Симпсон)", "ждёт 3 изм.", "", state="ph")
    y += 28
    y = D.paper_section(p, ix, y, iw, "Левое предсердие")
    D.paper_value(p, ix, y, "ОЛП · 4-кам.", "измерить", "", state="ph")
    D.paper_value(p, ix + colw, y, "ИОЛП", "—", "", state="ph")
    y += 28
    y = D.paper_section(p, ix, y, iw, "Диастолическая функция ЛЖ")
    rows = [("E", "78", "см/с", "done"), ("A", "64", "см/с", "done"), ("E/A", "1,2", "", "done"), ("e′ септ.", "8", "см/с", "done"), ("e′ лат.", "измерить", "", "ph"), ("E/e′ ср.", "—", "", "ph")]
    for i, (lab, val, unit, st) in enumerate(rows):
        D.paper_value(p, ix + (i % 2) * colw, y + (i // 2) * 21, lab, val, unit, state=st)
    y += 3 * 21 + 7
    y = D.paper_section(p, ix, y, iw, "Аортальный клапан")
    D.paper_value(p, ix, y, "Vmax АК", "измерить", "", state="ph")
    D.paper_value(p, ix + colw, y, "Град. ср. АК", "—", "", state="ph")
    y += 28
    y = D.paper_section(p, ix, y, iw, "Правые отделы · ТР")
    for i, (lab, val, unit) in enumerate(REPORT_RIGHT):
        D.paper_value(p, ix + (i % 2) * colw, y + (i // 2) * 21, lab, val, unit)
    p.restore()
    p.fillRect(QRectF(px, py + ph - 26, pw, 26), vgrad(py + ph - 26, py + ph, [(0, C(P["bg"], 0.0)), (1, C(P["bg"], 1.0))]))


A4_ROWS = [
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
    ("Аортальный клапан", None),
    ("Vmax АК · Град. ср. АК", "!измерить · клип CW АК"),
    ("Правые отделы", None),
    ("Vmax ТР · ДПП · СДЛА", "2,4 м/с · 3 · 26 мм рт. ст."),
]


def a4_page(p, cv, px, py, scale=1.0, clip=None, hl_row=None):
    """White A4 page (640 pt wide in page space) at (px, py), optional scale. Returns {row label: screen y}."""
    pw = 640
    marks = {}
    p.save()
    if clip is not None:
        p.setClipRect(clip)
    p.translate(px, py)
    p.scale(scale, scale)
    shadow(cv, 0, 0, pw, 1100, 4, blur=22, dy=8, alpha=0.6)
    rrect(p, 0, 0, pw, 1100, 3, fill="#ffffff")
    ix, iw = 44, pw - 88
    y = 34
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
    meta = [
        ("Пациент", PT["name"]),
        ("Пол, возраст", "Ж, 59 лет (12.03.1967)"),
        ("ID", PT["pid"]),
        ("Дата", f"{PT['date']} {PT['time']}"),
        ("Рост / вес / ППТ", f"{PT['height']} / {PT['weight']} / {PT['bsa']}"),
        ("ЧСС, ритм", "68 уд/мин, синусовый"),
    ]
    for i, (a, b) in enumerate(meta):
        mx = ix + (i % 2) * (iw / 2)
        my = y + (i // 2) * 17
        text(p, a, mx, my, 10.5, 500, P["text2"])
        text(p, b, mx + 104, my, 10.5, 600, P["text"])
    y += 3 * 17 + 14
    for lab, val in A4_ROWS:
        if val is None:
            p.fillRect(QRectF(ix, y, iw, 20), C("#f1f3f5"))
            text(p, lab, ix + 8, y, 10.5, 700, P["text"], w=iw, h=20, va="c")
            y += 21
            continue
        if lab == hl_row:
            p.fillRect(QRectF(ix, y, iw, 19), C(P["cur_bg"]))
            rrect(p, ix, y, 2.5, 19, 0, fill=P["cur"])
        text(p, lab, ix + 8, y, 10.5, 500, P["text2"], w=260, h=19, va="c")
        if val.startswith("!"):
            ph_chip(p, ix + 280, y + 1, val[1:], h=17, size=10)
        else:
            text(p, val, ix + 280, y, 10.5, 600, P["text"], w=260, h=19, va="c", tnum=True)
        hline(p, ix, y + 19, iw, "#eef0f2")
        marks[lab] = py + (y + 9.5) * scale
        y += 20
    y += 12
    iw2, ih = (iw - 12) / 2, 120
    rrect(p, ix, y, iw2, ih, 3, fill="#000000")
    p.save()
    p.setClipRect(QRectF(ix, y, iw2, ih))
    echo_view(p, ix, y, iw2, ih, TH, pad=(4, 4, 4, 4), lv_label=None, depth=False, points=False)
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
    line_y, cur_x = y, ix
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
    line_y += 20
    ph_chip(p, ix, line_y, "Аортальный клапан — после измерения Vmax АК", h=18, size=10)
    y = line_y + 40
    text(p, "Врач: ______________________      Подпись: __________", ix, y, 10.5, 500, P["text2"])
    p.restore()
    return marks


PHRASES = D.PHRASES
USED = D.USED_PHRASES


def phrases_panel(p, x, top, w, bottom, export_h=0, title_s="Фразы", hint="клик — вставить"):
    th = TH
    p.fillRect(QRectF(x, top, w, bottom - top), C(th["bg1"]))
    vline(p, x, top, bottom - top, th["line"])
    ix = x + 14
    y = top + 14
    text(p, title_s, ix, y, 14, 600, th["text"])
    text(p, hint, ix + tw(title_s, 14, 600) + 8, y + 3, 11, 500, th["text3"])
    y += 30
    search_field(p, ix, y, w - 28, 30, "Найти фразу…", th, r=7)
    y += 42
    lim = bottom - export_h - 10
    for grp, items in PHRASES:
        if y > lim - 40:
            break
        section_label(p, ix, y, grp, th)
        y += 18
        for it in items:
            used = it in USED
            tw_avail = w - 28 - 36
            hh = 14 + 15 * wrap_lines(it, 11.5, 500, tw_avail)
            if y + hh > lim:
                break
            rrect(p, ix, y, w - 28, hh, 7, fill=C(th["accent"], 0.12) if used else th["bg2"], stroke=C(th["accent"], 0.45) if used else th["line"])
            icon(p, "l-check" if used else "l-plus", ix + 9, y + 7, 13, th["accent_text"] if used else th["text3"], sw=2.2)
            text(p, it, ix + 28, y + 6, 11.5, 500, th["text"] if used else th["text2"], w=tw_avail, wrap=True, lh=15)
            y += hh + 6
        y += 6
    return y


def export_block(p, x, w, bottom):
    th = TH
    by = bottom - 160
    p.fillRect(QRectF(x + 1, by, w - 1, bottom - by), C(th["bg1"]))
    hline(p, x, by, w, th["line"])
    ix = x + 14
    text(p, "Экспорт", ix, by + 14, 12.5, 600, th["text"])
    bw = (w - 28 - 8) / 2
    for i, (lab, ico) in enumerate((("PDF", "l-file-down"), ("DICOM SR", "l-file-output"), ("Печать", "l-printer"), ("В PACS", "l-send"))):
        button(p, ix + (i % 2) * (bw + 8), by + 38 + (i // 2) * 38, th, lab, ico, "outline", h=32, w=bw)
    button(p, ix, bottom - 44, th, "Подписать и завершить", "l-badge-check", "primary", h=34, w=w - 28, weight=600)


# ───────────────────────────── R1: report as a tab of the right panel ─────────────────────────────


def render_r1():
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    th = TH
    title(p)
    A.patient_bar(p, th)
    top, bottom = TB + A.PB, H - SB
    lw, rw = 216, 452
    clips_grid(p, 0, top, lw, bottom)
    vx, vw = lw, W - lw - rw
    A.viewer_toolbar(p, th, vx, top, vw, 42)
    cine_h = 66
    viewer_area(p, vx, top + 42, vw, bottom - cine_h - top - 42, banner=True, banner_w=500, banner_msg="КСО · 4-кам. — кадр конца систолы, обведите ЛЖ", banner_dx=12, pad=(96, 16, 50, 80))
    A.cine_bar(p, th, vx, bottom - cine_h, vw, cine_h)
    # right panel: «Отчёт» tab
    x = W - rw
    p.fillRect(QRectF(x, top, rw, bottom - top), C(th["bg1"]))
    vline(p, x, top, bottom - top, th["line"])
    tab_row(p, x, top, rw, ("Измерения", "Отчёт", "Расчёты", "DICOM"), 1)
    y = top + 50
    pill(p, x + 14, y, "черновик", th["warn"], C(th["warn"], 0.14), h=20, size=10.5)
    text(p, "заполняется по мере измерений", x + 92, y, 11, 500, th["text3"], w=220, h=20, va="c")
    for i, (ico, tip) in enumerate((("l-maximize-2", "Во весь экран"), ("l-columns-2", "Рядом"), ("l-printer", "Печать"))):
        icon(p, ico, x + rw - 30 - i * 30, y + 2, 16, th["text2"])
    concl_h = 214
    live_paper(p, cv, x + 14, y + 32, rw - 28, bottom - concl_h - (y + 32) - 10)
    # conclusion composer
    cy = bottom - concl_h
    hline(p, x, cy, rw, th["line"])
    ix = x + 14
    text(p, "Заключение", ix, cy + 12, 13, 600, th["text"])
    s = "фразы подбираются по значениям"
    text(p, s, x + rw - 14 - tw(s, 11), cy + 14, 11, 500, th["text3"])
    rrect(p, ix, cy + 38, rw - 28, 58, 8, fill=th["bg2"], stroke=th["line"])
    text(p, "Полость ЛЖ не расширена, толщина стенок в норме. Диастолическая функция ЛЖ не нарушена.", ix + 10, cy + 45, 11.5, 500, th["text"], w=rw - 48, wrap=True, lh=16)
    rrect(p, ix + 10 + tw("Диастолическая функция ЛЖ не нарушена.", 11.5, 500) + 2, cy + 63, 1.4, 14, 0, fill=th["accent"])
    chips = [("Признаков лёгочной гипертензии нет (СДЛА 26)", True), ("ФВ — после Симпсона", False), ("АК — после Vmax", False)]
    cx, yy = ix, cy + 106
    for s2, ok in chips:
        cw = tw(s2, 11, 500) + 30
        if cx + cw > x + rw - 14:
            cx = ix
            yy += 30
        if ok:
            rrect(p, cx, yy, cw, 24, 12, fill=th["bg2"], stroke=th["line2"])
            icon(p, "l-plus", cx + 9, yy + 6, 12, th["accent_text"], sw=2.4)
            text(p, s2, cx + 24, yy, 11, 500, th["text2"], w=cw, h=24, va="c")
        else:
            ph_chip(p, cx, yy, s2, h=24, size=10.5, dark=True)
        cx += cw + 6
    bw = (rw - 28 - 8) / 2
    button(p, ix, bottom - 44, th, "Предпросмотр A4", "l-file-text", "outline", h=32, w=bw)
    button(p, ix + bw + 8, bottom - 44, th, "Открыть отчёт", "l-maximize-2", "filled", h=32, w=bw)
    status(p)
    return cv.save(OUT2 / "R1-report-side-panel.png")


# ───────────────────────────── R2: image | report | phrases ─────────────────────────────


def mini_toolbar(p, x, y, w, h=42):
    th = TH
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y + h - 1, w, th["line"])
    bx = x + 10
    rrect(p, bx, y + 7, 150, 28, 7, fill=th["bg2"], stroke=th["line"])
    text(p, "4-кам. · 2D", bx + 10, y + 7, 12, 600, th["text"], w=110, h=28, va="c")
    icon(p, "l-chevron-down", bx + 130, y + 15, 12, th["text3"])
    bx += 162
    for ico, act in (
        ("l-mouse-pointer-2", True),
        ("l-move", False),
        ("l-zoom-in", False),
        (None, 0),
        ("l-ruler", False),
        ("l-square-dashed", False),
        ("l-spline", False),
        ("l-audio-waveform", False),
        ("l-crosshair", False),
    ):
        if ico is None:
            vline(p, bx + 4, y + 13, 16, th["line2"])
            bx += 10
            continue
        if act:
            rrect(p, bx, y + 6, 32, 30, 6, fill=C(th["accent"], 0.16), stroke=C(th["accent"], 0.5))
        icon(p, ico, bx + 8, y + 13, 16, th["accent_text"] if act else th["text2"])
        bx += 34
    s = "Для Vmax АК нет клипа CW"
    icon(p, "l-triangle-alert", x + w - 14 - tw(s, 11.5, 600) - 19, y + h / 2 - 7, 14, th["warn"])
    text(p, s, x + w - 14 - tw(s, 11.5, 600), y, 11.5, 600, th["warn"], w=260, h=h, va="c")


def key_images(p, x, y, w, h):
    th = TH
    p.fillRect(QRectF(x, y, w, h), C(th["bg1"]))
    hline(p, x, y, w, th["line"])
    text(p, "В отчёт", x + 14, y + 10, 12, 600, th["text"])
    text(p, "перетащите кадр", x + 14, y + 28, 10.5, 500, th["text3"])
    tx = x + 124
    th_h = h - 22
    th_w = th_h * 1.36
    for i, cid in enumerate(("c1", "c7")):
        thumb(p, tx, y + 11, th_w, th_h, BY_ID[cid], th, r=6, measured=False)
        rrect(p, tx + th_w - 26, y + 15, 20, 16, 4, fill=C("#000000", 0.6))
        text(p, f"{i + 1}", tx + th_w - 26, y + 15, 9.5, 700, th["text"], w=20, h=16, align="c", va="c")
        tx += th_w + 8
    pen = QPen(C(th["text3"]), 1.2)
    pen.setDashPattern([4, 3])
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(tx, y + 11, th_w, th_h), 6, 6)
    icon(p, "l-plus", tx + th_w / 2 - 9, y + 11 + th_h / 2 - 16, 18, th["text3"])
    text(p, "текущий кадр", tx, y + 11 + th_h / 2 + 4, 10, 500, th["text3"], w=th_w, h=14, align="c", va="c")


def render_r2():
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    th = TH
    title(p)
    pl = 42
    patient_line(p, TB, pl, mode=1, mode_items=MODES3)
    top, bottom = TB + pl, H - SB
    lw, rw = 690, 268
    # left: viewer
    mini_toolbar(p, 0, top, lw)
    kh, cine_h = 96, 62
    img_top = top + 42
    img_h = bottom - kh - cine_h - img_top
    viewer_area(p, 0, img_top, lw, img_h, banner=False, chips=False, pad=(20, 10, 20, 60), lv_label="КДО · 4-кам.  112 мл")
    viewer_corner(p, lw - 12, img_top + img_h - 10, items=("l-maximize-2",))
    A.cine_bar(p, th, 0, bottom - kh - cine_h, lw, cine_h)
    key_images(p, 0, bottom - kh, lw, kh)
    # centre: page
    cx0, cx1 = lw, W - rw
    p.fillRect(QRectF(cx0, top, cx1 - cx0, bottom - top), C("#0e1013"))
    vline(p, cx0, top, bottom - top, th["line"])
    text(p, "Отчёт", cx0 + 16, top + 10, 13, 600, th["text"])
    pill(p, cx0 + 16 + tw("Отчёт", 13, 600) + 8, top + 11, "черновик v3", th["warn"], C(th["warn"], 0.14), h=18, size=10)
    s = "19 из 21 значения · 2 ждут измерения"
    text(p, s, cx0 + 16, top + 30, 11, 500, th["text3"])
    zx = cx1 - 16 - 132
    rrect(p, zx, top + 12, 132, 28, 7, fill=th["bg2"], stroke=th["line"])
    icon(p, "l-minus", zx + 10, top + 19, 14, th["text2"])
    text(p, "92 %", zx + 30, top + 12, 11.5, 600, th["text2"], w=72, h=28, align="c", va="c", tnum=True)
    icon(p, "l-plus", zx + 108, top + 19, 14, th["text2"])
    scale = (cx1 - cx0 - 44) / 640
    page_x = cx0 + 22
    marks = a4_page(p, cv, page_x, top + 54, scale=scale, clip=QRectF(cx0, top + 50, cx1 - cx0, bottom - top - 50), hl_row="Vmax АК · Град. ср. АК")
    # tooltip on the pending value
    my = marks.get("Vmax АК · Град. ср. АК")
    if my:
        tx = page_x + (44 + 280) * scale + 4
        ty = my + 16
        tw_ = 300
        shadow(cv, tx, ty, tw_, 62, 8, blur=14, dy=4, alpha=0.5)
        rrect(p, tx, ty, tw_, 62, 8, fill="#1f2328")
        text(p, "Нет клипа CW АК в исследовании", tx + 12, ty + 9, 11.5, 600, "#ffffff")
        text(p, "Клик — найти подходящий клип или отметить «не оценивалось»", tx + 12, ty + 27, 10.5, 500, "#c9d1d9", w=tw_ - 24, wrap=True, lh=14)
    # right: phrases
    phrases_panel(p, cx1, top, rw, bottom, export_h=56)
    hline(p, cx1, bottom - 56, rw, th["line"])
    button(p, cx1 + 14, bottom - 44, th, "Экспорт и подпись", "l-badge-check", "primary", h=32, w=rw - 28, weight=600)
    status(p, saved="10:58", left_extra=[(None, "Отчёт: черновик v3", th["text2"])])
    return cv.save(OUT2 / "R2-report-split.png")


# ───────────────────────────── R3: full report mode (D2 in variant-A chrome) ─────────────────────────────

SECTIONS = [
    ("Пациент и исследование", "done", ""),
    ("Левый желудочек", "done", "9/9"),
    ("Левое предсердие", "done", "2/2"),
    ("Диастолическая функция", "done", "6/6"),
    ("Аортальный клапан", "todo", "0/2"),
    ("Правые отделы", "done", "4/4"),
    ("Заключение", "current", ""),
    ("Ключевые изображения", "done", "2"),
]


def render_r3(out=None, modes=MODES3, sel=None):
    """Report as a separate mode. Approved variant: two states «Изображения | Отчёт» (see lay_final)."""
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    th = TH
    title(p)
    pl = 42
    patient_line(p, TB, pl, mode=len(modes) - 1 if sel is None else sel, mode_items=modes)
    top, bottom = TB + pl, H - SB
    lw, rw = 284, 336
    p.fillRect(QRectF(0, top, lw, bottom - top), C(th["bg1"]))
    vline(p, lw - 1, top, bottom - top, th["line"])
    x, y = 16, top + 16
    text(p, "Разделы", x, y, 14, 600, th["text"])
    y += 32
    for name, st, cnt in SECTIONS:
        if st == "current":
            rrect(p, 8, y, lw - 16, 34, 8, fill=C(th["accent"], 0.14), stroke=C(th["accent"], 0.45))
        status_icon(p, x + 2, y + 10, st, th, size=14)
        text(p, name, x + 26, y, 12.5, 600 if st == "current" else 500, th["text"] if st != "todo" else th["warn"], w=180, h=34, va="c")
        if cnt:
            text(p, cnt, lw - 20 - tw(cnt, 11, 600, tnum=True), y, 11, 600, th["text3"] if st != "todo" else th["warn"], w=40, h=34, va="c", tnum=True)
        y += 36
    y += 12
    hline(p, 14, y, lw - 28, th["line"])
    y += 16
    text(p, "Не заполнено", x, y, 12.5, 600, th["text"])
    pill(p, x + tw("Не заполнено", 12.5, 600) + 8, y - 1, "2", th["warn"], C(th["warn"], 0.14), h=18, size=10)
    y += 26
    rrect(p, 12, y, lw - 24, 118, 8, fill=C(th["warn"], 0.07), stroke=C(th["warn"], 0.35))
    for i, lab in enumerate(("Vmax АК", "Град. ср. АК")):
        yy = y + 12 + i * 26
        status_icon(p, 24, yy + 2, "todo", th, size=12)
        text(p, lab, 44, yy, 12, 500, th["text"])
        s = "измерить"
        text(p, s, lw - 26 - tw(s, 11.5, 600), yy, 11.5, 600, th["accent_text"])
    text(p, "нет клипа CW АК — можно отметить «не оценивалось»", 24, y + 66, 10.5, 500, th["text3"], w=lw - 48, wrap=True, lh=14)
    y += 132
    rrect(p, 12, y, lw - 24, 70, 8, fill=th["bg2"], stroke=th["line"])
    text(p, "Рекомендуемые: 2", 24, y + 10, 12, 600, th["text"])
    text(p, "TAPSE · S′ ПЖ (TDI)", 24, y + 30, 11.5, 500, th["text2"])
    text(p, "показать в протоколе", 24, y + 48, 11, 600, th["accent_text"])
    # centre page
    cx0, cx1 = lw, W - rw
    p.fillRect(QRectF(cx0, top, cx1 - cx0, bottom - top), C("#0e1013"))
    text(p, "Предпросмотр · A4", cx0 + 18, top + 12, 12, 600, th["text2"])
    zx = cx1 - 150
    rrect(p, zx, top + 8, 132, 28, 7, fill=th["bg2"], stroke=th["line"])
    icon(p, "l-minus", zx + 10, top + 15, 14, th["text2"])
    text(p, "100 %", zx + 30, top + 8, 11.5, 600, th["text2"], w=72, h=28, align="c", va="c", tnum=True)
    icon(p, "l-plus", zx + 108, top + 15, 14, th["text2"])
    page_x = (cx0 + cx1) / 2 - 320
    marks = a4_page(p, cv, page_x, top + 48, clip=QRectF(cx0, top + 44, cx1 - cx0, bottom - top - 44), hl_row="ФВ ЛЖ (Симпсон бипланово)")
    my = marks.get("ФВ ЛЖ (Симпсон бипланово)")
    if my:
        # hover card: where the value came from
        hx, hy = cx1 - 12 - 300, my - 20
        hw, hh = 300, 214
        shadow(cv, hx, hy, hw, hh, 10, blur=18, dy=6, alpha=0.6)
        rrect(p, hx, hy, hw, hh, 10, fill=th["bg1"], stroke=th["line2"])
        text(p, "ФВ ЛЖ 59 % · откуда значение", hx + 12, hy + 10, 12, 600, th["text"])
        iw = (hw - 32) / 2
        for i, (clip, lab) in enumerate(((("gold7+ECG", 0), "4-кам. · КДО/КСО"), (("gold5", 30), "2-кам. · КДО/КСО"))):
            ix = hx + 12 + i * (iw + 8)
            rrect(p, ix, hy + 34, iw, 104, 6, fill="#000000")
            p.save()
            p.setClipRect(QRectF(ix, hy + 34, iw, 104))
            echo_view(p, ix, hy + 34, iw, 104, th, clip=clip, pad=(4, 4, 4, 4), lv_label=None, depth=False, points=False, lv=(i == 0))
            p.restore()
            text(p, lab, ix, hy + 142, 10.5, 500, th["text2"], w=iw, h=16, va="c")
        text(p, "Симпсон бипланово · 108 / 44 мл", hx + 12, hy + 164, 11, 500, th["text2"])
        text(p, "Открыть кадры  →", hx + 12, hy + 184, 11.5, 600, th["accent_text"])
    # right
    phrases_panel(p, cx1, top, rw, bottom, export_h=160)
    export_block(p, cx1, rw, bottom)
    status(p, saved="10:58", left_extra=[(None, "Отчёт: черновик v3", th["text2"])])
    return cv.save(out or OUT2 / "R3-report-full.png")


if __name__ == "__main__":
    print(render_r1())
    print(render_r2())
    print(render_r3())
