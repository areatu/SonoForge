"""Shared study data and composite widgets for the main-window mockups."""

from __future__ import annotations

import functools

from kit import *  # noqa: F401,F403
from kit import (
    C,
    Image,
    QImage,
    QPainter,
    QPen,
    QPointF,
    QRectF,
    Qt,
    SECTOR,
    LV_CONTOUR_G7,
    LA_CONTOUR_G7,
    catmull,
    circle,
    color_flow,
    doppler_image,
    draw_image_fit,
    ecg_path,
    icon,
    line,
    map_pt,
    mmode_synth,
    pil_to_qimage,
    rr_path,
    rrect,
    sector,
    text,
    tw,
    vgrad,
)

# ───────────────────────────── study (fictional) ─────────────────────────────

PT = {
    "name": "Петрова Мария Ивановна",
    "short": "Петрова М. И.",
    "sex": "Ж",
    "age": "59 лет",
    "pid": "0004127",
    "dob": "12.03.1967",
    "height": "164 см",
    "weight": "71 кг",
    "bsa": "1,79 м²",
    "hr": "68",
    "date": "08.10.2026",
    "time": "10:14",
    "device": "Samsung RS85",
    "clips": 24,
}

# id, label, mode badge, image spec, frames text, measured count
CLIPS = [
    ("c1", "4-кам.", "2D", ("sector", "gold7+ECG", 0), "83 к.", 1),
    ("c2", "2-кам.", "2D", ("sector", "gold5", 30), "125 к.", 0),
    ("c3", "3-кам.", "2D", ("sector", "gold2", 20), "80 к.", 0),
    ("c4", "4-кам.", "2D", ("sector", "gold6", 0), "120 к.", 0),
    ("c5", "ПСДО", "M", ("mmode",), "2,6 с", 4),
    ("c6", "МК", "ЦДК", ("color",), "64 к.", 0),
    ("c7", "МК", "PW", ("duplex", "pw_mv"), "4,1 с", 3),
    ("c8", "e′ септ.", "TDI", ("duplex", "tdi"), "4,1 с", 1),
    ("c9", "АК", "CW", ("duplex", "cw_av"), "4,1 с", 0),
    ("c10", "ТР", "CW", ("duplex", "cw_tr"), "4,1 с", 2),
    ("c11", "2-кам.", "2D", ("sector", "gold3", 30), "105 к.", 0),
    ("c12", "4-кам.", "2D", ("sector", "gold_Ph_ECG1", 40), "185 к.", 0),
    ("c13", "4-кам.", "2D", ("sector", "gold8+ECG", 10), "82 к.", 0),
    ("c14", "ЛЖ · зум", "2D", ("sector", "gold4", 30), "139 к.", 0),
    ("c15", "ВТЛЖ", "PW", ("duplex", "pw_lvot"), "4,1 с", 0),
    ("c16", "e′ лат.", "TDI", ("duplex", "tdi"), "4,1 с", 0),
    ("c17", "4-кам.", "2D", ("sector", "gold_Ph_ECG2", 10), "46 к.", 0),
    ("c18", "ПСДО · АК", "M", ("mmode",), "2,6 с", 0),
]

# frame markers of the main clip (83 frames, 30 fps, HR 68 → 26.5 frames per beat)
MAIN_FRAMES = 83
ED_FRAMES = [0, 26, 53, 79]
ES_FRAMES = [10, 36, 63]

# Protocols (names per the tool-panel spec; RU labels only)
PROTOCOLS = [
    # key, name, modes, done, total
    ("lv_lin", "ЛЖ линейно", ("2D", "M"), 2, 2),
    ("simpson", "Симпсон бипланово", ("2D",), 1, 4),
    ("la", "Объём ЛП", ("2D",), 0, 2),
    ("diast", "Диастолическая функция", ("PW", "TDI", "CW"), 5, 7),
    ("as", "Аортальный стеноз", ("2D", "PW", "CW"), 0, 4),
    ("tr", "ТР / СДЛА", ("CW",), 2, 2),
]
PROTO_ICON = {"lv_lin": "LV01", "simpson": "LV01", "la": "LA01", "diast": "MV01", "as": "AV01", "tr": "TV01"}

