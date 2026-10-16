"""Round 2 · «Фокус» for a single file (from C1): Windows 11 title bar, clean window."""

from __future__ import annotations

import screen_c as SC
from common import C, QRectF, button, cine_track, circle, echo_view, icon, kbd, pill, rrect, status_icon, text, tw, vline, win_controls
from kit import Canvas, logo
from lay_common import OUT2, TH, W, H, S

FT = 34  # slim title bar


def focus_title(p):
    th = TH
    p.fillRect(QRectF(0, 0, W, FT), C("#0b0d0f"))
    logo(p, 12, 8, 18, light=True)
    x = 42
    x += text(p, "IMG_0007.dcm", x, 0, 12.5, 600, th["text"], w=300, h=FT, va="c") + 8
    x += text(p, "· 4-кам. · Петрова М. И. · 08.10.2026", x, 0, 12.5, 400, th["text3"], w=500, h=FT, va="c") + 12
    pill(p, x, 8, "Фокус", th["accent_text"], C(th["accent"], 0.14), h=18, size=10, icon_name="l-scan")
    xr = W - 3 * 46 - 10
    s = "Обычный вид"
    bw = button(p, 0, -100, th, s, "l-minimize-2", "ghost", h=26, size=12, kbd_s="F")
    button(p, xr - bw, 4, th, s, "l-minimize-2", "ghost", h=26, size=12, kbd_s="F")
    win_controls(p, W, 0, FT, th["text2"])


def base(cv, bottom_pad=86):
    p = cv.p
    p.fillRect(QRectF(0, FT, W, H - FT), C("#000000"))
    echo_view(p, 0, FT, W, H - FT, TH, pad=(14, bottom_pad, 0, 0), lv_label="КДО · 4-кам.  112 мл", depth=False, bg=None)


def info_hud(cv):
    p = cv.p
    th = TH
    SC.hud(cv, 16, FT + 14, 262, 58, 12)
    text(p, "SAMSUNG RS85 · PM1-6A", 30, FT + 22, 10.5, 600, th["text2"])
    text(p, "2D · 16 см · 30 Гц · кадр 1 / 83 · КД", 30, FT + 38, 11.5, 600, th["text"])
    icon(p, "l-check", 30, FT + 55, 11, th["ok"], sw=2.4)
    text(p, "0,28 мм/пикс. · DICOM", 44, FT + 53, 10.5, 500, th["ok"])


def hint_hud(cv, y=None):
    p = cv.p
    th = TH
    s = "Контур: ставьте точки по эндокарду ЛЖ"
    w = tw(s, 12.5, 600) + 300
    x = W / 2 - w / 2
    y = y or FT + 14
    SC.hud(cv, x, y, w, 38, 12)
    icon(p, "l-spline", x + 14, y + 11, 16, th["accent_text"])
    text(p, s, x + 38, y, 12.5, 600, th["text"], w=w, h=38, va="c")
    kx = x + 38 + tw(s, 12.5, 600) + 16
    for k, lab in (("Enter", "готово"), ("Esc", "отмена")):
        kx += kbd(p, kx, y + 10.5, k, th, fg=th["text2"], bg=C("#ffffff", 0.06), border=C("#ffffff", 0.14)) + 5
        kx += text(p, lab, kx, y, 11.5, 500, th["text2"], w=80, h=38, va="c") + 14


def measure_card(cv):
    p = cv.p
    th = TH
    w, h = 300, 236
    x, y = W - 16 - w, FT + 14
    SC.hud(cv, x, y, w, h, 14)
    ix = x + 16
    text(p, "Измерения", ix, y + 12, 13.5, 600, th["text"])
    text(p, "в этом файле", ix + tw("Измерения", 13.5, 600) + 8, y + 15, 11, 500, th["text3"])
    icon(p, "l-chevron-up", x + w - 30, y + 14, 15, th["text2"])
    rows = [("done", "КДО · 4-кам.", "112 мл"), ("current", "КСО · 4-кам.", "измеряется"), ("todo", "ФВ ЛЖ (4-кам.)", "после КСО")]
    yy = y + 44
    for st, lab, val in rows:
        if st == "current":
            rrect(p, x + 8, yy - 2, w - 16, 34, 8, fill=C(th["accent"], 0.15), stroke=C(th["accent"], 0.5))
        status_icon(p, ix, yy + 8, st, th, size=14)
        text(p, lab, ix + 24, yy, 12.5, 600 if st != "todo" else 500, th["text"] if st != "todo" else th["text2"], w=150, h=30, va="c")
        col = th["text"] if st == "done" else (th["accent_text"] if st == "current" else th["text3"])
        text(p, val, x + w - 16 - tw(val, 12, 600, tnum=True), yy, 12, 600, col, w=100, h=30, va="c", tnum=True)
        yy += 36
    yy += 6
    bw = (w - 32 - 8) / 2
    button(p, ix, yy, th, "Копировать", "l-copy", "outline", h=30, w=bw, size=12)
    button(p, ix + bw + 8, yy, th, "В исследование", "l-plus", "outline", h=30, w=bw, size=12)
    yy += 42
    text(p, "Файл без исследования: значения не попадут в отчёт, пока не добавите их.", ix, yy, 10.5, 500, th["text3"], w=w - 32, wrap=True, lh=14)


