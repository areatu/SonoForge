#!/usr/bin/env python3
"""Regenerate the six small landing-page GIFs and their static posters.

Optional authoring tool, NOT a Pages build dependency. Requires Pillow >= 10
and DejaVu fonts (Debian: fonts-dejavu-core). Run from any directory:
    python site/generate_feature_media.py

Clinical pixels come only from the project's existing screenshots / demos.
Crops exclude patient identifiers, acquisition dates and application chrome.
The vascular spectrum is an actual PW strip, not a generated waveform. PACS
and report previews are illustrative diagrams, not fabricated application UI.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site/media/features"
SIZE = (480, 224)
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
BG = "#080c11"
PANEL = "#111b25"
BORDER = "#273948"
TEXT = "#e6edf3"
MUTED = "#8b9bab"
CYAN = "#38bdf8"
GREEN = "#34d399"
WARM = "#f59e0b"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def text(draw: ImageDraw.ImageDraw, xy, value, size=12, color=TEXT, bold=False):
    draw.text(xy, value, font=font(size, bold), fill=color)


def pill(draw, xy, value, color=CYAN):
    x, y = xy
    width = draw.textlength(value, font=font(10, True)) + 16
    draw.rounded_rectangle((x, y, x + width, y + 20), radius=5, fill=PANEL, outline=BORDER)
    text(draw, (x + 8, y + 3), value, 10, color, True)


def canvas(title, badge):
    image = Image.new("RGB", SIZE, BG)
    draw = ImageDraw.Draw(image)
    draw.line((0, 30, 480, 30), fill=BORDER)
    text(draw, (16, 9), title, 11, TEXT, True)
    width = draw.textlength(badge, font=font(10, True)) + 16
    pill(draw, (464 - width, 5), badge)
    return image


def tick(draw, xy, color=GREEN):
    x, y = xy
    draw.line([(x, y + 3), (x + 3, y + 6), (x + 9, y)], fill=color, width=2)


def cross(draw, xy, radius=4):
    x, y = xy
    draw.line((x - radius, y, x + radius, y), fill=CYAN, width=2)
    draw.line((x, y - radius, x, y + radius), fill=CYAN, width=2)


def demo_frames(path: Path, indexes: list[int]) -> list[Image.Image]:
    """Decode sequentially so delta-encoded frames are fully composited."""
    wanted = set(indexes)
    found = {}
    with Image.open(path) as source:
        for index, frame in enumerate(ImageSequence.Iterator(source)):
            if index in wanted:
                found[index] = frame.convert("RGB").copy()
            if index == max(indexes):
                break
    return [found[index] for index in indexes]


def save(name, frames, duration=120, poster_index=-1):
    # One shared palette and no dithering keep the ultrasound texture consistent
    # and let GIF delta frames compress the otherwise-static diagram backgrounds.
    sample = Image.new("RGB", (SIZE[0] * 3, SIZE[1]))
    for index, frame in enumerate((frames[0], frames[len(frames) // 2], frames[-1])):
        sample.paste(frame, (index * SIZE[0], 0))
    palette = sample.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    OUT.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        OUT / f"{name}.gif",
        save_all=True,
        append_images=quantized[1:],
        duration=duration,
        loop=0,
        disposal=1,
        optimize=True,
    )
    frames[poster_index].save(OUT / f"{name}-poster.jpg", quality=88, optimize=True)
    print(f"{name}: {(OUT / f'{name}.gif').stat().st_size / 1024:.0f} KiB")


def cardiac():
    with Image.open(ROOT / "docs/screenshots/lv-linear-measurements.png") as source:
        # Coordinates below refer to the 1568×942 display-size screenshot;
        # scale the crop to the original PNG resolution before sampling pixels.
        sx, sy = source.width / 1568, source.height / 942
        box = tuple(round(value * (sx if i % 2 == 0 else sy)) for i, value in enumerate((380, 250, 1090, 745)))
        crop = source.convert("RGB").crop(box).resize((240, 167), Image.Resampling.LANCZOS)
    # The original caliper endpoints / values, not simulated measurements.
    endpoints = [(726, 349), (699, 401), (599, 593), (582, 636)]
    points = [(18 + (x - 380) * 240 / 710, 37 + (y - 250) * 167 / 495) for x, y in endpoints]
    frames = []
    for n in range(36):
        image = canvas("CARDIAC MEASUREMENTS", "B / M-MODE")
        image.paste(crop, (18, 37))
        draw = ImageDraw.Draw(image)
        for i, (label, value) in enumerate((("IVSd", "15.1"), ("LVIDd", "55.8"), ("LVPWd", "11.6"))):
            y = 43 + i * 52
            progress = min(1, max(0, (n - i * 8) / 7))
            active = progress > 0
            text(draw, (282, y), label, 11, CYAN if active else MUTED, True)
            text(draw, (282, y + 15), f"{value} mm", 20, TEXT if active else BORDER, True)
            if active:
                a, b = points[i], points[i + 1]
                end = (a[0] + (b[0] - a[0]) * progress, a[1] + (b[1] - a[1]) * progress)
                draw.line([a, end], fill=CYAN, width=2)
                cross(draw, a)
                cross(draw, end)
                if progress == 1:
                    tick(draw, (435, y + 23))
        text(draw, (18, 207), "B-mode / M-mode calipers · Simpson volumes", 10, MUTED)
        frames.append(image)
    save("cardiac", frames, poster_index=29)


def spectral(source):
    # Genuine vessel PW spectrum from the end of sonoforge_preview.gif. Includes
    # the velocity ruler / time ticks, but none of the patient / acquisition text.
    box = (144, 220, 579, 349)
    image = source.crop(box).resize((448, 133), Image.Resampling.LANCZOS)

    def xy(x, y):
        return (16 + (x - box[0]) * 448 / 435, 43 + (y - box[1]) * 133 / 129)

    return image, xy


def doppler(source):
    strip, xy = spectral(source)
    frames = []
    for n in range(28):
        image = canvas("PW DOPPLER", "VASCULAR")
        image.paste(strip, (16, 43))
        draw = ImageDraw.Draw(image)
        # Highlight an actual cycle and its PSV / EDV locations on the strip.
        shift = 81 if n >= 14 else 0
        a = xy(173 + shift, 225)
        b = xy(251 + shift, 309)
        draw.rounded_rectangle((*a, *b), radius=4, outline=BORDER)
        for x, y, color in ((178 + shift, 244, CYAN), (248 + shift, 289, WARM)):
            px, py = xy(x, y)
            radius = 3 + (n % 7) / 8
            draw.ellipse((px - radius, py - radius, px + radius, py + radius), outline=color, width=2)
        for x, label, value, color in (
            (18, "PSV", "92.6 cm/s", CYAN),
            (184, "EDV", "26.6 cm/s", WARM),
            (348, "RI", "0.71", GREEN),
        ):
            text(draw, (x, 180), label, 10, MUTED, True)
            text(draw, (x, 194), value, 15, color, True)
        frames.append(image)
    save("doppler", frames, poster_index=10)


def calibration(source):
    strip, xy = spectral(source)
    frames = []
    for n in range(33):
        image = canvas("AUTO-CALIBRATION", "PW")
        image.paste(strip, (16, 43))
        draw = ImageDraw.Draw(image)
        phase = min(2, n // 9)
        progress = min(1, (n - phase * 9) / 7)
        baseline = xy(146, 309)[1]
        end_x = xy(543, 309)[0]
        if phase == 0:
            end_x = 16 + (end_x - 16) * progress
        draw.line((16, baseline, end_x, baseline), fill=CYAN, width=2)
        if phase >= 1:
            for i, value in enumerate((226, 253, 280)):
                if phase == 1 and i > progress * 2:
                    continue
                x, y = xy(543, value)
                draw.rounded_rectangle((x - 4, y - 5, x + 33, y + 7), radius=3, outline=CYAN)
        if phase >= 2:
            y = xy(146, 336)[1]
            values = list(range(157, 531, 22))
            for i, value in enumerate(values):
                if i > progress * (len(values) - 1):
                    continue
                x, _ = xy(value, 336)
                draw.line((x, y - 3, x, y + 3), fill=WARM, width=2)
        for i, label in enumerate(("BASELINE", "VELOCITY", "TIME AXIS")):
            x = 18 + i * 151
            pill(draw, (x, 191), label, TEXT if i <= phase else MUTED)
            if i <= phase:
                tick(draw, (x + 120, 198))
        frames.append(image)
    save("calibration", frames, poster_index=28)


def segmentation(sources):
    frames = []
    for n in range(36):
        # Real A4C cine / tracked nodes from the existing Presenter demonstration.
        crop = sources[n % len(sources)].crop((940, 126, 1390, 426))
        crop = ImageOps.contain(crop, (258, 166), Image.Resampling.LANCZOS)
        r, g, b = crop.split()
        nodes = ImageChops.darker(ImageChops.subtract(g, r), ImageChops.subtract(b, r))
        nodes = nodes.point(lambda value: 255 if value > 30 else 0)
        phase = n // 12
        reveal = min(1, (n + 1) / 11) if phase == 0 else 1
        scan_y = int(crop.height * reveal)
        mask = Image.new("L", crop.size)
        ImageDraw.Draw(mask).rectangle((0, 0, crop.width, scan_y), fill=255)
        nodes = ImageChops.multiply(nodes, mask)
        anatomy = crop.convert("L").convert("RGB")
        anatomy.paste(crop, (0, 0), nodes)
        if phase == 2:
            glow = nodes.filter(ImageFilter.GaussianBlur(2)).point(lambda value: value // 3)
            anatomy.paste(Image.new("RGB", crop.size, CYAN), (0, 0), glow)
        image = canvas("AI SEGMENTATION", "A4C · LV")
        image.paste(anatomy, (18, 37))
        draw = ImageDraw.Draw(image)
        if phase == 0 and reveal < 1:
            draw.line((18, 37 + scan_y, 18 + crop.width, 37 + scan_y), fill=CYAN)
        pill(draw, (292, 42), "ONNX · CPU", GREEN)
        for i, label in enumerate(("DETECT", "TRACK", "REFINE")):
            y = 83 + i * 33
            text(draw, (292, y), f"0{i + 1}", 11, CYAN if i == phase else MUTED, True)
            text(draw, (319, y - 1), label, 13, TEXT if i == phase else MUTED, True)
            if i < phase:
                tick(draw, (443, y + 2))
        draw.rounded_rectangle((292, 183, 456, 187), radius=2, fill=BORDER)
        draw.rounded_rectangle((292, 183, 293 + int(163 * (n + 1) / 36), 187), radius=2, fill=CYAN)
        text(draw, (18, 207), "Temporal tracking · local inference", 10, MUTED)
        frames.append(image)
    save("segmentation", frames, duration=110, poster_index=30)


def pacs(thumbnail):
    frames = []
    thumb = ImageOps.fit(thumbnail, (84, 61), Image.Resampling.LANCZOS)
    for n in range(30):
        image = canvas("DICOM & PACS", "TLS")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((18, 48, 150, 183), radius=9, fill=PANEL, outline=BORDER)
        draw.rounded_rectangle((316, 48, 462, 183), radius=9, fill=PANEL, outline=BORDER)
        text(draw, (62, 59), "PACS", 13, TEXT, True)
        text(draw, (333, 59), "SonoForge", 13, TEXT, True)
        for i in range(3):
            y = 89 + i * 26
            draw.rounded_rectangle((38, y, 130, y + 19), radius=4, outline=MUTED)
            draw.ellipse((47, y + 7, 52, y + 12), fill=GREEN if n >= i * 8 else MUTED)
            draw.line((65, y + 10, 117, y + 10), fill=BORDER, width=2)
        draw.line((150, 103, 315, 103), fill=BORDER, width=2)
        draw.line((150, 135, 315, 135), fill=BORDER, width=2)
        text(draw, (182, 81), "QIDO-RS", 10, MUTED, True)
        text(draw, (182, 147), "WADO-RS", 10, MUTED, True)
        for i in range(3):
            progress = ((n / 30) + i / 3) % 1
            x = 153 + int(158 * progress)
            y = 103 if i % 2 else 135
            draw.rounded_rectangle((x - 5, y - 4, x + 5, y + 4), radius=2, fill=CYAN)
        image.paste(thumb, (330, 87))
        draw = ImageDraw.Draw(image)
        tick(draw, (439, 95))
        text(draw, (330, 161), "DICOM", 10, CYAN, True)
        text(draw, (18, 202), "DICOMweb · DIMSE · secure transfer", 11, MUTED)
        frames.append(image)
    save("pacs", frames, duration=140, poster_index=24)


def reports():
    frames = []
    for n in range(36):
        image = canvas("REPORTS & NORMS", "ASE")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((22, 42, 220, 208), radius=6, fill="#dee7ee")
        text(draw, (37, 50), "SonoForge", 15, "#17212c", True)
        text(draw, (37, 71), "ECHO REPORT · DEMO", 8, "#566574", True)
        draw.line((37, 88, 205, 88), fill="#b6c2cf")
        text(draw, (37, 94), "Parameter", 9, "#566574", True)
        text(draw, (164, 94), "ASE", 9, "#566574", True)
        for i, label in enumerate(("LVEF", "LVMI", "LAVi", "E/e′")):
            if n < i * 5:
                continue
            y = 112 + i * 19
            text(draw, (37, y), label, 10, "#17212c", True)
            draw.line((94, y + 7, 142, y + 7), fill="#b6c2cf", width=3)
            draw.rounded_rectangle((164, y + 1, 195, y + 12), radius=3, fill="#b6d8ce")
            tick(draw, (174, y + 3), "#137b5e")
        text(draw, (37, 194), "REFERENCE RANGES", 8, "#566574", True)
        draw.line((221, 124, 311, 124), fill=BORDER, width=2)
        if n > 15:
            x = 224 + int(((n - 16) / 20) * 82)
            draw.ellipse((x - 4, 120, x + 4, 128), fill=CYAN)
        draw.rounded_rectangle((314, 68, 450, 178), radius=9, fill=PANEL, outline=BORDER)
        draw.line((342, 85, 417, 85, 429, 97, 429, 161, 342, 161, 342, 85), fill=CYAN, width=2)
        text(draw, (356, 106), "PDF", 23, TEXT, True)
        if n >= 26:
            tick(draw, (382, 144))
        else:
            draw.line((386, 140, 386, 153), fill=CYAN, width=2)
            draw.line((381, 148, 386, 153, 391, 148), fill=CYAN, width=2)
        text(draw, (270, 197), "PDF · DICOM SR", 12, MUTED, True)
        frames.append(image)
    save("reports", frames, poster_index=31)


def main():
    vascular = demo_frames(ROOT / "assets/sonoforge_preview.gif", [930])[0]
    cine = demo_frames(ROOT / "assets/presenter_demo.gif", list(range(21, 33)))
    cardiac()
    doppler(vascular)
    calibration(vascular)
    segmentation(cine)
    pacs(cine[-1].crop((940, 126, 1390, 426)))
    reports()


if __name__ == "__main__":
    main()
