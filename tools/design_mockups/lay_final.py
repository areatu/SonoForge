"""Round 3 · approved UI redesign mockups: docs/images/ui-redesign/.

The user's answers to round 2:

* main window: keep A1, take M1 and M2, plus the current arrangement (clips on the
  left, tools on the right); the user picks the layout in Settings, as in O1;
* the protocol step is a bar under the image, never a banner over it;
* report: R3, a separate mode; the switch has two states, «Изображения | Отчёт»;
* reference: S1 window and S2 card, but the card shows no attached images.

Every main-window variant shares one header (one-row patient line with the mode
switch), the step bar and the cine bar, so only the panels move.
"""

from __future__ import annotations

import lay_ref as R
import lay_report as RP
import lay_settings as ST
import screen_a as A
from common import C, QRectF, button, circle, hline, icon, rrect, search_field, section_label, text, toggle, tw, vline
from kit import REPO, Canvas, Image, logo, pil_to_qimage, shadow
from lay_common import (
    SB,
    TB,
    TH,
    W,
    H,
    S,
    clips_grid,
    filmstrip,
    patient_line,
    proto_panel,
    rbutton,
    segmented,
    status,
    step_bar,
    title,
    tool_rail_docked,
    viewer_area,
    viewer_corner,
)

OUT3 = REPO / "docs/images/ui-redesign"
PL = 42  # one-row patient line, same in every layout
TOOLBAR_H, STEP_H, CINE_H, FILM_H = 42, 58, 66, 112
CLIPS_W, PANEL_W, RAIL_W = 216, 352, 70
MODES = ("Изображения", "Отчёт")


def header(p, sel=0):
    """Patient line + actions + the two-state «Изображения | Отчёт» switch on the right."""
    th = TH
    patient_line(p, TB, PL, actions=False)
    bh = 30
    by = TB + (PL - bh) / 2
    sw_ = sum(tw(s, 12, 600) + 28 for s in MODES) + 4
    xr = W - 14
    segmented(p, xr - sw_, by, list(MODES), sel, h=bh)
    xr -= sw_ + 10
    vline(p, xr, TB + 11, PL - 22, th["line2"])
    xr -= 8 + 32
    icon(p, "l-book-open", xr + 8, by + 7, 16, th["text2"])  # Справочник (S1)
    xr -= 2
    for lab, ico in (("Презентация", "l-presentation"), ("Сравнить", "l-columns-2")):
        xr = rbutton(p, xr, by, lab, ico, "ghost", h=bh) - 2
    for ico in ("l-cloud-download", "l-folder-open"):  # PACS ▾ (загрузить / отправить), Открыть: icons with tooltips, also in Ctrl+K
        xr -= 32
        icon(p, ico, xr + 8, by + 7, 16, th["text2"])


def viewer_column(p, vx, top, vw, bottom, toolbar=True, film=False, step=True, corner=False):
    """Viewer stack: optional tool row, image, step bar under the image, cine bar, optional filmstrip."""
    y = top
    if toolbar:
        A.viewer_toolbar(p, TH, vx, top, vw, TOOLBAR_H)
        y += TOOLBAR_H
    film_h = FILM_H if film else 0
    cine_h = 62 if film else CINE_H
    step_h = STEP_H if step else 0
    img_h = bottom - film_h - cine_h - step_h - y
    viewer_area(p, vx, y, vw, img_h, banner=False, pad=(24, 12, 60, 84))
    if corner:
        viewer_corner(p, vx + vw - 14, y + img_h - 12)
    if step:
        step_bar(p, vx, y + img_h, vw, step_h)
    A.cine_bar(p, TH, vx, bottom - film_h - cine_h, vw, cine_h)
    if film:
        filmstrip(p, vx, bottom - film_h, vw, film_h)


def frame(sel=0):
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    title(p)
    header(p, sel)
    return cv, p, TB + PL, H - SB


