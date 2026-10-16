"""Round 2 · K1 «где ставить кнопки» (crops of the other screens) and the 00-overview sheet."""

from __future__ import annotations

from common import C, QRectF, hline, icon, kbd, pill, rrect, text, tw, vline
from kit import OUT, Canvas, Image, logo, pil_to_qimage, rr_path, shadow
from lay_common import OUT2, TH, S

GOOD, BAD = "+", "−"


def crop_q(path, box):
    """box in canvas units (the PNGs are rendered at scale S)."""
    im = Image.open(path).convert("RGB")
    x0, y0, x1, y1 = (round(v * S) for v in box)
    return im.crop((x0, y0, x1, y1))


def place(cv, im, x, y, w, h, r=8, bg="#07090a"):
    """Fit (contain) a PIL image into a rounded box."""
    p = cv.p
    rrect(p, x, y, w, h, r, fill=bg)
    iw, ih = im.size
    k = min(w / (iw / S), h / (ih / S))
    dw, dh = iw / S * k, ih / S * k
    dx, dy = x + (w - dw) / 2, y + (h - dh) / 2
    p.save()
    p.setClipPath(rr_path(x, y, w, h, r))
    p.drawImage(QRectF(dx, dy, dw, dh), pil_to_qimage(im.resize((max(1, int(dw * S)), max(1, int(dh * S))), Image.LANCZOS)))
    p.restore()
    rrect(p, x, y, w, h, r, stroke=C("#ffffff", 0.10))
    return dx, dy, k


def option_card(cv, x, y, w, letter, title_s, chip, chip_kind, img, bullets, img_h=176, custom=None):
    p = cv.p
    th = TH
    h = img_h + 58 + 18 * 3 + 18
    rec = chip_kind == "rec"
    rrect(p, x, y, w, h, 12, fill="#111417", stroke=C(th["accent"], 0.55) if rec else th["line"])
    rrect(p, x + 14, y + 14, 24, 24, 7, fill=th["accent"] if rec else th["bg3"])
    text(p, letter, x + 14, y + 14, 12.5, 700, th["on_accent"] if rec else th["text"], w=24, h=24, align="c", va="c")
    cw = 0
    if chip:
        fg = {"rec": th["accent_text"], "alt": th["text2"], "focus": "#b48cff"}[chip_kind]
        bgc = {"rec": C(th["accent"], 0.14), "alt": th["bg3"], "focus": C("#b48cff", 0.14)}[chip_kind]
        cw = pill(p, 0, -100, chip, fg, bgc, h=20, size=10.5)
        pill(p, x + w - 14 - cw, y + 16, chip, fg, bgc, h=20, size=10.5)
    text(p, title_s, x + 48, y + 14, 13, 600, th["text"], w=w - 48 - 14 - cw - 8, h=24, va="c", elide=True)
    iy = y + 50
    if img is not None:
        place(cv, img, x + 14, iy, w - 28, img_h)
    if custom:
        custom(cv, x + 14, iy, w - 28, img_h)
    by = iy + img_h + 12
    for sign, s in bullets:
        col = th["ok"] if sign == GOOD else th["warn"]
        text(p, sign, x + 16, by, 12.5, 700, col, w=12, h=17, va="c")
        text(p, s, x + 32, by, 11.5, 500, th["text2"], w=w - 46, h=17, va="c", elide=True)
        by += 18
    return h


