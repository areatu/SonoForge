"""Design-mockup toolkit (dev-only, not part of the app).

QPainter primitives, icons (Lucide / Phosphor / repo SVGs), real de-identified
echo frames from ``tests/fixtures/for_pero`` and synthetic Doppler / M-mode
imagery.  Everything is drawn in logical pixels; ``Canvas.s`` is the output
scale.

Run (sandbox):
    V=~/.cache/venv-mock
    LD_LIBRARY_PATH=$V/stubs QT_QPA_PLATFORM=offscreen $V/bin/python render_all.py
"""

from __future__ import annotations

import functools
import io
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FONTS = REPO / "src/echo_personal_tool/resources/fonts"
ICONS = HERE / "icons"
REPO_ICONS = REPO / "src/echo_personal_tool/resources/icons"
CLIPS = REPO / "tests/fixtures/for_pero"
LOGO_LIGHT = REPO / "src/echo_personal_tool/resources/logo_dark.png"  # white strokes
LOGO_DARK = REPO / "src/echo_personal_tool/resources/logo.png"  # black strokes
OUT = REPO / "docs/images/main-window-variants"

_app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
for _f in (
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Bold.ttf",
    "InterDisplay-Regular.ttf",
    "JetBrainsMono-Bold.ttf",
):
    QFontDatabase.addApplicationFont(str(FONTS / _f))


# Font metrics must be measured against a 72-dpi device (the canvases use
# 2835 dots/m) — the default screen DPI of the offscreen platform is 96.
_METRIC_DEVICE = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
_METRIC_DEVICE.setDotsPerMeterX(2835)
_METRIC_DEVICE.setDotsPerMeterY(2835)


def FM(f: QFont) -> QFontMetricsF:
    return QFontMetricsF(f, _METRIC_DEVICE)


# ───────────────────────────── colour / font ─────────────────────────────


def C(c, a: float | None = None) -> QColor:
    """'#rrggbb', '#rrggbbaa' (CSS order), tuple or QColor → QColor."""
    if isinstance(c, QColor):
        q = QColor(c)
    elif isinstance(c, tuple):
        q = QColor(*c)
    else:
        s = c.lstrip("#")
        if len(s) == 8:
            q = QColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
        else:
            q = QColor("#" + s)
    if a is not None:
        q.setAlphaF(max(0.0, min(1.0, a)))
    return q


def mix(c1, c2, t: float) -> QColor:
    a, b = C(c1), C(c2)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


