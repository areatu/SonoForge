"""E1 — window chrome per OS (applies to any of A–D) + the 00 overview sheet."""

from __future__ import annotations

from PIL import Image

from common import PT, THEME_A, C, QRectF, icon, rrect, text, tw, hline, circle
from kit import OUT, Canvas, pil_to_qimage, shadow, logo
import screen_a

S = 1.5
W = 1600


def _crop_png(name: str, y0: float, y1: float, x0: float = 0, x1: float = 1600):
    im = Image.open(OUT / name).convert("RGB")
    return im.crop((int(x0 * S), int(y0 * S), int(x1 * S), int(y1 * S)))


def _mac_style_on_windows_strip() -> Image.Image:
    th = THEME_A
    cv = Canvas(1600, 140, S, bg=th["bg0"])
    p = cv.p
    screen_a.title_bar(p, th, [("l-heart-pulse", PT["short"], PT["date"]), ("l-heart-pulse", "Сидоров А. П.", "07.10.2026")], chrome="mac")
    screen_a.patient_bar(p, th)
    cv.end()
    from kit import qimage_to_pil

    return qimage_to_pil(cv.img).convert("RGB")


def snap_flyout(p, cv, x, y):
    w, h = 268, 112
    shadow(cv, x, y, w, h, 8, blur=20, dy=8, alpha=0.6)
    rrect(p, x, y, w, h, 8, fill="#2b2b2b", stroke="#3f3f3f")
    layouts = [[(0, 0, 0.5, 1), (0.5, 0, 0.5, 1)], [(0, 0, 0.66, 1), (0.66, 0, 0.34, 1)], [(0, 0, 0.5, 1), (0.5, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)], [(0, 0, 0.25, 1), (0.25, 0, 0.5, 1), (0.75, 0, 0.25, 1)]]
    for i, lay in enumerate(layouts):
        lx = x + 12 + (i % 2) * 126
        ly = y + 12 + (i // 2) * 46
        for j, (a, b, c, d) in enumerate(lay):
            hl = i == 0 and j == 0
            rrect(p, lx + a * 118 + 1.5, ly + b * 40 + 1.5, c * 118 - 3, d * 40 - 3, 4, fill="#4cc2ff" if hl else "#3b3b3b", stroke="#555555" if not hl else None)


def render_e1():
    th = THEME_A
    H = 900
    cv = Canvas(W, H, S, bg="#0b0d0f")
    p = cv.p
    text(p, "Обвязка окна по ОС: одна раскладка — нативная рамка на каждой платформе", 32, 24, 20, 700, th["text"])
    text(p, "Относится к любому варианту A–D. Сравнение: нативная рамка на macOS и Windows против «Mac-стиля везде».", 32, 54, 12.5, 500, th["text2"])
    rows = [
        (
            "macOS 26 · нативно",
            "рекомендую",
            th["ok"],
            ("B1-mac-main-dark.png", 0, 150),
            [
                ("+", "меню в системной строке, сочетания ⌘, «Окно» и «Справка» от ОС"),
                ("+", "светофор, полноэкранный режим, тайлинг и Stage Manager — системные"),
                ("+", "Liquid Glass для панелей и тулбара даёт система (Qt 6.9+: ExpandedClientAreaHint, safeAreaMargins)"),
                ("−", "нужна отдельная проверка на macOS: подписи клавиш ⌘/⌥, Ctrl+Tab, тёмная/светлая тема"),
            ],
        ),
        (
            "Windows 11 · нативно",
            "рекомендую",
            th["ok"],
            ("A1-workstation-main.png", 0, 176),
            [
                ("+", "Snap Layouts при наведении на «развернуть», Win+стрелки, Aero Snap"),
                ("+", "кнопки окна там, где их ждут; вкладки исследований в заголовке экономят высоту"),
                ("+", "акцент и Mica берутся из системы; текущий SystemBar уже безрамочный"),
                ("−", "для Snap Layouts безрамочному окну нужна обработка WM_NCHITTEST (HTMAXBUTTON)"),
            ],
        ),
        (
            "«Mac-стиль везде» (здесь — на Windows)",
            "не рекомендую",
            th["err"],
            None,
            [
                ("−", "нет Snap Layouts; светофор слева непривычен пользователям Windows и Linux"),
                ("−", "на Windows нет системной строки меню — меню прячется в «≡»"),
                ("−", "нерабочие ожидания: двойной клик, Alt+пробел, жесты окна"),
                ("+", "один внешний вид для скриншотов и документации"),
            ],
        ),
    ]
    y = 92
    for title, verdict, vcol, src, notes in rows:
        tw_ = tw(title, 14, 700)
        text(p, title, 32, y, 14, 700, th["text"])
        vw = tw(verdict, 11, 700) + 18
        rrect(p, 32 + tw_ + 12, y + 1, vw, 20, 10, fill=C(vcol, 0.15), stroke=C(vcol, 0.5))
        text(p, verdict, 32 + tw_ + 12, y + 1, 11, 700, vcol, w=vw, h=20, align="c", va="c")
        y += 30
        if src:
            im = _crop_png(src[0], src[1], src[2])
        else:
            im = _mac_style_on_windows_strip().crop((0, 0, int(1600 * S), int(89 * S)))
        sh = im.height / S
        rrect(p, 31, y - 1, W - 62, sh * (W - 64) / 1600 + 2, 8, stroke=th["line2"])
        p.save()
        from kit import rr_path

        p.setClipPath(rr_path(32, y, W - 64, sh * (W - 64) / 1600, 8))
        p.drawImage(QRectF(32, y, W - 64, sh * (W - 64) / 1600), pil_to_qimage(im))
        p.restore()
        if title.startswith("Windows"):
            # hover state on the maximise button + Snap Layouts flyout
            k = (W - 64) / 1600
            bx = 32 + (1600 - 2 * 46) * k
            p.fillRect(QRectF(bx, y, 46 * k, 38 * k), C("#ffffff", 0.10))
            snap_flyout(p, cv, 32 + (1600 - 300) * k, y + 40 * k)
        y += sh * (W - 64) / 1600 + 12
        for i, (sign, s) in enumerate(notes):
            col = th["ok"] if sign == "+" else th["err"]
            nx = 32 + (i % 2) * 770
            ny = y + (i // 2) * 22
            circle(p, nx + 7, ny + 8, 7, fill=C(col, 0.16))
            text(p, sign, nx, ny - 1, 12, 700, col, w=14, h=18, align="c", va="c")
            text(p, s, nx + 22, ny, 12, 500, th["text2"], w=740, h=18, va="c", elide=True)
        y += 2 * 22 + 28
    text(p, "Linux: системные декорации (KDE/GNOME) или та же безрамочная схема Windows — без светофора.", 32, H - 34, 12, 500, th["text3"])
    return cv.save(OUT / "E1-window-chrome-by-os.png")


VARIANTS = [
    ("A", "Клиническая станция", "A1-workstation-main.png", "Три колонки, всё на виду: клипы — снимок — протоколы. Плотно, предсказуемо, одинаково на всех ОС. Ближе всего к текущему SonoForge."),
    ("B", "Mac Pro (нативный macOS)", "B1-mac-main-dark.png", "Системная строка меню, единый тулбар, «стеклянные» сайдбар и инспектор. Самый «родной» на Mac; на Windows — та же раскладка с нативной рамкой."),
    ("C", "Изображение в фокусе", "C1-focus-main.png", "Снимок на весь экран, панели плавают и скрываются. Максимум пикселей для изображения, всё остальное — через Ctrl K и горячие клавиши."),
    ("D", "Протокол → отчёт", "D1-workflow-measure.png", "Работа по шагам: план исследования слева, справа живой отчёт, который заполняется измерениями. Минимум пропусков, быстрый отчёт."),
]


def render_overview():
    th = THEME_A
    Wc, Hc = 1600, 1236
    cv = Canvas(Wc, Hc, S, bg="#0b0d0f")
    p = cv.p
    logo(p, 32, 24, 30, light=True)
    text(p, "SonoForge · варианты главного окна", 74, 22, 22, 700, th["text"])
    text(p, "Одно и то же исследование и шаг «Симпсон бипланово» (КСО · 4-кам.) в четырёх концепциях. Доп. экраны: A2, B2, C2, D2, E1.", 74, 52, 12.5, 500, th["text2"])
    tw_, th_ = 752, 470
    for i, (letter, name, fn, desc) in enumerate(VARIANTS):
        x = 32 + (i % 2) * (tw_ + 32)
        y = 92 + (i // 2) * (th_ + 66 + 30)
        im = Image.open(OUT / fn).convert("RGB")
        shadow(cv, x, y, tw_, th_, 10, blur=24, dy=8, alpha=0.6)
        p.save()
        from kit import rr_path

        p.setClipPath(rr_path(x, y, tw_, th_, 10))
        p.drawImage(QRectF(x, y, tw_, th_), pil_to_qimage(im.resize((int(tw_ * S), int(th_ * S)), Image.LANCZOS)))
        p.restore()
        rrect(p, x, y, tw_, th_, 10, stroke=C("#ffffff", 0.12))
        rrect(p, x, y + th_ + 12, 30, 30, 8, fill=th["accent"])
        text(p, letter, x, y + th_ + 12, 16, 700, th["on_accent"], w=30, h=30, align="c", va="c")
        text(p, name, x + 42, y + th_ + 12, 15, 700, th["text"])
        text(p, desc, x + 42, y + th_ + 33, 11.5, 500, th["text2"], w=tw_ - 50, wrap=True, lh=16)
    return cv.save(OUT / "00-overview.png")


if __name__ == "__main__":
    print(render_e1())
    print(render_overview())