def menu_mock(cv, x, y, w, h):
    """Option «≡ menu + Ctrl K, only «Отчёт» visible»."""
    p = cv.p
    th = TH
    rrect(p, x, y, w, h, 8, fill="#07090a")
    p.save()
    p.setClipPath(rr_path(x, y, w, h, 8))
    p.fillRect(QRectF(x, y, w, 34), C(th["bg0"]))
    rrect(p, x + 8, y + 5, 26, 24, 6, fill=th["bg3"])
    for k in range(3):
        rrect(p, x + 14, y + 11 + k * 5, 14, 1.8, 0.9, fill=th["text"])
    rrect(p, x + 42, y + 6, 132, 22, 6, fill=th["bg2"], stroke=th["line"])
    text(p, "Петрова М. И.", x + 52, y + 6, 11, 600, th["text"], w=110, h=22, va="c")
    rrect(p, x + w - 168, y + 7, 92, 20, 5, fill=th["bg2"], stroke=th["line"])
    icon(p, "l-search", x + w - 162, y + 11, 12, th["text3"])
    kbd(p, x + w - 122, y + 10, "Ctrl K", th)
    rrect(p, x + w - 70, y + 5, 62, 24, 6, fill=th["accent"])
    text(p, "Отчёт", x + w - 70, y + 5, 11.5, 700, th["on_accent"], w=62, h=24, align="c", va="c")
    p.fillRect(QRectF(x, y + 34, w, h - 34), C("#000000"))
    mx, my, mw = x + 8, y + 32, 196
    items = [
        ("l-folder-open", "Открыть…", "Ctrl O"),
        ("l-cloud-download", "Загрузить из PACS", ""),
        ("l-columns-2", "Сравнить", "Ctrl D"),
        ("l-presentation", "Презентация", "F5"),
        (None, "", ""),
        ("l-settings", "Настройки", "Ctrl ,"),
    ]
    mh = 8 + sum(9 if i[0] is None else 26 for i in items)
    shadow(cv, mx, my, mw, mh, 8, blur=14, dy=6, alpha=0.6)
    rrect(p, mx, my, mw, mh, 8, fill=th["bg2"], stroke=th["line2"])
    yy = my + 4
    for ico, lab, k in items:
        if ico is None:
            hline(p, mx + 8, yy + 4, mw - 16, th["line2"])
            yy += 9
            continue
        if lab == "Сравнить":
            rrect(p, mx + 4, yy, mw - 8, 26, 5, fill=th["bg3"])
        icon(p, ico, mx + 12, yy + 6, 14, th["text2"])
        text(p, lab, mx + 34, yy, 11.5, 500, th["text"], w=120, h=26, va="c")
        if k:
            text(p, k, mx + mw - 12 - tw(k, 10, 500), yy, 10, 500, th["text3"], w=60, h=26, va="c")
        yy += 26
    p.restore()
    rrect(p, x, y, w, h, 8, stroke=C("#ffffff", 0.10))


def near_contour_mock(cv, x, y, w, h):
    """Option «mini toolbar next to the contour» on top of a crop of F1."""
    p = cv.p
    th = TH
    im = crop_q(OUT2 / "F1-focus-single-file.png", (640, 130, 1000, 470))
    dx, dy, k = place(cv, im, x, y, w, h)
    # contour base in F1 ≈ (760..950, 388) → map into the crop
    bx = dx + (735 - 640) * k
    by = dy + (395 - 130) * k
    tw_ = 214
    rrect(p, bx, by, tw_, 30, 15, fill=C("#14171b", 0.94), stroke=C("#ffffff", 0.14))
    rrect(p, bx + 3, by + 3, 84, 24, 12, fill=th["accent"])
    icon(p, "l-check", bx + 12, by + 8, 13, th["on_accent"], sw=2.6)
    text(p, "Готово", bx + 30, by + 3, 11.5, 700, th["on_accent"], w=60, h=24, va="c")
    icon(p, "l-undo-2", bx + 98, by + 8, 14, th["text"])
    vline(p, bx + 122, by + 8, 14, C("#ffffff", 0.16))
    text(p, "Пропустить", bx + 130, by, 11.5, 500, th["text2"], w=80, h=30, va="c")