@functools.lru_cache(maxsize=None)
def F(size: float, weight: int = 400, family: str = "Inter", tnum: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    if tnum:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except Exception:  # pragma: no cover - older Qt
            pass
    return f


def tw(s: str, size: float = 13, weight: int = 400, family: str = "Inter", tnum: bool = False, spacing: float = 0.0) -> float:
    return FM(F(size, weight, family, tnum, spacing)).horizontalAdvance(s)


def text(
    p: QPainter,
    s: str,
    x: float,
    y: float,
    size: float = 13,
    weight: int = 400,
    color="#ffffff",
    *,
    w: float | None = None,
    h: float | None = None,
    align: str = "l",
    va: str = "t",
    family: str = "Inter",
    tnum: bool = False,
    spacing: float = 0.0,
    elide: bool = False,
    wrap: bool = False,
    alpha: float | None = None,
    lh: float | None = None,
) -> float:
    """Draw text.  Without ``w``: (x, y) is the anchor (va t/c/b = top/centre/baseline).

    With ``w``: draws into the box (x, y, w, h) with alignment, optional elide/wrap.
    Returns the advance width of the drawn string.
    """
    f = F(size, weight, family, tnum, spacing)
    p.setFont(f)
    p.setPen(C(color, alpha))
    fm = FM(f)
    if w is None:
        adv = fm.horizontalAdvance(s)
        if align == "c":
            x -= adv / 2
        elif align == "r":
            x -= adv
        if va == "t":
            by = y + fm.ascent()
        elif va == "c":
            by = y + (fm.ascent() - fm.descent()) / 2
        else:
            by = y
        p.drawText(QPointF(x, by), s)
        return adv
    if wrap and lh:
        # manual wrap with custom line height
        words = s.split(" ")
        lines: list[str] = []
        cur = ""
        for word in words:
            trial = (cur + " " + word).strip()
            if fm.horizontalAdvance(trial) <= w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        for i, ln in enumerate(lines):
            lx = x
            adv = fm.horizontalAdvance(ln)
            if align == "c":
                lx = x + (w - adv) / 2
            elif align == "r":
                lx = x + w - adv
            p.drawText(QPointF(lx, y + fm.ascent() + i * lh), ln)
        return float(len(lines))
    hh = h if h is not None else fm.height()
    flags = {"l": Qt.AlignmentFlag.AlignLeft, "c": Qt.AlignmentFlag.AlignHCenter, "r": Qt.AlignmentFlag.AlignRight}[align]
    flags |= {"t": Qt.AlignmentFlag.AlignTop, "c": Qt.AlignmentFlag.AlignVCenter, "b": Qt.AlignmentFlag.AlignBottom}[va]
    if wrap:
        flags |= Qt.TextFlag.TextWordWrap
    elif elide:
        s = fm.elidedText(s, Qt.TextElideMode.ElideRight, w)
    p.drawText(QRectF(x, y, w, hh), int(flags.value if hasattr(flags, "value") else flags), s)
    return fm.horizontalAdvance(s)


def rich(p: QPainter, parts, x: float, y: float, va: str = "t") -> float:
    """Draw a run of (text, size, weight, color[, family]) parts on one line; returns end x."""
    for part in parts:
        s, size, weight, color = part[:4]
        family = part[4] if len(part) > 4 else "Inter"
        x += text(p, s, x, y, size, weight, color, va=va, family=family)
    return x


# ───────────────────────────── canvas / shapes ─────────────────────────────


class Canvas:
    def __init__(self, w: int, h: int, scale: float = 1.5, bg="#000000"):
        self.w, self.h, self.s = w, h, scale
        self.img = QImage(int(round(w * scale)), int(round(h * scale)), QImage.Format.Format_ARGB32_Premultiplied)
        self.img.setDotsPerMeterX(2835)
        self.img.setDotsPerMeterY(2835)
        if bg is None:
            self.img.fill(Qt.GlobalColor.transparent)
        else:
            self.img.fill(C(bg))
        self.p: QPainter | None = None
        self._painter: QPainter | None = None
        self.begin()

    def begin(self) -> QPainter:
        # Reuse one QPainter object so callers can keep their ``p`` reference
        # across glass()/pil() round-trips that temporarily end painting.
        if getattr(self, "_painter", None) is None:
            self._painter = QPainter()
        self._painter.begin(self.img)
        self.p = self._painter
        self.p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.p.scale(self.s, self.s)
        return self.p

    def end(self) -> None:
        if self.p is not None and self.p.isActive():
            self.p.end()

    def save(self, path: Path | str) -> Path:
        self.end()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pil = qimage_to_pil(self.img).convert("RGB")
        pil.save(path, optimize=True)
        return path

    def pil(self) -> Image.Image:
        self.end()
        out = qimage_to_pil(self.img)
        self.begin()
        return out


def pil_to_qimage(im: Image.Image) -> QImage:
    if im.mode == "L":
        data = im.tobytes()
        return QImage(data, im.width, im.height, im.width, QImage.Format.Format_Grayscale8).copy()
    if im.mode == "RGB":
        data = im.tobytes()
        return QImage(data, im.width, im.height, im.width * 3, QImage.Format.Format_RGB888).copy()
    im = im.convert("RGBA")
    data = im.tobytes()
    return QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()


def qimage_to_pil(q: QImage) -> Image.Image:
    q = q.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, bpl = q.width(), q.height(), q.bytesPerLine()
    arr = np.frombuffer(q.constBits(), np.uint8, count=q.sizeInBytes()).reshape(h, bpl)[:, : w * 4]
    return Image.fromarray(arr.reshape(h, w, 4).copy(), "RGBA")


def _brush(fill, alpha=None):
    if isinstance(fill, (QLinearGradient, QRadialGradient)):
        return QBrush(fill)
    if isinstance(fill, QBrush):
        return fill
    return QBrush(C(fill, alpha))


def rr_path(x, y, w, h, r) -> QPainterPath:
    path = QPainterPath()
    if r:
        path.addRoundedRect(QRectF(x, y, w, h), r, r)
    else:
        path.addRect(QRectF(x, y, w, h))
    return path


def rrect(p: QPainter, x, y, w, h, r=0.0, fill=None, stroke=None, sw: float = 1.0, alpha=None, salpha=None):
    path = rr_path(x, y, w, h, r)
    if fill is not None:
        p.fillPath(path, _brush(fill, alpha))
    if stroke is not None:
        i = sw / 2
        path2 = rr_path(x + i, y + i, w - sw, h - sw, max(0.0, r - i))
        pen = QPen(C(stroke, salpha), sw)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path2)
    return path