SIMPSON_STEPS = [
    # label, value, state: done / current / todo
    ("КДО · 4-кам.", "112 мл", "done"),
    ("КСО · 4-кам.", "кадр КС", "current"),
    ("КДО · 2-кам.", "—", "todo"),
    ("КСО · 2-кам.", "—", "todo"),
]

KEY_RESULTS = [
    ("ФВ ЛЖ", "—", "после КСО"),
    ("КДО · 4-кам.", "112", "мл"),
    ("ИММЛЖ", "90", "г/м²"),
    ("ОТС", "0,38", ""),
    ("E/A", "1,2", ""),
    ("СДЛА", "26", "мм рт. ст."),
]

REPORT_LV = [
    ("КДР ЛЖ", "48", "мм"),
    ("КСР ЛЖ", "31", "мм"),
    ("МЖП", "10", "мм"),
    ("ЗСЛЖ", "9", "мм"),
    ("ОТС", "0,38", ""),
    ("ММЛЖ", "162", "г"),
    ("ИММЛЖ", "90", "г/м²"),
]
REPORT_DIAST = [
    ("E", "78", "см/с"),
    ("A", "64", "см/с"),
    ("E/A", "1,2", ""),
    ("e′ септ.", "8", "см/с"),
    ("e′ лат.", "11", "см/с"),
    ("E/e′ ср.", "8,2", ""),
]
REPORT_RIGHT = [
    ("Vmax ТР", "2,4", "м/с"),
    ("Град. ТР", "23", "мм рт. ст."),
    ("ДПП", "3", "мм рт. ст."),
    ("СДЛА", "26", "мм рт. ст."),
]

# ───────────────────────────── themes ─────────────────────────────

THEME_A = {
    "bg0": "#0b0d0f",
    "bg1": "#131619",
    "bg2": "#1a1e22",
    "bg3": "#23282d",
    "line": "#262b31",
    "line2": "#343b42",
    "text": "#e6e9ec",
    "text2": "#a3abb3",
    "text3": "#6e7781",
    "accent": "#2bd1cb",
    "accent_text": "#5fe3dd",
    "on_accent": "#032421",
    "ok": "#3ccb7f",
    "warn": "#f2a93b",
    "err": "#f06a6a",
    "blue": "#5aa9ff",
    "active": "#ffc845",
}

# ───────────────────────────── imagery ─────────────────────────────