def render_u1_classic():
    """A1 «Классическая» (default): clips left, tool row above the image, protocols right."""
    cv, p, top, bottom = frame()
    clips_grid(p, 0, top, CLIPS_W, bottom, border="right")
    viewer_column(p, CLIPS_W, top, W - CLIPS_W - PANEL_W, bottom)
    proto_panel(p, W - PANEL_W, top, PANEL_W, bottom)
    status(p)
    return cv.save(OUT3 / "01-main-classic.png")


def render_u2_mirrored():
    """M1 «Зеркальная»: protocols left, clips right."""
    cv, p, top, bottom = frame()
    lpw = 344
    proto_panel(p, 0, top, lpw, bottom, border="right")
    clips_grid(p, W - CLIPS_W, top, CLIPS_W, bottom, border="left")
    viewer_column(p, lpw, top, W - lpw - CLIPS_W, bottom)
    status(p)
    return cv.save(OUT3 / "02-main-mirrored.png")


def render_u3_filmstrip():
    """M2 «Лента снизу»: labelled tool panel left of the image, filmstrip under the cine bar."""
    cv, p, top, bottom = frame()
    tool_rail_docked(p, 0, top, RAIL_W, bottom)
    proto_panel(p, W - PANEL_W, top, PANEL_W, bottom)
    viewer_column(p, RAIL_W, top, W - RAIL_W - PANEL_W, bottom, toolbar=False, film=True, corner=True)
    status(p)
    return cv.save(OUT3 / "03-main-filmstrip.png")


PANEL_TOOLS = [
    ("l-mouse-pointer-2", "Указатель", None),
    ("l-ruler", "Линейка", "L"),
    ("l-square-dashed", "Площадь", "A"),
    ("l-spline", "Контур", "C"),
    ("l-audio-waveform", "Допплер", "V"),
    ("l-crosshair", "Маркер", "K"),
    ("l-sparkles", "Авто-контур", None),
    ("l-ellipsis", "Ещё", None),
]