def line(p: QPainter, x1, y1, x2, y2, color, w: float = 1.0, dash=None, alpha=None, cap=Qt.PenCapStyle.RoundCap):
    pen = QPen(C(color, alpha), w)
    pen.setCapStyle(cap)
    if dash:
        pen.setDashPattern(dash)
    p.setPen(pen)
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def hline(p, x, y, w, color, alpha=None, t=1.0):
    p.fillRect(QRectF(x, y, w, t), C(color, alpha))


def vline(p, x, y, h, color, alpha=None, t=1.0):
    p.fillRect(QRectF(x, y, t, h), C(color, alpha))


def circle(p: QPainter, cx, cy, r, fill=None, stroke=None, sw=1.0, alpha=None):
    p.setPen(QPen(C(stroke), sw) if stroke is not None else Qt.PenStyle.NoPen)
    p.setBrush(_brush(fill, alpha) if fill is not None else Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)


def vgrad(y1, y2, stops):
    g = QLinearGradient(0, y1, 0, y2)
    for t, c in stops:
        g.setColorAt(t, C(c) if not isinstance(c, QColor) else c)
    return g


def hgrad(x1, x2, stops):
    g = QLinearGradient(x1, 0, x2, 0)
    for t, c in stops:
        g.setColorAt(t, C(c) if not isinstance(c, QColor) else c)
    return g


def shadow(cv: Canvas, x, y, w, h, r=10.0, blur=24.0, dy=10.0, dx=0.0, color=(0, 0, 0), alpha=0.45, spread=0.0):
    s = cv.s
    pad = blur * 1.6 + spread + 4
    W = int(math.ceil((w + 2 * pad) * s))
    H = int(math.ceil((h + 2 * pad) * s))
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    x0 = (pad - spread) * s
    y0 = (pad - spread) * s
    d.rounded_rectangle(
        [x0, y0, x0 + (w + 2 * spread) * s, y0 + (h + 2 * spread) * s],
        radius=max(0.0, (r + spread) * s),
        fill=int(255 * alpha),
    )
    if blur > 0:
        m = m.filter(ImageFilter.GaussianBlur(blur * s / 2))
    rgba = Image.new("RGBA", (W, H), tuple(color) + (0,))
    rgba.putalpha(m)
    cv.p.drawImage(QRectF(x - pad + dx, y - pad + dy, W / s, H / s), pil_to_qimage(rgba))


def glass(cv: Canvas, x, y, w, h, r=14.0, blur=22.0, tint="#15171b", tint_a=0.62, border="#ffffff", border_a=0.09, sheen=True):
    """Frosted panel: blur what is already painted under the rect, tint, hairline border.

    Reads the backing QImage while the raster painter stays active (drawing is
    synchronous), so the caller's painter state (clips, saves) is preserved.
    """
    s = cv.s
    p = cv.p
    pad = blur
    rx = max(0, int((x - pad) * s))
    ry = max(0, int((y - pad) * s))
    rw = min(cv.img.width() - rx, int((w + 2 * pad) * s))
    rh = min(cv.img.height() - ry, int((h + 2 * pad) * s))
    sub = qimage_to_pil(cv.img.copy(rx, ry, rw, rh)).filter(ImageFilter.GaussianBlur(blur * s / 2))
    q = pil_to_qimage(sub)
    path = rr_path(x, y, w, h, r)
    p.save()
    p.setClipPath(path, Qt.ClipOperation.IntersectClip)
    p.drawImage(QRectF(rx / s, ry / s, rw / s, rh / s), q)
    p.fillPath(path, C(tint, tint_a))
    if sheen:
        p.fillPath(path, QBrush(vgrad(y, y + h, [(0, C("#ffffff", 0.07)), (0.35, C("#ffffff", 0.02)), (1, C("#ffffff", 0.0))])))
    p.restore()
    if border_a:
        rrect(p, x, y, w, h, r, stroke=border, salpha=border_a, sw=1.0)