@functools.lru_cache(maxsize=None)
def duplex_pil(kind: str, w: int = 360, h: int = 250) -> Image.Image:
    """Doppler clip look: small 2-D reference image on top, spectrum below."""
    out = Image.new("L", (w, h), 0)
    ref = sector("gold7+ECG", 0).copy()
    rh = int(h * 0.36)
    ref.thumbnail((w, rh))
    out.paste(ref, ((w - ref.width) // 2, 2))
    sh = h - rh - 8
    spec = doppler_image(kind, w, sh, px_per_s=w / 3.2)
    out.paste(spec, (0, rh + 8))
    return out.convert("RGB")


@functools.lru_cache(maxsize=None)
def clip_qimage(spec: tuple) -> QImage:
    kind = spec[0]
    if kind == "sector":
        return pil_to_qimage(sector(spec[1], spec[2]))
    if kind == "mmode":
        return pil_to_qimage(mmode_synth(360, 250))
    if kind == "color":
        return pil_to_qimage(color_flow())
    if kind == "duplex":
        return pil_to_qimage(duplex_pil(spec[1]))
    raise ValueError(spec)


# ───────────────────────────── small widgets ─────────────────────────────


def kbd(p: QPainter, x, y, s, th, h=17.0, size=10.0, fg=None, bg=None, border=None) -> float:
    w = max(h, tw(s, size, 600) + 10)
    rrect(p, x, y, w, h, 4, fill=bg or th["bg3"], stroke=border or th["line2"])
    text(p, s, x, y, size, 600, fg or th["text2"], w=w, h=h, align="c", va="c")
    return w


def pill(p: QPainter, x, y, s, fg, bg, h=20.0, size=11.0, weight=600, icon_name=None, stroke=None, r=None, pad=8.0, tnum=False) -> float:
    iw = (size + 3) if icon_name else 0
    w = tw(s, size, weight, tnum=tnum) + pad * 2 + iw
    rrect(p, x, y, w, h, h / 2 if r is None else r, fill=bg, stroke=stroke)
    if icon_name:
        icon(p, icon_name, x + pad - 1, y + (h - size) / 2, size, fg)
    text(p, s, x + pad + iw, y, size, weight, fg, w=w, h=h, va="c", tnum=tnum)
    return w


def button(
    p: QPainter,
    x,
    y,
    th,
    label: str | None = None,
    icon_name: str | None = None,
    kind: str = "ghost",
    h=30.0,
    w=None,
    size=12.5,
    r=6.0,
    kbd_s: str | None = None,
    active=False,
    icon_size=None,
    weight=500,
    fg=None,
) -> float:
    isz = icon_size or (16 if h >= 28 else 14)
    pad = 10 if label else (h - isz) / 2
    content = (isz if icon_name else 0) + (6 if icon_name and label else 0) + (tw(label, size, weight) if label else 0)
    kw = (tw(kbd_s, 10, 600) + 10 + 8) if kbd_s else 0
    bw = w or (content + pad * 2 + kw)
    if kind == "primary":
        bg, col, stroke = th["accent"], th["on_accent"], None
    elif kind == "filled":
        bg, col, stroke = th["bg3"], th["text"], th["line2"]
    elif kind == "outline":
        bg, col, stroke = None, th["text"], th["line2"]
    elif kind == "tinted":
        bg, col, stroke = C(th["accent"], 0.16), th["accent_text"], C(th["accent"], 0.45)
    else:
        bg, col, stroke = None, th["text2"], None
    if active:
        bg, col, stroke = C(th["accent"], 0.16), th["accent_text"], C(th["accent"], 0.5)
    if fg:
        col = fg
    if bg is not None or stroke is not None:
        rrect(p, x, y, bw, h, r, fill=bg, stroke=stroke)
    cx = x + (bw - kw - content) / 2 if w else x + pad
    if icon_name:
        icon(p, icon_name, cx, y + (h - isz) / 2, isz, col)
        cx += isz + (6 if label else 0)
    if label:
        text(p, label, cx, y, size, weight, col, w=tw(label, size, weight) + 2, h=h, va="c")
        cx += tw(label, size, weight)
    if kbd_s:
        kbd(p, x + bw - kw + 2, y + (h - 17) / 2, kbd_s, th)
    return bw


def toggle(p: QPainter, x, y, on: bool, th, w=30.0, h=18.0, on_color=None):
    rrect(p, x, y, w, h, h / 2, fill=(on_color or th["accent"]) if on else th["bg3"], stroke=None if on else th["line2"])
    cx = x + w - h / 2 if on else x + h / 2
    circle(p, cx, y + h / 2, h / 2 - 2.5, fill="#ffffff")


def ring(p: QPainter, cx, cy, r, frac, color, track, width=3.0):
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(C(track), width)
    p.setPen(pen)
    p.drawEllipse(QPointF(cx, cy), r, r)
    if frac > 0:
        pen = QPen(C(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 90 * 16, int(-frac * 360 * 16))


def progress(p: QPainter, x, y, w, h, frac, color, track):
    rrect(p, x, y, w, h, h / 2, fill=track)
    if frac > 0:
        rrect(p, x, y, max(h, w * frac), h, h / 2, fill=color)


def status_icon(p: QPainter, x, y, state: str, th, size=14.0):
    cx, cy, r = x + size / 2, y + size / 2, size / 2
    if state == "done":
        circle(p, cx, cy, r, fill=th["ok"])
        icon(p, "l-check", x + size * 0.18, y + size * 0.18, size * 0.64, "#0b1a10", sw=3.2)
    elif state == "current":
        circle(p, cx, cy, r - 0.75, stroke=th["accent"], sw=1.5)
        circle(p, cx, cy, r * 0.42, fill=th["accent"])
    elif state == "stale":
        circle(p, cx, cy, r - 0.75, stroke=th["warn"], sw=1.5)
        icon(p, "l-refresh-cw", x + size * 0.22, y + size * 0.22, size * 0.56, th["warn"], sw=2.6)
    else:
        pen = QPen(C(th["text3"]), 1.3)
        pen.setDashPattern([2.2, 2.0])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r - 0.75, r - 0.75)


def section_label(p: QPainter, x, y, s, th, color=None, size=10.5) -> float:
    return text(p, s.upper(), x, y, size, 600, color or th["text3"], spacing=0.6)


def search_field(p: QPainter, x, y, w, h, placeholder, th, kbd_s=None, r=6.0, bg=None, border=None, size=12.5, fg=None):
    rrect(p, x, y, w, h, r, fill=bg or th["bg2"], stroke=border or th["line"])
    icon(p, "l-search", x + 9, y + (h - 15) / 2, 15, th["text3"])
    text(p, placeholder, x + 31, y, size, 400, fg or th["text3"], w=w - 40 - (40 if kbd_s else 0), h=h, va="c", elide=True)
    if kbd_s:
        kw = tw(kbd_s, 10, 600) + 10
        kbd(p, x + w - kw - 7, y + (h - 17) / 2, kbd_s, th)


def win_controls(p: QPainter, x_right, y, h, color, close_hover=False):
    """Windows caption buttons, right-aligned at x_right."""
    bw = 46
    x = x_right - 3 * bw
    cy = y + h / 2
    line(p, x + 18, cy, x + 28, cy, color, 1.0)
    rrect(p, x + bw + 18, cy - 5, 10, 10, 1.5, stroke=color, sw=1.0)
    if close_hover:
        p.fillRect(QRectF(x + 2 * bw, y, bw, h), C("#c42b1c"))
    line(p, x + 2 * bw + 18, cy - 5, x + 2 * bw + 28, cy + 5, color, 1.0)
    line(p, x + 2 * bw + 28, cy - 5, x + 2 * bw + 18, cy + 5, color, 1.0)
    return x


def traffic_lights(p: QPainter, x, y, d=12.0, gap=8.0, gray=False):
    cols = [("#ff5f57", "#e0443e"), ("#febc2e", "#dea123"), ("#28c840", "#1aab29")]
    for i, (fill, edge) in enumerate(cols):
        cx = x + d / 2 + i * (d + gap)
        if gray:
            circle(p, cx, y + d / 2, d / 2, fill="#4a4a4f", stroke="#5a5a60", sw=0.5)
        else:
            circle(p, cx, y + d / 2, d / 2, fill=fill, stroke=edge, sw=0.5)


def scrollbar(p: QPainter, x, y, h, pos, size, color, alpha=0.35, w=4.0):
    rrect(p, x, y + h * pos, w, h * size, w / 2, fill=C(color, alpha))


# ───────────────────────────── thumbnails ─────────────────────────────

MODE_COLORS = {"2D": "#9aa4ae", "M": "#c3a6ff", "PW": "#5aa9ff", "TDI": "#ffb86b", "CW": "#ff8fa3", "ЦДК": "#ff6b6b"}


def thumb(
    p: QPainter,
    x,
    y,
    w,
    h,
    clip,
    th,
    selected=False,
    r=6.0,
    show_label=True,
    label_inside=True,
    badge=True,
    measured=True,
    dim=False,
    accent=None,
):
    cid, label, mode, spec, frames, measured_n = clip
    acc = accent or th["accent"]
    path = rr_path(x, y, w, h, r)
    p.save()
    p.setClipPath(path)
    p.fillRect(QRectF(x, y, w, h), C("#000000"))
    q = clip_qimage(spec)
    draw_image_fit(p, q, x, y, w, h, "cover" if spec[0] in ("mmode",) else "contain")
    if show_label and label_inside:
        p.fillRect(QRectF(x, y + h * 0.52, w, h * 0.48), vgrad(y + h * 0.52, y + h, [(0, C("#000000", 0.0)), (1, C("#000000", 0.85))]))
    if dim:
        p.fillRect(QRectF(x, y, w, h), C("#000000", 0.45))
    p.restore()
    if badge:
        bc = MODE_COLORS.get(mode, "#9aa4ae")
        bw = tw(mode, 9, 700) + 8
        rrect(p, x + 5, y + 5, bw, 14, 3.5, fill=C("#000000", 0.62), stroke=C(bc, 0.7))
        text(p, mode, x + 5, y + 5, 9, 700, bc, w=bw, h=14, align="c", va="c")
    if measured and measured_n:
        s = str(measured_n)
        mw = max(16, tw(s, 9.5, 700) + 9)
        rrect(p, x + w - mw - 5, y + 5, mw, 15, 7.5, fill=C(acc, 0.92))
        text(p, s, x + w - mw - 5, y + 5, 9.5, 700, th.get("on_accent", "#000"), w=mw, h=15, align="c", va="c")
    if show_label and label_inside:
        text(p, label, x + 7, y + h - 19, 11, 600, "#ffffff", w=w - 14 - tw(frames, 9.5) - 4, h=15, va="c", elide=True)
        text(p, frames, x + w - 7 - tw(frames, 9.5), y + h - 19, 9.5, 500, C("#ffffff", 0.62), w=tw(frames, 9.5) + 2, h=15, va="c")
    if selected:
        rrect(p, x - 2, y - 2, w + 4, h + 4, r + 2, stroke=acc, sw=2.0)


# ───────────────────────────── viewer ─────────────────────────────


def echo_view(
    p: QPainter,
    x,
    y,
    w,
    h,
    th,
    clip=("gold7+ECG", 0),
    pad=(26, 26, 40, 60),
    lv=True,
    la=False,
    lv_color=None,
    lv_label="КДО · 4-кам.  112 мл",
    depth=True,
    info=True,
    bg="#000000",
    label_side="right",
    points=True,
    gamma=1.0,
) -> QRectF:
    """Black viewport with the echo sector and measurement overlays. Returns the image rect."""
    if bg:
        p.fillRect(QRectF(x, y, w, h), C(bg))
    top, bottom, left, right = pad
    q = pil_to_qimage(sector(clip[0], clip[1], gamma))
    rect = draw_image_fit(p, q, x + left, y + top, w - left - right, h - top - bottom)
    box = SECTOR[clip[0]]
    acc = lv_color or th["accent"]
    if lv and clip[0] == "gold7+ECG":
        pts = [map_pt(pt, box, rect) for pt in LV_CONTOUR_G7]
        path = catmull(pts)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # subtle dark halo for legibility
        p.setPen(QPen(C("#000000", 0.55), 4.2))
        p.drawPath(path)
        pen = QPen(C(acc), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawPath(path)
        a, b = pts[0], pts[-1]
        line(p, a[0], a[1], b[0], b[1], acc, 2.0)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        apex = pts[7]
        line(p, mid[0], mid[1], apex[0], apex[1], acc, 1.2, dash=[4, 3], alpha=0.75)
        # Simpson discs (faint)
        for k in range(1, 20):
            t = k / 20
            cx = mid[0] + (apex[0] - mid[0]) * t
            cy = mid[1] + (apex[1] - mid[1]) * t
            # crude half-width from contour bounding at this height
            ys = [pt[1] for pt in pts]
            if not (min(ys) < cy < max(ys)):
                continue
            lefts = [pt for pt in pts[:8]]
            rights = [pt for pt in pts[7:]]
            lx = _interp_x(lefts, cy)
            rx = _interp_x(rights, cy)
            if lx is not None and rx is not None:
                line(p, lx + 1.5, cy, rx - 1.5, cy, acc, 0.8, alpha=0.22)
        if points:
            for pt in pts[::2] + [pts[-1]]:
                circle(p, pt[0], pt[1], 2.6, fill=acc, stroke="#000000", sw=0.8)
        if lv_label:
            lx = max(pt[0] for pt in pts) + 14 if label_side == "right" else min(pt[0] for pt in pts) - 14
            ly = pts[10][1] - 12
            lw = tw(lv_label, 12, 600, tnum=True) + 20
            if label_side != "right":
                lx -= lw
            rrect(p, lx, ly, lw, 24, 6, fill=C("#000000", 0.72), stroke=C(acc, 0.85))
            text(p, lv_label, lx + 9, ly, 12, 600, acc, w=lw, h=24, va="c", tnum=True)
            line(p, lx if label_side == "right" else lx + lw, ly + 12, pts[10][0] + (3 if label_side == "right" else -3), pts[10][1], acc, 1.0, alpha=0.7)
    if la and clip[0] == "gold7+ECG":
        pts = [map_pt(pt, box, rect) for pt in LA_CONTOUR_G7]
        pen = QPen(C(th.get("warn", "#f2a93b")), 1.8)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(catmull(pts))
    if depth:
        sx = rect.right() + 10
        y0, y1 = rect.top() + 4, rect.bottom() - 6
        line(p, sx, y0, sx, y1, "#ffffff", 1.0, alpha=0.35)
        for cm in range(0, 17):
            yy = y0 + (y1 - y0) * cm / 16
            L = 7 if cm % 5 == 0 else 4
            line(p, sx, yy, sx + L, yy, "#ffffff", 1.0, alpha=0.5)
            if cm % 5 == 0:
                text(p, str(cm), sx + 10, yy, 9.5, 500, C("#ffffff", 0.55), va="c")
        text(p, "см", sx + 6, y1 + 6, 9, 500, C("#ffffff", 0.45))
    return rect


def _interp_x(pts, y):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if (y1 - y) * (y2 - y) <= 0 and y1 != y2:
            t = (y - y1) / (y2 - y1)
            return x1 + (x2 - x1) * t
    return None


def info_overlay(p: QPainter, x, y, lines, size=10.5, color="#ffffff", alpha=0.62, lh=15):
    for i, ln in enumerate(lines):
        text(p, ln, x, y + i * lh, size, 500, C(color, alpha))


# ───────────────────────────── cine timeline ─────────────────────────────


def cine_track(
    p: QPainter,
    x,
    y,
    w,
    h,
    th,
    cur=0,
    frames=MAIN_FRAMES,
    ed=ED_FRAMES,
    es=ES_FRAMES,
    track_bg=None,
    ecg_color=None,
    labels=True,
    es_suggest=10,
    r=5.0,
):
    """Timeline with ECG trace, end-diastole/end-systole marks and the playhead."""
    rrect(p, x, y, w, h, r, fill=track_bg or th["bg2"], stroke=th["line"])
    fps = 30.0
    dur = frames / fps
    pps = w / dur
    p.save()
    p.setClipRect(QRectF(x + 1, y + 1, w - 2, h - 2))
    path = ecg_path(x, y + 2, w, h - 4, hr=68.0, px_per_s=pps, t0=0.0)
    pen = QPen(C(ecg_color or th["ok"], 0.9), 1.25)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()

    def fx(fr):
        return x + w * (fr + 0.5) / frames

    for fr in ed:
        xx = fx(fr)
        line(p, xx, y + 2, xx, y + h - 2, th["accent"], 1.0, alpha=0.55)
        if labels:
            text(p, "КД", xx + 3, y + 2, 8.5, 700, th["accent_text"])
    for fr in es:
        xx = fx(fr)
        line(p, xx, y + 2, xx, y + h - 2, th["warn"], 1.0, alpha=0.6)
        if labels:
            text(p, "КС", xx + 3, y + 2, 8.5, 700, th["warn"])
    if es_suggest is not None:
        xx = fx(es_suggest)
        rrect(p, xx - 7, y + h - 12, 14, 10, 3, fill=C(th["warn"], 0.9))
        icon(p, "l-chevron-up", xx - 5, y + h - 12, 10, "#1a1203", sw=3)
    # playhead
    px_ = fx(cur)
    line(p, px_, y - 3, px_, y + h + 3, "#ffffff", 1.6)
    circle(p, px_, y - 3, 4.2, fill="#ffffff")