def cine_pill(cv, y=None, w=760):
    p = cv.p
    th = TH
    x = W / 2 - w / 2
    y = y or H - 16 - 52
    SC.hud(cv, x, y, w, 52, 26)
    icon(p, "l-step-back", x + 20, y + 17, 18, th["text"])
    circle(p, x + 68, y + 26, 18, fill=th["accent"])
    icon(p, "l-play", x + 61, y + 18.5, 15, th["on_accent"], sw=2.4)
    icon(p, "l-step-forward", x + 98, y + 17, 18, th["text"])
    cine_track(p, x + 134, y + 11, w - 134 - 122, 30, th, track_bg=C("#ffffff", 0.05), r=8)
    text(p, "1 / 83", x + w - 106, y + 9, 13, 600, th["text"], tnum=True)
    text(p, "1× · 30 к/с", x + w - 106, y + 27, 10.5, 500, th["text3"])
    icon(p, "l-repeat", x + w - 36, y + 17, 18, th["accent"])


def render_f1():
    """C1 for one file: tool rail left, small measurement card right, cine pill bottom — nothing else."""
    cv = Canvas(W, H, S, bg="#000000")
    p = cv.p
    base(cv)
    focus_title(p)
    info_hud(cv)
    hint_hud(cv)
    SC.tool_rail(cv, cy=FT + (H - FT) / 2 - 20, tooltip=False)
    measure_card(cv)
    cine_pill(cv)
    return cv.save(OUT2 / "F1-focus-single-file.png")


DOCK_TOOLS = [
    ("l-mouse-pointer-2", None),
    ("l-move", None),
    ("l-zoom-in", None),
    ("l-sun-medium", None),
    None,
    ("l-ruler", "L"),
    ("l-square-dashed", "A"),
    ("l-spline", "C"),
    ("l-audio-waveform", "V"),
    ("l-crosshair", "K"),
    None,
    ("l-sparkles", None),
]


def render_f2():
    """Everything in one bottom dock: tools · cine · results. The top of the image stays empty."""
    cv = Canvas(W, H, S, bg="#000000")
    p = cv.p
    th = TH
    base(cv, bottom_pad=96)
    focus_title(p)
    # small corner info (no HUD frame)
    text(p, "2D · 16 см · 30 Гц · кадр 1 / 83 · КД", 18, FT + 14, 11, 600, C("#ffffff", 0.62))
    text(p, "0,28 мм/пикс. · DICOM", 18, FT + 31, 10.5, 500, C(th["ok"], 0.85))
    w, h = 1300, 64
    x, y = W / 2 - w / 2, H - 16 - h
    SC.hud(cv, x, y, w, h, 18)
    bx = x + 10
    for t in DOCK_TOOLS:
        if t is None:
            bx += 4
            vline(p, bx, y + 16, h - 32, C("#ffffff", 0.14))
            bx += 6
            continue
        ico, key = t
        if ico == "l-spline":
            rrect(p, bx, y + 10, 44, 44, 11, fill=th["accent"])
            icon(p, ico, bx + 12, y + 22, 20, th["on_accent"], sw=2.0)
        else:
            dis = ico == "l-audio-waveform"
            icon(p, ico, bx + 12, y + 22, 20, th["text3"] if dis else th["text"])
            if key:
                text(p, key, bx + 32, y + 38, 8.5, 700, th["text3"])
        bx += 46
    bx += 8
    vline(p, bx, y + 12, h - 24, C("#ffffff", 0.14))
    bx += 14
    circle(p, bx + 18, y + h / 2, 18, fill=C("#ffffff", 0.10))
    icon(p, "l-play", bx + 11, y + h / 2 - 7.5, 15, th["text"], sw=2.4)
    bx += 46
    tw_ = 270
    cine_track(p, bx, y + 15, tw_, 34, th, track_bg=C("#ffffff", 0.05), r=8)
    bx += tw_ + 10
    text(p, "1 / 83", bx, y + 13, 13, 600, th["text"], tnum=True)
    text(p, "кадр", bx, y + 32, 10.5, 500, th["text3"])
    bx += 56
    vline(p, bx, y + 12, h - 24, C("#ffffff", 0.14))
    bx += 14
    chips = [("done", "КДО · 4-кам.", "112 мл"), ("current", "КСО · 4-кам.", "…")]
    for st, lab, val in chips:
        s = f"{lab}  {val}"
        cw = tw(s, 12, 600, tnum=True) + 38
        if st == "current":
            rrect(p, bx, y + 16, cw, 32, 16, fill=C(th["accent"], 0.16), stroke=C(th["accent"], 0.55))
        else:
            rrect(p, bx, y + 16, cw, 32, 16, fill=C("#ffffff", 0.07), stroke=C("#ffffff", 0.1))
        status_icon(p, bx + 10, y + 25, st, th, size=14)
        text(p, s, bx + 30, y + 16, 12, 600, th["text"] if st == "done" else th["accent_text"], w=cw, h=32, va="c", tnum=True)
        bx += cw + 8
    icon(p, "l-copy", x + w - 40, y + 22, 18, th["text2"])
    # transient hint above the dock (fades after 3 s)
    s = "Enter — готово · Esc — отмена · ПКМ — убрать точку"
    sw = tw(s, 11.5, 500) + 28
    rrect(p, W / 2 - sw / 2, y - 40, sw, 28, 14, fill=C("#000000", 0.62), stroke=C("#ffffff", 0.1))
    text(p, s, W / 2 - sw / 2, y - 40, 11.5, 500, th["text2"], w=sw, h=28, align="c", va="c")
    return cv.save(OUT2 / "F2-focus-bottom-dock.png")


if __name__ == "__main__":
    print(render_f1())
    print(render_f2())