def panel_with_tools(p, x, top, w, bottom):
    """Right panel as in the app today: tool buttons on top, then search and protocols."""
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
    section_label(p, x + 14, y, "Инструменты", th)
    text(p, "настроить", x + w - 14 - tw("настроить", 11), y - 1, 11, 500, th["text3"])
    y += 20
    cols, gap, bh = 4, 6, 50
    bw = (w - 24 - gap * (cols - 1)) / cols
    for i, (ico, lab, key) in enumerate(PANEL_TOOLS):
        bx = x + 12 + (i % cols) * (bw + gap)
        by = y + (i // cols) * (bh + gap)
        act = ico == "l-spline"
        dis = ico == "l-audio-waveform"
        rrect(p, bx, by, bw, bh, 8, fill=C(th["accent"], 0.16) if act else th["bg2"], stroke=C(th["accent"], 0.5) if act else th["line"])
        col = th["accent_text"] if act else (th["text3"] if dis else th["text2"])
        icon(p, ico, bx + bw / 2 - 9, by + 8, 18, col)
        text(p, lab, bx, by + 31, 10.5, 600 if act else 500, col, w=bw, h=14, align="c", va="c")
        if key:
            text(p, key, bx + bw - 15, by + 5, 8.5, 700, th["text3"])
    y += 2 * bh + gap + 12
    hline(p, x, y, w, th["line"])
    proto_panel(p, x, y, w, bottom, tabs=None, groups=False)


def render_u4_tools_in_panel():
    """Current arrangement: clips left, tool buttons in the right panel, nothing above the image."""
    cv, p, top, bottom = frame()
    clips_grid(p, 0, top, CLIPS_W, bottom, border="right")
    viewer_column(p, CLIPS_W, top, W - CLIPS_W - PANEL_W, bottom, toolbar=False, corner=True)
    panel_with_tools(p, W - PANEL_W, top, PANEL_W, bottom)
    status(p)
    return cv.save(OUT3 / "04-main-tools-in-panel.png")


def render_u5_report():
    """R3 with the two-state switch."""
    return RP.render_r3(out=OUT3 / "05-report-mode.png", modes=MODES, sel=1)


def render_u6_reference_card():
    """S2 card without the figure, over the classic layout (no protocol running → no step bar)."""
    cv, p, top, bottom = frame()
    clips_grid(p, 0, top, CLIPS_W, bottom, border="right")
    viewer_column(p, CLIPS_W, top, W - CLIPS_W - PANEL_W, bottom, step=False)
    # norm dots carry only the reference grades (норма / лёгкое / умеренное / тяжёлое): МЖП 10 мм is within 6–10
    R.LV_MEAS = [(lab, val, unit, "ok" if st == "edge" else st) for lab, val, unit, st in R.LV_MEAS]
    rows_y = R.measurements_panel(p, W - PANEL_W, top, PANEL_W, bottom, hover=0)
    R.ref_popover(cv, p, W - PANEL_W, rows_y[0] + 16, figure=False)
    status(p)
    return cv.save(OUT3 / "06-reference-card.png")


def render_u7_settings():
    """O1 with the three approved layouts and the tool-button placement."""
    th = TH
    cv = Canvas(W, H, S, bg=th["bg0"])
    p = cv.p
    bg = OUT3 / "01-main-classic.png"
    if bg.exists():
        p.drawImage(QRectF(0, 0, W, H), pil_to_qimage(Image.open(bg).convert("RGB")))
    p.fillRect(QRectF(0, 0, W, H), C("#000000", 0.58))
    dw, dh = 1200, 820
    dx, dy = (W - dw) / 2, (H - dh) / 2
    shadow(cv, dx, dy, dw, dh, 10, blur=40, dy=18, alpha=0.7)
    rrect(p, dx, dy, dw, dh, 9, fill="#15181b", stroke="#2c3238")
    logo(p, dx + 14, dy + 11, 18, light=True)
    text(p, "Настройки", dx + 44, dy, 12.5, 500, th["text"], w=200, h=40, va="c")
    icon(p, "l-x", dx + dw - 32, dy + 13, 14, th["text2"])
    icon(p, "l-minus", dx + dw - 78, dy + 13, 14, th["text2"])
    nx, ny, nw = dx + 10, dy + 50, 286
    search_field(p, nx + 6, ny, nw - 12, 34, "Найти параметр", th, r=6, bg="#1d2125", border="#2a3036")
    y = ny + 50
    for i, (ico, lab) in enumerate(ST.NAV):
        sel = i == 1
        if sel:
            rrect(p, nx, y, nw, 38, 6, fill="#262b30")
            rrect(p, nx + 1, y + 11, 3, 16, 1.5, fill=th["accent"])
        icon(p, ico, nx + 16, y + 11, 16, th["text"] if sel else th["text2"])
        text(p, lab, nx + 46, y, 13, 600 if sel else 400, th["text"] if sel else th["text2"], w=nw - 56, h=38, va="c")
        y += 41
    cx = dx + nw + 36
    cw = dx + dw - 28 - cx
    y = dy + 54
    text(p, "Внешний вид и компоновка", cx, y, 24, 600, th["text"])
    y += 52
    card_h = 330
    ST.card(p, cx, y, cw, card_h)
    icon(p, "l-layout-grid", cx + 20, y + 20, 18, th["text2"])
    text(p, "Компоновка главного окна", cx + 56, y + 16, 13, 500, th["text"])
    text(p, "Где находятся клипы, протоколы и кнопки инструментов. Меняется без перезапуска.", cx + 56, y + 36, 11.5, 400, th["text3"])
    tiles = [
        ("classic", "Классическая", "клипы слева, протоколы справа", "по умолчанию"),
        ("mirror", "Зеркальная", "протоколы слева, клипы справа", None),
        ("strip", "Лента снизу", "клипы под снимком, кнопки слева", None),
    ]
    gap = 18
    tw_ = (cw - 40 - 2 * gap) / 3
    th_ = tw_ * 0.5
    for i, (kind, name, sub, note) in enumerate(tiles):
        tx = cx + 20 + i * (tw_ + gap)
        ty = y + 70
        sel = i == 0
        if sel:
            rrect(p, tx - 6, ty - 6, tw_ + 12, th_ + 66, 10, fill=C(th["accent"], 0.08), stroke=C(th["accent"], 0.45))
        ST.wire(p, tx, ty, tw_, th_, kind, sel=sel)
        # the step bar under the image in every layout
        if kind == "classic":
            p.fillRect(QRectF(tx + tw_ * 0.18, ty + th_ - 16, tw_ * 0.54, 7), C(th["accent"], 0.25))
        elif kind == "strip":
            p.fillRect(QRectF(tx + tw_ * 0.07, ty + th_ - 37, tw_ * 0.65, 7), C(th["accent"], 0.25))
        ry = ty + th_ + 12
        circle(p, tx + 8, ry + 8, 8, stroke=th["accent"] if sel else th["text3"], sw=1.5)
        if sel:
            circle(p, tx + 8, ry + 8, 4, fill=th["accent"])
        nx_ = tx + 24 + text(p, name, tx + 24, ry - 1, 12.5, 600 if sel else 500, th["text"])
        if note:
            text(p, note, nx_ + 8, ry, 11, 500, th["text3"])
        text(p, sub, tx + 24, ry + 18, 11, 400, th["text3"], w=tw_ - 24, elide=True)
    ry = y + 70 + th_ + 70
    hline(p, cx + 16, ry, cw - 32, "#262b30")
    ry += 1
    icon(p, "l-mouse-pointer-2", cx + 20, ry + 21, 18, th["text2"])
    text(p, "Кнопки инструментов", cx + 56, ry + 12, 13, 500, th["text"])
    text(p, "По умолчанию — как в выбранной компоновке", cx + 56, ry + 32, 11.5, 400, th["text3"])
    items = ["Над снимком", "Слева от снимка", "В правой панели"]
    sw_ = sum(tw(s, 12, 600) + 28 for s in items) + 4
    segmented(p, cx + cw - 20 - sw_, ry + 15, items, 0, h=30)
    y += card_h + 14
    rows = [
        ("l-contrast", "Тема", "Графит — нейтральная тёмная; прежние темы остаются в списке", lambda xr, cy: ST.dropdown(p, xr, cy, "Графит (тёмная)")),
        ("l-palette", "Акцентный цвет", "Активные кнопки и выделение; цвета разметки на снимке не меняются", None),
        ("l-type", "Подписи кнопок инструментов", "Иконки с подписями удобнее в начале, только иконки — компактнее", lambda xr, cy: ST.dropdown(p, xr, cy, "Иконки и подписи", w=220)),
        ("l-scan", "Одиночный файл — в режиме «Фокус»", "Без панелей исследования: инструменты и кинопетля вокруг снимка", lambda xr, cy: toggle(p, xr - 40, cy - 10, True, th, w=40, h=20)),
        ("l-keyboard", "Буквы клавиш на кнопках", "Маленькие L, A, C, V рядом с иконками инструментов", lambda xr, cy: toggle(p, xr - 40, cy - 10, True, th, w=40, h=20)),
    ]
    for ico, t, d, ctl in rows:
        ST.setting_row(p, cx, y, cw, ico, t, d, ctl, h=56)
        if t == "Акцентный цвет":
            sx = cx + cw - 20
            for col in reversed(ST.ACCENTS):
                sx -= 30
                circle(p, sx + 12, y + 28, 11, fill=col)
                if col == ST.ACCENTS[0]:
                    circle(p, sx + 12, y + 28, 15, stroke="#ffffff", sw=1.6)
        y += 60
    fy = dy + dh - 56
    hline(p, dx + nw + 20, fy, dw - nw - 20, "#262b30")
    text(p, "Изменения применяются сразу", cx, fy, 11.5, 500, th["text3"], w=300, h=56, va="c")
    text(p, "Сбросить раздел", cx + 200, fy, 11.5, 600, th["accent_text"], w=200, h=56, va="c")
    button(p, dx + dw - 28 - 110, fy + 12, th, "Готово", None, "primary", h=32, w=110, weight=600)
    return cv.save(OUT3 / "07-settings-layout.png")


if __name__ == "__main__":
    for fn in (render_u1_classic, render_u2_mirrored, render_u3_filmstrip, render_u4_tools_in_panel, render_u5_report, render_u6_reference_card, render_u7_settings):
        print(fn())
