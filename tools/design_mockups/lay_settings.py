"""Round 2 · settings in the Windows 11 style: «Внешний вид и компоновка» with a layout picker."""

from __future__ import annotations

from common import C, QRectF, button, circle, hline, icon, rrect, search_field, text, toggle, tw
from kit import OUT, Canvas, Image, logo, pil_to_qimage, shadow
from lay_common import OUT2, TH, W, H, S

NAV = [
    ("l-settings", "Общие"),
    ("l-palette", "Внешний вид и компоновка"),
    ("l-wrench", "Инструменты"),
    ("l-list-checks", "Протоколы и нормы"),
    ("l-ruler", "Измерения и единицы"),
    ("l-file-text", "Отчёт и бланк"),
    ("l-server", "PACS / Orthanc"),
    ("l-keyboard", "Горячие клавиши"),
    ("l-languages", "Язык"),
    ("l-shield-check", "Конфиденциальность"),
    ("l-info", "О программе"),
]
ACCENTS = ["#2bd1cb", "#4c9bff", "#3ccb7f", "#f2a93b", "#b48cff", "#ff7a90"]


def wire(p, x, y, w, h, kind, sel=False):
    """Tiny wireframe of a main-window layout."""
    th = TH
    rrect(p, x, y, w, h, 6, fill="#07090a", stroke=C(th["accent"], 0.9) if sel else th["line2"], sw=1.6 if sel else 1.0)
    p.save()
    p.setClipRect(QRectF(x + 1, y + 1, w - 2, h - 2))
    t = 10  # title strip
    p.fillRect(QRectF(x, y, w, t), C("#14181c"))
    for i in range(3):
        circle(p, x + w - 8 - i * 7, y + 5, 1.6, fill=th["text3"])
    body_y, body_h = y + t, h - t
    panel, img, tool = C("#20262c"), C("#000000"), C("#1a1f24")

    def thumbs(px, py, pw, ph, cols=2, n=8, horiz=False):
        if horiz:
            tw_ = (ph - 6) * 1.3
            for k in range(n):
                rrect(p, px + 3 + k * (tw_ + 3), py + 3, tw_, ph - 6, 1.5, fill="#3a434c")
        else:
            cw = (pw - 3 * (cols + 1)) / cols
            ch = cw * 0.72
            for k in range(n):
                rrect(p, px + 3 + (k % cols) * (cw + 3), py + 3 + (k // cols) * (ch + 3), cw, ch, 1.5, fill="#3a434c")

    def rows(px, py, pw, ph):
        p.fillRect(QRectF(px, py, pw, ph), tool)
        rrect(p, px + 4, py + 5, pw - 8, 16, 2, fill=C(th["accent"], 0.35))
        for k in range(6):
            rrect(p, px + 4, py + 26 + k * 8, (pw - 8) * (0.9 - (k % 3) * 0.18), 3, 1.5, fill="#3a434c")

    def image(px, py, pw, ph):
        p.fillRect(QRectF(px, py, pw, ph), img)
        cx, cy = px + pw / 2, py + ph * 0.18
        r = min(pw, ph) * 0.62
        from common import QPainterPath, QPointF

        path = QPainterPath()
        path.moveTo(QPointF(cx, cy))
        path.lineTo(QPointF(cx - r * 0.62, cy + r * 0.78))
        path.quadTo(QPointF(cx, cy + r * 1.02), QPointF(cx + r * 0.62, cy + r * 0.78))
        path.closeSubpath()
        p.setPen(C("#000000", 0.0))
        p.setBrush(C("#7d858c", 0.55))
        p.drawPath(path)

    if kind == "classic":
        p.fillRect(QRectF(x, body_y, w * 0.18, body_h), panel)
        thumbs(x, body_y + 2, w * 0.18, body_h)
        p.fillRect(QRectF(x + w * 0.18, body_y, w * 0.54, 7), C("#14181c"))
        image(x + w * 0.18, body_y + 7, w * 0.54, body_h - 7 - 9)
        p.fillRect(QRectF(x + w * 0.18, y + h - 9, w * 0.54, 9), C("#14181c"))
        rows(x + w * 0.72, body_y, w * 0.28, body_h)
    elif kind == "mirror":
        rows(x, body_y, w * 0.28, body_h)
        p.fillRect(QRectF(x + w * 0.28, body_y, w * 0.54, 7), C("#14181c"))
        image(x + w * 0.28, body_y + 7, w * 0.54, body_h - 7 - 16)
        p.fillRect(QRectF(x + w * 0.28, y + h - 16, w * 0.54, 7), C(th["accent"], 0.25))
        p.fillRect(QRectF(x + w * 0.28, y + h - 9, w * 0.54, 9), C("#14181c"))
        p.fillRect(QRectF(x + w * 0.82, body_y, w * 0.18, body_h), panel)
        thumbs(x + w * 0.82, body_y + 2, w * 0.18, body_h)
    elif kind == "strip":
        p.fillRect(QRectF(x, body_y, w * 0.07, body_h), panel)
        for k in range(7):
            rrect(p, x + 2.5, body_y + 4 + k * 7, w * 0.07 - 5, 4, 1, fill="#3a434c")
        image(x + w * 0.07, body_y, w * 0.65, body_h - 30)
        p.fillRect(QRectF(x + w * 0.07, y + h - 30, w * 0.65, 8), C("#14181c"))
        p.fillRect(QRectF(x + w * 0.07, y + h - 22, w * 0.65, 22), panel)
        thumbs(x + w * 0.07, y + h - 22, w * 0.65, 22, horiz=True, n=7)
        rows(x + w * 0.72, body_y, w * 0.28, body_h)
    elif kind == "single":
        p.fillRect(QRectF(x, body_y, w, 8), C("#20262c"))
        for k in range(9):
            rrect(p, x + 4 + k * 13, body_y + 2.5, 9, 3, 1, fill="#3a434c")
        image(x, body_y + 8, w * 0.68, body_h - 8 - 24)
        p.fillRect(QRectF(x, y + h - 24, w * 0.68, 24), panel)
        thumbs(x, y + h - 24, w * 0.4, 24, horiz=True, n=3)
        rows(x + w * 0.68, body_y + 8, w * 0.25, body_h - 8)
        p.fillRect(QRectF(x + w * 0.93, body_y + 8, w * 0.07, body_h - 8), C("#0b0d0f"))
    p.restore()


def card(p, x, y, w, h, r=8):
    rrect(p, x, y, w, h, r, fill="#1b1f23", stroke="#262b30")


def setting_row(p, x, y, w, ico, title_s, desc, control=None, h=66):
    th = TH
    card(p, x, y, w, h)
    icon(p, ico, x + 20, y + h / 2 - 9, 18, th["text2"])
    text(p, title_s, x + 56, y + (11 if desc else 0), 13, 500, th["text"], w=w - 360, h=None if desc else h, va="t" if desc else "c")
    if desc:
        text(p, desc, x + 56, y + 31, 11.5, 400, th["text3"], w=w - 380, elide=True)
    if control:
        control(x + w - 20, y + h / 2)


def dropdown(p, xr, cy, label, w=200):
    th = TH
    x = xr - w
    rrect(p, x, cy - 16, w, 32, 6, fill="#23282d", stroke="#30363c")
    text(p, label, x + 12, cy - 16, 12.5, 500, th["text"], w=w - 40, h=32, va="c")
    icon(p, "l-chevron-down", x + w - 26, cy - 7, 14, th["text2"])


def render_o1():
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    th = TH
    bg = OUT / "A1-workstation-main.png"
    if bg.exists():
        p.drawImage(QRectF(0, 0, W, H), pil_to_qimage(Image.open(bg).convert("RGB")))
    p.fillRect(QRectF(0, 0, W, H), C("#000000", 0.58))
    dw, dh = 1200, 820
    dx, dy = (W - dw) / 2, (H - dh) / 2
    shadow(cv, dx, dy, dw, dh, 10, blur=40, dy=18, alpha=0.7)
    rrect(p, dx, dy, dw, dh, 9, fill="#15181b", stroke="#2c3238")
    # title bar
    logo(p, dx + 14, dy + 11, 18, light=True)
    text(p, "Настройки", dx + 44, dy, 12.5, 500, th["text"], w=200, h=40, va="c")
    icon(p, "l-x", dx + dw - 32, dy + 13, 14, th["text2"])
    icon(p, "l-minus", dx + dw - 78, dy + 13, 14, th["text2"])
    # nav
    nx, ny, nw = dx + 10, dy + 50, 286
    search_field(p, nx + 6, ny, nw - 12, 34, "Найти параметр", th, r=6, bg="#1d2125", border="#2a3036")
    y = ny + 50
    for i, (ico, lab) in enumerate(NAV):
        sel = i == 1
        if sel:
            rrect(p, nx, y, nw, 38, 6, fill="#262b30")
            rrect(p, nx + 1, y + 11, 3, 16, 1.5, fill=th["accent"])
        icon(p, ico, nx + 16, y + 11, 16, th["text"] if sel else th["text2"])
        text(p, lab, nx + 46, y, 13, 600 if sel else 400, th["text"] if sel else th["text2"], w=nw - 56, h=38, va="c")
        y += 41
    # content
    cx = dx + nw + 36
    cw = dx + dw - 28 - cx
    y = dy + 54
    text(p, "Внешний вид и компоновка", cx, y, 24, 600, th["text"])
    y += 52
    # layout picker card
    card(p, cx, y, cw, 270)
    icon(p, "l-layout-grid", cx + 20, y + 20, 18, th["text2"])
    text(p, "Компоновка главного окна", cx + 56, y + 16, 13, 500, th["text"])
    text(p, "Где находятся клипы, протоколы и кнопки инструментов. Меняется без перезапуска.", cx + 56, y + 36, 11.5, 400, th["text3"])
    tiles = [
        ("classic", "Классическая", "клипы слева"),
        ("mirror", "Зеркальная", "клипы справа"),
        ("strip", "Лента снизу", "клипы внизу"),
        ("single", "Одна панель", "всё справа, вкладками"),
    ]
    tw_ = (cw - 40 - 3 * 14) / 4
    th_ = tw_ * 0.62
    for i, (kind, name, sub) in enumerate(tiles):
        tx = cx + 20 + i * (tw_ + 14)
        ty = y + 70
        sel = i == 0
        if sel:
            rrect(p, tx - 6, ty - 6, tw_ + 12, th_ + 74, 10, fill=C(th["accent"], 0.08), stroke=C(th["accent"], 0.45))
        wire(p, tx, ty, tw_, th_, kind, sel=sel)
        ry = ty + th_ + 12
        circle(p, tx + 8, ry + 8, 8, stroke=th["accent"] if sel else th["text3"], sw=1.5)
        if sel:
            circle(p, tx + 8, ry + 8, 4, fill=th["accent"])
        text(p, name, tx + 24, ry - 1, 12.5, 600 if sel else 500, th["text"])
        text(p, sub, tx + 24, ry + 18, 11, 400, th["text3"], w=tw_ - 24, elide=True)
    y += 284
    rows = [
        ("l-contrast", "Тема", "Графит — нейтральная тёмная; светлая — для отчётов и печати", lambda xr, cy: dropdown(p, xr, cy, "Графит (тёмная)")),
        ("l-palette", "Акцентный цвет", "Цвет активного инструмента, контуров и выделения", None),
        ("l-ratio", "Плотность интерфейса", "Высота строк и отступы панелей", lambda xr, cy: dropdown(p, xr, cy, "Обычная")),
        ("l-type", "Подписи кнопок инструментов", "Иконки с подписями удобнее в начале, только иконки — компактнее", lambda xr, cy: dropdown(p, xr, cy, "Иконки и подписи", w=220)),
        ("l-scan", "Одиночный файл — в режиме «Фокус»", "Без панелей исследования: инструменты и кинопетля поверх снимка", lambda xr, cy: toggle(p, xr - 40, cy - 10, True, th, w=40, h=20)),
        ("l-keyboard", "Буквы клавиш на кнопках", "Маленькие L, A, C, V рядом с иконками инструментов", lambda xr, cy: toggle(p, xr - 40, cy - 10, True, th, w=40, h=20)),
    ]
    for ico, t, d, ctl in rows:
        setting_row(p, cx, y, cw, ico, t, d, ctl, h=56)
        if t == "Акцентный цвет":
            sx = cx + cw - 20
            for k, col in enumerate(reversed(ACCENTS)):
                sx -= 30
                circle(p, sx + 12, y + 28, 11, fill=col)
                if col == ACCENTS[0]:
                    circle(p, sx + 12, y + 28, 15, stroke="#ffffff", sw=1.6)
            text(p, "как в Windows", sx - 18 - tw("как в Windows", 11.5, 500), y, 11.5, 500, th["text3"], w=120, h=56, va="c")
        y += 60
    # footer
    fy = dy + dh - 56
    hline(p, dx + nw + 20, fy, dw - nw - 20, "#262b30")
    text(p, "Изменения применяются сразу", cx, fy, 11.5, 500, th["text3"], w=300, h=56, va="c")
    s = "Сбросить раздел"
    text(p, s, cx + 200, fy, 11.5, 600, th["accent_text"], w=200, h=56, va="c")
    button(p, dx + dw - 28 - 110, fy + 12, th, "Готово", None, "primary", h=32, w=110, weight=600)
    return cv.save(OUT2 / "O1-settings-appearance.png")


if __name__ == "__main__":
    print(render_o1())