def render_k1():
    th = TH
    Wc, Hc = 1600, 1176
    cv = Canvas(Wc, Hc, S, bg="#0b0d0f")
    p = cv.p
    logo(p, 32, 24, 30, light=True)
    text(p, "Где ставить кнопки · сравнение размещений", 74, 22, 22, 700, th["text"])
    text(p, "Фрагменты взяты из макетов этого набора. Бирюзовая рамка — что я бы взял за основу; остальное можно оставить выбором в настройках.", 74, 52, 12.5, 500, th["text2"])
    M = lambda n: OUT2 / n  # noqa: E731
    A1 = OUT / "A1-workstation-main.png"
    sections = [
        (
            "Инструменты измерения",
            [
                (
                    "A",
                    "Ряд над изображением",
                    "рекомендую",
                    "rec",
                    crop_q(A1, (216, 88, 736, 355)),
                    [(GOOD, "привычно по DICOM-просмотрщикам"), (GOOD, "буквы клавиш видны на кнопках"), (BAD, "занимает 42 px высоты")],
                    None,
                ),
                (
                    "B",
                    "Вертикальная панель с подписями",
                    "M2",
                    "alt",
                    crop_q(M("M2-main-filmstrip.png"), (0, 80, 440, 306)),
                    [(GOOD, "подписи понятны с первого дня"), (GOOD, "не отнимает высоту у кадра"), (BAD, "+70 px по ширине")],
                    None,
                ),
                (
                    "C",
                    "Командная строка Windows 11",
                    "M3",
                    "alt",
                    crop_q(M("M3-main-commandbar.png"), (0, 38, 560, 325)),
                    [(GOOD, "файл, измерения и отчёт в одном ряду"), (GOOD, "знакомо по приложениям Windows 11"), (BAD, "на экране 1366 px не поместится")],
                    None,
                ),
                (
                    "D",
                    "Нижняя панель с кинопетлёй",
                    "для «Фокуса»",
                    "focus",
                    crop_q(M("F2-focus-bottom-dock.png"), (140, 680, 760, 1000)),
                    [(GOOD, "верх снимка полностью свободен"), (GOOD, "инструменты и кадр — одним взглядом"), (BAD, "мало места для подписей")],
                    None,
                ),
            ],
        ),
        (
            "Действия исследования: Открыть, PACS, Сравнить, Презентация, Отчёт",
            [
                (
                    "A",
                    "Справа в строке пациента",
                    "рекомендую",
                    "rec",
                    crop_q(A1, (1010, 0, 1600, 302)),
                    [(GOOD, "«Отчёт» всегда на виду"), (GOOD, "не смешиваются с инструментами"), (BAD, "строка пациента выше — 50 px")],
                    None,
                ),
                (
                    "B",
                    "В командной строке",
                    "M3",
                    "alt",
                    crop_q(M("M3-main-commandbar.png"), (1010, 0, 1600, 302)),
                    [(GOOD, "все команды в одном ряду"), (BAD, "«Отчёт» теряется среди инструментов"), (BAD, "длинная строка")],
                    None,
                ),
                (
                    "C",
                    "Меню ≡ и Ctrl K",
                    "компактно",
                    "alt",
                    None,
                    [(GOOD, "на виду только «Отчёт», остальное в меню"), (GOOD, "всё ищется через Ctrl K"), (BAD, "редкие действия — на клик дальше")],
                    menu_mock,
                ),
            ],
        ),
        (
            "Шаг протокола: Готово · Пропустить · Отменить точку",
            [
                (
                    "A",
                    "Баннер над снимком",
                    "A1",
                    "alt",
                    crop_q(A1, (330, 110, 900, 402)),
                    [(GOOD, "заметен, подсказки клавиш рядом"), (BAD, "закрывает верх области снимка"), (BAD, "дублирует карточку протокола")],
                    None,
                ),
                (
                    "B",
                    "Полоса под снимком",
                    "рекомендую",
                    "rec",
                    crop_q(M("M1-main-mirrored.png"), (760, 654, 1384, 974)),
                    [(GOOD, "ничего не закрывает снимок"), (GOOD, "кнопки всегда на одном месте"), (BAD, "отнимает 58 px высоты")],
                    None,
                ),
                (
                    "C",
                    "Только в карточке протокола",
                    "A1",
                    "alt",
                    crop_q(A1, (1248, 196, 1600, 376)),
                    [(GOOD, "видны все шаги и результат"), (BAD, "взгляд уходит от снимка"), (BAD, "мелкие цели для мыши")],
                    None,
                ),
                (
                    "D",
                    "Мини-панель у контура",
                    "для «Фокуса»",
                    "focus",
                    None,
                    [(GOOD, "почти не нужно вести мышь"), (GOOD, "хорошо для одиночного файла"), (BAD, "может закрыть край контура")],
                    near_contour_mock,
                ),
            ],
        ),
    ]
    y = 92
    gap = 16
    for title_s, opts in sections:
        text(p, title_s, 32, y, 15, 700, th["text"])
        y += 30
        n = 4
        cw = (Wc - 64 - (n - 1) * gap) / n
        hmax = 0
        for i, (letter, name, chip, kind, img, bullets, custom) in enumerate(opts):
            hmax = max(hmax, option_card(cv, 32 + i * (cw + gap), y, cw, letter, name, chip, kind, img, bullets, custom=custom))
        if len(opts) == 3:
            x = 32 + 3 * (cw + gap)
            rrect(p, x, y, cw, hmax, 12, fill=None, stroke=th["line"])
            text(p, "Можно комбинировать: A в обычном окне, C — в компактном режиме или на маленьком экране.", x + 20, y + 20, 12, 500, th["text3"], w=cw - 40, wrap=True, lh=18)
        y += hmax + 26
    return cv.save(OUT2 / "K1-buttons-placement.png")