# ───────────────────────────── icons ─────────────────────────────


@functools.lru_cache(maxsize=None)
def _svg_src(name: str) -> str:
    if name.startswith("r-"):
        return (REPO_ICONS / f"{name[2:]}.svg").read_text(encoding="utf-8")
    return (ICONS / f"{name}.svg").read_text(encoding="utf-8")


@functools.lru_cache(maxsize=None)
def _svg_renderer(name: str, hexc: str, sw: float | None) -> QSvgRenderer:
    svg = _svg_src(name).replace("currentColor", hexc)
    if sw is not None:
        svg = svg.replace('stroke-width="2"', f'stroke-width="{sw}"')
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    r.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
    return r


def icon(p: QPainter, name: str, x, y, size=16.0, color="#ffffff", sw: float | None = None, alpha: float | None = None):
    """Icon names: 'l-<lucide>', 'p-<phosphor>[-fill]', 'r-<repo icon>'."""
    col = C(color, alpha)
    if name.startswith("l-") and sw is None:
        sw = 1.75
    r = _svg_renderer(name, col.name(QColor.NameFormat.HexRgb), sw)
    p.save()
    if col.alphaF() < 0.999:
        p.setOpacity(p.opacity() * col.alphaF())
    r.render(p, QRectF(x, y, size, size))
    p.restore()


@functools.lru_cache(maxsize=None)
def _logo(light: bool) -> QImage:
    """SF heart logo as an alpha mask coloured white (light) or black."""
    im = Image.open(LOGO_DARK).convert("RGBA")
    alpha = im.getchannel("A")
    rgb = Image.new("RGB", im.size, (255, 255, 255) if light else (0, 0, 0))
    rgb.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox:
        rgb = rgb.crop(bbox)
    return pil_to_qimage(rgb)


def logo(p: QPainter, x, y, h, light=True, color: str | None = None):
    q = _logo(light)
    w = h * q.width() / q.height()
    if color is not None:
        tinted = QImage(q.size(), QImage.Format.Format_ARGB32_Premultiplied)
        tinted.fill(Qt.GlobalColor.transparent)
        tp = QPainter(tinted)
        tp.drawImage(0, 0, q)
        tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        tp.fillRect(tinted.rect(), C(color))
        tp.end()
        q = tinted
    p.drawImage(QRectF(x, y, w, h), q)
    return w


# ───────────────────────────── echo imagery ─────────────────────────────


@functools.lru_cache(maxsize=None)
def _clip(name: str):
    z = np.load(CLIPS / f"{name}.npz", allow_pickle=True)
    return z["frames_jpeg"]


def nframes(name: str) -> int:
    return len(_clip(name))


@functools.lru_cache(maxsize=None)
def frame(name: str, idx: int = 0) -> Image.Image:
    fj = _clip(name)
    b = fj[idx % len(fj)]
    if isinstance(b, np.ndarray):
        b = b.tobytes()
    return Image.open(io.BytesIO(b)).convert("L")


# Sector crop boxes (x0, y0, x1, y1) in source pixels — tight around the fan.
SECTOR = {
    "gold1": (262, 88, 1018, 800),
    "gold2": (262, 88, 1018, 800),
    "gold3": (262, 88, 1018, 800),
    "gold4": (262, 88, 1018, 800),
    "gold5": (262, 88, 1018, 800),
    "gold6": (262, 88, 1018, 800),
    "gold7+ECG": (262, 88, 1018, 790),
    "gold8+ECG": (262, 88, 1018, 790),
    "gold_Ph_ECG1": (100, 40, 720, 580),
    "gold_Ph_ECG2": (100, 40, 720, 580),
}


@functools.lru_cache(maxsize=None)
def _fan_mask(name: str) -> np.ndarray | None:
    """Binary mask of the scan fan (removes burned-in rulers, ECG and the vendor marker)."""
    if not name.startswith("gold") or name.startswith("gold_Ph"):
        return None
    n = nframes(name)
    acc = None
    for k in range(0, n, max(1, n // 12)):
        a = np.asarray(frame(name, k).crop(SECTOR[name]), np.float32)
        acc = a if acc is None else np.maximum(acc, a)
    H, W = acc.shape
    rows = np.arange(100, 401, 25)
    left, right = [], []
    for r in rows:
        nz = np.where(acc[r] > 18)[0]
        left.append(nz.min())
        right.append(nz.max())
    bl, al = np.polyfit(rows, left, 1)
    br, ar = np.polyfit(rows, right, 1)
    ya = (ar - al) / (bl - br)
    xa = al + bl * ya
    th_l = math.atan(-bl) + math.radians(0.6)
    th_r = math.atan(br) + math.radians(0.6)
    col = acc[:, int(round(xa))]
    R = np.where(col > 18)[0].max() - ya + 2
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx, dy = xx - xa, yy - ya
    ang = np.arctan2(dx, dy)
    rr = np.sqrt(dx * dx + dy * dy)
    mask = (dy > 0) & (ang >= -th_l) & (ang <= th_r) & (rr <= R)
    mask[: int(ya + 16), int(xa - 16): int(xa + 17)] = False  # vendor "S" marker at the apex
    return mask.astype(np.float32)


@functools.lru_cache(maxsize=None)
def sector(name: str, idx: int = 0, gamma: float = 1.0) -> Image.Image:
    im = frame(name, idx).crop(SECTOR[name])
    m = _fan_mask(name)
    if m is not None:
        im = Image.fromarray((np.asarray(im, np.float32) * m).astype(np.uint8), "L")
    if gamma != 1.0:
        lut = [int(255 * (i / 255) ** gamma) for i in range(256)]
        im = im.point(lut)
    return im


def qsector(name: str, idx: int = 0, gamma: float = 1.0) -> QImage:
    return pil_to_qimage(sector(name, idx, gamma))


def draw_image_fit(p: QPainter, q: QImage, x, y, w, h, mode="contain", align="c") -> QRectF:
    """Draw ``q`` into the box; returns the target rect used."""
    iw, ih = q.width(), q.height()
    if mode == "contain":
        k = min(w / iw, h / ih)
    else:
        k = max(w / iw, h / ih)
    tw_, th_ = iw * k, ih * k
    tx = x + (w - tw_) / 2
    ty = y + (h - th_) / 2 if align == "c" else y
    target = QRectF(tx, ty, tw_, th_)
    if mode == "cover":
        p.save()
        p.setClipRect(QRectF(x, y, w, h))
        p.drawImage(target, q)
        p.restore()
    else:
        p.drawImage(target, q)
    return target


def _bump(ph, t0, tp, t1, peak, fall="cos"):
    out = np.zeros_like(ph)
    up = (ph >= t0) & (ph < tp)
    out[up] = peak * np.sin(0.5 * np.pi * (ph[up] - t0) / (tp - t0))
    dn = (ph >= tp) & (ph <= t1)
    x = (ph[dn] - tp) / (t1 - tp)
    if fall == "lin":
        out[dn] = peak * (1 - x) ** 1.1
    else:
        out[dn] = peak * np.cos(0.5 * np.pi * x)
    return out


def doppler_envelope(t: np.ndarray, kind: str, hr: float = 68.0) -> np.ndarray:
    period = 60.0 / hr
    ph = np.mod(t, period)
    if kind == "pw_mv":  # m/s, positive (towards probe)
        return _bump(ph, 0.40, 0.48, 0.66, 0.78, "lin") + _bump(ph, 0.71, 0.79, 0.87, 0.64)
    if kind == "cw_av":  # negative, systolic
        return -_bump(ph, 0.07, 0.17, 0.37, 1.42)
    if kind == "cw_tr":  # negative, holosystolic
        x = np.clip((ph - 0.05) / 0.40, 0, 1)
        env = np.where((ph > 0.05) & (ph < 0.45), np.sin(np.pi * x) ** 0.35, 0.0)
        return -2.42 * env
    if kind == "tdi":  # cm/s, s' positive, e'/a' negative
        return _bump(ph, 0.08, 0.15, 0.32, 9.0) - _bump(ph, 0.42, 0.48, 0.58, 8.0) - _bump(ph, 0.74, 0.79, 0.86, 10.0)
    if kind == "pw_lvot":
        return -_bump(ph, 0.07, 0.15, 0.35, 0.98)
    raise ValueError(kind)


DOPPLER_SCALE = {  # (v_top, v_bottom)
    "pw_mv": (1.2, -0.4),
    "cw_av": (1.0, -2.5),
    "cw_tr": (1.0, -3.5),
    "tdi": (16.0, -16.0),
    "pw_lvot": (0.6, -1.4),
}


@functools.lru_cache(maxsize=None)
def doppler_image(kind: str, width: int = 900, height: int = 360, px_per_s: float = 170.0, seed: int = 3, hr: float = 68.0) -> Image.Image:
    """Synthetic spectral Doppler (grayscale) — plausible look, not physics."""
    rng = np.random.default_rng(seed)
    t = np.arange(width) / px_per_s
    env = doppler_envelope(t, kind, hr)
    # beat-to-beat variation + smoothing (rounded peaks)
    period = 60.0 / hr
    beat = np.floor(t / period).astype(int)
    gain = 1 + 0.04 * np.sin(beat * 2.1 + seed)
    env = env * gain
    k = max(1, int(0.018 * px_per_s))
    ker = np.hanning(2 * k + 1)
    ker /= ker.sum()
    env = np.convolve(env, ker, mode="same")
    vtop, vbot = DOPPLER_SCALE[kind]
    span = abs(vtop - vbot)
    v = np.linspace(vtop, vbot, height)[:, None]
    e = env[None, :]
    ae, av = np.abs(e), np.abs(v)
    same = (np.sign(v) == np.sign(e)) & (ae > 0.015 * span)
    gap = ae - av  # >0 inside the envelope
    if kind.startswith("cw"):
        core = 0.30 + 0.70 * np.exp(-((gap) / (0.22 * ae + 1e-6)) ** 2)
    elif kind == "tdi":
        core = 0.45 + 0.55 * np.exp(-((gap) / (0.35 * ae + 1e-6)) ** 2)
    else:
        core = 0.10 + 0.90 * np.exp(-((gap) / (0.16 * ae + 1e-6)) ** 2)
    edge = 0.010 * span
    soft = np.where(gap >= 0, 1.0, np.exp(-((gap) / edge) ** 2))
    inten = np.where(same, core * soft, 0.0)
    # speckle texture: vertically streaky, moderately grainy
    hn, wn = max(8, height // 2), max(8, int(width / 1.3))
    n1 = rng.gamma(3.0, 1 / 3.0, size=(hn, wn))
    n1 = np.asarray(Image.fromarray(np.clip(n1 * 80, 0, 255).astype(np.uint8)).resize((width, height), Image.BILINEAR)) / 80.0
    col_gain = rng.normal(1.0, 0.10, size=(1, width))
    img = inten * n1 * col_gain
    img += 0.025 * rng.gamma(1.5, 1.0, size=(height, width))
    # baseline clutter line
    base_row = (vtop / (vtop - vbot)) * (height - 1)
    rows = np.arange(height)[:, None]
    img += np.exp(-((rows - base_row) / 1.6) ** 2) * rng.uniform(0.25, 0.55, size=(1, width))
    img = np.clip(img, 0, 1) ** 0.95
    out = Image.fromarray((img * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(0.45))
    return out


def ecg_signal(t: np.ndarray, hr: float = 68.0) -> np.ndarray:
    period = 60.0 / hr
    ph = np.mod(t + 0.12, period) - 0.12  # R at phase 0
    g = lambda mu, sd, a: a * np.exp(-((ph - mu) / sd) ** 2)  # noqa: E731
    return g(-0.16, 0.025, 0.12) + g(-0.03, 0.010, -0.12) + g(0.0, 0.011, 1.0) + g(0.032, 0.012, -0.28) + g(0.27, 0.05, 0.30)


def ecg_path(x, y, w, h, hr=68.0, px_per_s=170.0, t0=0.0) -> QPainterPath:
    n = max(2, int(w * 2))
    xs = np.linspace(0, w, n)
    t = t0 + xs / px_per_s
    sig = ecg_signal(t, hr)
    path = QPainterPath()
    mid = y + h * 0.68
    for i, (xx, ss) in enumerate(zip(xs, sig)):
        pt = QPointF(x + xx, mid - ss * h * 0.6)
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    return path


@functools.lru_cache(maxsize=None)
def mmode_image(name: str = "gold7+ECG", p0=(648, 100), p1=(690, 770), width: int = 600, height: int = 300, repeats: int = 2) -> Image.Image:
    """Anatomical M-mode: sample a scan line through every frame and stack in time."""
    n = nframes(name)
    L = 420
    xs = np.linspace(p0[0], p1[0], L)
    ys = np.linspace(p0[1], p1[1], L)
    cols = []
    for k in range(n):
        a = np.asarray(frame(name, k), dtype=np.float32)
        xi = np.clip(xs.astype(int), 0, a.shape[1] - 1)
        yi = np.clip(ys.astype(int), 0, a.shape[0] - 1)
        # 3-px wide sampling for smoother texture
        col = (a[yi, xi] + a[yi, np.clip(xi + 1, 0, a.shape[1] - 1)] + a[yi, np.clip(xi - 1, 0, a.shape[1] - 1)]) / 3
        cols.append(col)
    m = np.stack(cols, axis=1)
    m = np.concatenate([m, m[:, ::-1]] * repeats, axis=1)
    im = Image.fromarray(np.clip(m, 0, 255).astype(np.uint8), "L").resize((width, height), Image.BICUBIC)
    return im


@functools.lru_cache(maxsize=None)
def mmode_synth(width: int = 600, height: int = 300, hr: float = 68.0, px_per_s: float = 150.0, seed: int = 5) -> Image.Image:
    """Procedural PLAX M-mode through the LV (chest wall, RV, IVS, LV cavity, LVPW, pericardium)."""
    rng = np.random.default_rng(seed)
    t = np.arange(width) / px_per_s
    period = 60.0 / hr
    ph = np.mod(t, period)
    # contraction curve: 0 at ED, 1 at end-systole, rapid early filling, small atrial kick
    s = np.where(ph < 0.34, np.clip(np.sin(0.5 * np.pi * np.clip(ph, 0, 0.34) / 0.34), 0, 1) ** 1.4, 0.0)
    rel = np.where((ph >= 0.34) & (ph < 0.56), np.clip(np.cos(0.5 * np.pi * np.clip(ph - 0.34, 0, 0.22) / 0.22), 0, 1) ** 1.3, 0.0)
    s = np.where(ph >= 0.34, rel, s)
    s = s + np.where((ph > 0.74) & (ph < 0.86), -0.08 * np.sin(np.pi * (ph - 0.74) / 0.12), 0.0)
    z = np.linspace(0, 1, height)[:, None]
    S = s[None, :]
    b = {
        "rv_top": 0.105 + 0.0 * S,
        "rv_bot": 0.165 + 0.01 * S,
        "ivs_top": 0.300 + 0.022 * S,
        "ivs_bot": 0.392 + 0.055 * S,
        "pw_top": 0.770 - 0.120 * S,
        "pw_bot": 0.865 - 0.075 * S,
    }
    def band(a, c, sharp=0.006):
        return 1 / (1 + np.exp(-(z - a) / sharp)) * (1 - 1 / (1 + np.exp(-(z - c) / sharp)))
    img = 0.80 * band(0.0, b["rv_top"]) * (0.7 + 0.3 * np.cos(z * 60) ** 2)
    img += 0.55 * band(b["rv_top"], b["rv_bot"])
    img += 0.06 * band(b["rv_bot"], b["ivs_top"])
    img += 0.62 * band(b["ivs_top"], b["ivs_bot"])
    img += 0.05 * band(b["ivs_bot"], b["pw_top"])
    img += 0.66 * band(b["pw_top"], b["pw_bot"])
    img += 0.98 * band(b["pw_bot"], b["pw_bot"] + 0.045)
    img += 0.40 * band(b["pw_bot"] + 0.045, 1.2) * np.exp(-(z - 0.9) * 3)
    hn, wn = height, max(8, width // 7)
    n1 = rng.gamma(2.2, 1 / 2.2, size=(hn, wn))
    n1 = np.asarray(Image.fromarray(np.clip(n1 * 70, 0, 255).astype(np.uint8)).resize((width, height), Image.BICUBIC)) / 70.0
    img = img * (0.55 + 0.45 * n1) + 0.03 * rng.gamma(1.3, 1, size=(height, width))
    img = np.clip(img, 0, 1) ** 0.9
    return Image.fromarray((img * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(0.6))


@functools.lru_cache(maxsize=None)
def color_flow(name: str = "gold6", idx: int = 0) -> Image.Image:
    """B-mode sector + synthetic colour-flow jet through the mitral valve."""
    base = sector(name, idx).convert("RGB")
    W, H = base.size
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # jet from LA (bottom) towards LV apex region, centred on the mitral valve
    cx, cy = 0.60 * W, 0.58 * H
    ang = math.radians(-12)
    u = (xx - cx) * math.cos(ang) + (yy - cy) * math.sin(ang)
    v = -(xx - cx) * math.sin(ang) + (yy - cy) * math.cos(ang)
    jet = np.exp(-(u / (0.085 * W)) ** 2 - (v / (0.23 * H)) ** 2)
    jet *= np.clip(1.15 - np.abs(v) / (0.3 * H), 0, 1)
    noise = np.asarray(Image.fromarray((rng.random((H // 4, W // 4)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)) / 255.0
    jet = np.clip(jet * (0.75 + 0.5 * noise), 0, 1)
    # colour map: dark red → red → orange/yellow core, a few aliasing cyan specks
    r = np.clip(0.55 + 0.6 * jet, 0, 1)
    g = np.clip((jet - 0.55) * 1.8, 0, 1) * 0.85
    b = np.clip((jet - 0.85) * 2.5, 0, 1) * 0.6
    alias = (jet > 0.96) & (noise > 0.86)
    r = np.where(alias, 0.15, r)
    g = np.where(alias, 0.75, g)
    b = np.where(alias, 1.0, b)
    a = np.clip((jet - 0.18) * 2.2, 0, 1)
    arr = np.asarray(base).astype(np.float32) / 255
    col = np.dstack([r, g, b])
    out = arr * (1 - a[..., None]) + col * a[..., None]
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), "RGB")


def doppler_qimage(kind: str, width=900, height=360, px_per_s=170.0) -> QImage:
    return pil_to_qimage(doppler_image(kind, width, height, px_per_s))


# ───────────────────────────── geometry helpers ─────────────────────────────


def catmull(points, closed=False, tension=0.5) -> QPainterPath:
    pts = [QPointF(*pt) for pt in points]
    path = QPainterPath(pts[0])
    n = len(pts)
    rng_ = range(n) if closed else range(n - 1)
    for i in rng_:
        p0 = pts[(i - 1) % n] if (closed or i > 0) else pts[i]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if (closed or i + 2 < n) else p2
        c1 = p1 + (p2 - p0) * (tension / 3)
        c2 = p2 - (p3 - p1) * (tension / 3)
        path.cubicTo(c1, c2, p2)
    if closed:
        path.closeSubpath()
    return path


def map_pt(pt, src_box, dst: QRectF):
    """Map a source-frame pixel coordinate into a drawn image rect."""
    x0, y0, x1, y1 = src_box
    return (dst.x() + (pt[0] - x0) / (x1 - x0) * dst.width(), dst.y() + (pt[1] - y0) / (y1 - y0) * dst.height())


# LV endocardium (gold7+ECG, frame 0) in source pixels: septal annulus → apex → lateral annulus.
LV_CONTOUR_G7 = [
    (604, 470), (594, 428), (589, 380), (589, 330), (596, 282), (612, 243), (636, 216),
    (664, 205), (694, 212), (722, 236), (745, 272), (760, 318), (768, 368), (770, 420), (758, 468),
]
LA_CONTOUR_G7 = [
    (606, 482), (588, 520), (580, 572), (590, 630), (628, 676), (680, 686), (726, 660),
    (752, 610), (756, 552), (752, 494),
]