OVERVIEW = [
    ("A1", "База · раунд 1", "A1", "Клипы слева, инструменты над снимком, протоколы справа. С ней сравниваются вариации."),
    ("M1", "Зеркальная", "M1-main-mirrored.png", "Протоколы слева, клипы справа (как в EchoPAC); шаг протокола — полосой под снимком."),
    ("M2", "Лента снизу", "M2-main-filmstrip.png", "Инструменты — вертикальной панелью с подписями, клипы — лентой под кинопетлёй, строка пациента в одну линию."),
    ("M3", "Командная строка", "M3-main-commandbar.png", "Командная строка Windows 11 и одна боковая панель с вкладками; под снимком — «клипы для шага»."),
    ("F1", "Фокус · один файл", "F1-focus-single-file.png", "C1 для одиночного файла: заголовок Windows 11, инструменты слева, маленькая карточка измерений, кинопетля."),
    ("F2", "Фокус · одна панель", "F2-focus-bottom-dock.png", "Всё в одной нижней панели: инструменты, кинопетля, результаты. Верх снимка пустой."),
    ("R1", "Отчёт · вкладка справа", "R1-report-side-panel.png", "Живой отчёт во вкладке правой панели, внизу — заключение с подсказанными фразами."),
    ("R2", "Отчёт · рядом со снимком", "R2-report-split.png", "Снимок | лист A4 | фразы. Пустые значения — «измерить», переход к нужному клипу."),
    ("R3", "Отчёт · отдельный режим", "R3-report-full.png", "D2 в оформлении A: разделы и полнота, лист A4, фразы, экспорт; источник значения по наведению."),
    ("S1", "Справочник · окно", "S1-reference-window.png", "Темы слева, таблица норм с градациями и значениями пациентки, рисунок и «как измерять» справа."),
    ("S2", "Справочник · в контексте", "S2-reference-in-context.png", "Нормы прямо в списке измерений; по наведению — карточка с полосой градаций и схемой."),
    ("O1", "Настройки · Windows 11", "O1-settings-appearance.png", "«Внешний вид и компоновка»: выбор компоновки окна, тема, акцент, плотность, «Фокус» для файлов."),
]


def render_overview():
    th = TH
    Wc = 1600
    cols, gap = 4, 22
    tw_ = (Wc - 64 - (cols - 1) * gap) / cols
    th_ = tw_ * 0.625
    rows = (len(OVERVIEW) + cols - 1) // cols
    cap_h = 74
    Hc = int(96 + rows * (th_ + cap_h + 24) + 10)
    cv = Canvas(Wc, Hc, S, bg="#0b0d0f")
    p = cv.p
    logo(p, 32, 24, 30, light=True)
    text(p, "SonoForge · вариации компоновки (раунд 2)", 74, 22, 22, 700, th["text"])
    text(p, "Основа — A1/A2, графитовая палитра, заголовок окна Windows 11. Меняется только расположение панелей и кнопок. Отдельный лист K1 — где ставить кнопки.", 74, 52, 12.5, 500, th["text2"])
    for i, (code, name, fn, desc) in enumerate(OVERVIEW):
        x = 32 + (i % cols) * (tw_ + gap)
        y = 96 + (i // cols) * (th_ + cap_h + 24)
        src = OUT / "A1-workstation-main.png" if fn == "A1" else OUT2 / fn
        im = Image.open(src).convert("RGB")
        shadow(cv, x, y, tw_, th_, 8, blur=18, dy=6, alpha=0.55)
        p.save()
        p.setClipPath(rr_path(x, y, tw_, th_, 8))
        p.drawImage(QRectF(x, y, tw_, th_), pil_to_qimage(im.resize((int(tw_ * S), int(th_ * S)), Image.LANCZOS)))
        p.restore()
        rrect(p, x, y, tw_, th_, 8, stroke=C("#ffffff", 0.12))
        cy = y + th_ + 10
        cw = tw(code, 12, 700) + 14
        base = fn == "A1"
        rrect(p, x, cy, cw, 22, 6, fill=th["bg3"] if base else th["accent"])
        text(p, code, x, cy, 12, 700, th["text"] if base else th["on_accent"], w=cw, h=22, align="c", va="c")
        text(p, name, x + cw + 8, cy, 13, 700, th["text"], w=tw_ - cw - 8, h=22, va="c", elide=True)
        text(p, desc, x, cy + 28, 11, 500, th["text2"], w=tw_, wrap=True, lh=15)
    return cv.save(OUT2 / "00-overview.png")


if __name__ == "__main__":
    print(render_k1())
    print(render_overview())
