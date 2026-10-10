#!/usr/bin/env python3
"""Record the feature-tour GIFs for the project website from the real application UI.

Developer tool, NOT part of the application and NOT a Pages build dependency.
It boots ``MainWindow`` with Qt's offscreen platform, drives it through the same
widgets and handlers a user reaches (mouse clicks on the viewer, tabs, menus,
the preferences dialog), grabs the window every few milliseconds and writes
optimised GIFs to ``site/media/tour/``.

The clinical-looking pixels are a SYNTHETIC cine phantom generated here (a
fan-shaped speckle image with a pulsating left ventricle). No patient data,
no vendor screenshots and no real acquisition are used. The phantom only
exists so that the tools have an image to act on.

Requirements: the project environment (``uv sync --extra dev``). On hosts
without system OpenGL libraries run ``CI=1 python tools/qtstub/mkstub.py``
first and export ``LD_LIBRARY_PATH=tools/qtstub/lib``.

Usage (from the repository root):
    python tools/record_tour.py                 # all scenarios
    python tools/record_tour.py lv-contours     # one scenario by name
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "media" / "tour"
SRC = ROOT / "src"

# Isolate every QSettings / data / cache path from the developer's real profile.
_WORK = Path(tempfile.mkdtemp(prefix="sf-tour-"))
os.environ["HOME"] = str(_WORK / "home")
os.environ["XDG_DATA_HOME"] = str(_WORK / "data")
os.environ["XDG_CONFIG_HOME"] = str(_WORK / "home" / ".config")
os.environ["XDG_CACHE_HOME"] = str(_WORK / "cache")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LANG", "en_US.UTF-8")
sys.path.insert(0, str(SRC))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
GIF_WIDTH = 960
FRAME_MS = 80  # default frame duration: ~12 fps


# ---------------------------------------------------------------- phantom cine
def make_phantom_cine(path: Path, *, variant: int, frames: int = 48, fps: int = 16) -> None:
    """Write a fan-shaped synthetic apical cine with a pulsating LV (mp4v)."""
    w, h = 720, 540
    rng = np.random.default_rng(11 + variant)
    speckle = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 0.9)
    lo, hi = np.percentile(speckle, [1, 99])
    speckle = np.clip((speckle - lo) / (hi - lo + 1e-6), 0.0, 1.0)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    apex_x, apex_y = w / 2 + 10 * variant, 26.0
    dx, dy = xx - apex_x, yy - apex_y
    radius = np.sqrt(dx * dx + dy * dy)
    angle = np.arctan2(dx, dy)
    fan = (np.abs(angle) < 0.68) & (radius < h - 40)
    attenuation = np.exp(-radius / 520.0)

    cx = w / 2 + (-6 if variant else 6)
    cy = 262.0
    la_cx, la_cy = cx - 175, 215.0
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (w, h))
    if not writer.isOpened():
        raise RuntimeError("cv2.VideoWriter could not open the phantom file")
    try:
        for index in range(frames):
            phase = 0.5 - 0.5 * np.cos(2 * np.pi * index / frames)  # 0 = end-diastole, 1 = end-systole
            rx = 135 - 42 * phase
            ry = 175 - 48 * phase
            ex = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
            wall = ((xx - cx) / (rx + 26)) ** 2 + ((yy - cy) / (ry + 26)) ** 2
            atrium = ((xx - la_cx) / 92) ** 2 + ((yy - la_cy) / 62) ** 2
            tissue = 55 + 120 * speckle
            tissue = np.where(wall < 1.0, 118 + 60 * speckle, tissue)  # myocardium
            tissue = np.where(ex < 1.0, 14 + 10 * speckle, tissue)  # blood pool
            tissue = np.where((atrium < 1.0) & (ex >= 1.0), 22 + 12 * speckle, tissue)
            image = np.clip(tissue * attenuation * fan, 0, 255).astype(np.uint8)
            frame = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            writer.write(frame)
    finally:
        writer.release()


# ---------------------------------------------------------------- capture helpers
def _qimage_to_pil(image) -> Image.Image:  # noqa: ANN001 - QImage
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    # Keep the QByteArray in a named variable for the whole write: a temporary
    # owned only by the QBuffer is freed too early and crashes the process.
    storage = QByteArray()
    buffer = QBuffer(storage)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    data = bytes(storage)
    return Image.open(io.BytesIO(data)).convert("RGB")


class Recorder:
    """Drives a live ``MainWindow`` and collects frames for each GIF."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []

    # time and events
    def pump(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def snap(self, widget=None, *, hold_ms: int = FRAME_MS, crop=None) -> None:  # noqa: ANN001
        target = widget if widget is not None else self.window
        image = _qimage_to_pil(target.grab().toImage())
        if crop is not None:
            image = image.crop(crop)
        self.frames.append(image)
        self.durations.append(hold_ms)

    def hold(self, seconds: float, *, widget=None, step_ms: int = 140, crop=None) -> None:  # noqa: ANN001
        steps = max(1, int(seconds * 1000 / step_ms))
        for _ in range(steps):
            self.pump(step_ms / 1000)
            self.snap(widget, hold_ms=step_ms, crop=crop)

    def take(self) -> tuple[list[Image.Image], list[int]]:
        frames, durations = self.frames, self.durations
        self.frames, self.durations = [], []
        return frames, durations

    # application state helpers
    def wait_until(self, predicate, timeout: float = 30.0) -> bool:  # noqa: ANN001
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump(0.1)
            if predicate():
                return True
        return False

    def gallery_count(self) -> int:
        return self.window._gallery.count()

    def select_thumbnail(self, row: int) -> None:
        gallery = self.window._gallery
        gallery._on_item_clicked(gallery.item(row))

    def frame_ready(self) -> bool:
        return self.window._viewer._image_item.image is not None

    def open_study(self, folder: Path) -> None:
        self.window.open_folder_path(folder)
        if not self.wait_until(lambda: self.gallery_count() > 0, timeout=60):
            raise RuntimeError(f"scan of {folder} produced no thumbnails")
        self.select_thumbnail(0)
        if not self.wait_until(self.frame_ready, timeout=60):
            raise RuntimeError(f"first frame of {folder} did not render")
        # Synthetic phantom has no physical scale: give it a nominal 0.2 mm/px, as a
        # user would from the Caliper calibration, so results are shown in mm.
        self.window._controller.state_manager.set_manual_pixel_spacing((0.2, 0.2))
        self.pump(0.6)


# ---------------------------------------------------------------- GIF writer
def save_gif(name: str, frames: list[Image.Image], durations: list[int], *, width: int = GIF_WIDTH) -> Path:
    if not frames:
        raise RuntimeError(f"{name}: no frames captured")
    target_w = min(width, frames[0].width)
    scale = target_w / frames[0].width
    size = (target_w, round(frames[0].height * scale))
    small = [f.resize(size, Image.Resampling.LANCZOS) if f.size != size else f for f in frames]
    # One shared palette from sampled frames keeps colours stable across the loop.
    sample = Image.new("RGB", (size[0] * 3, size[1]))
    for k, index in enumerate((0, len(small) // 2, len(small) - 1)):
        sample.paste(small[index], (k * size[0], 0))
    palette = sample.quantize(colors=200, method=Image.Quantize.MEDIANCUT)
    quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in small]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.gif"
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        disposal=1,
        optimize=True,
    )
    print(f"{name}: {len(frames)} frames, {path.stat().st_size / 1024:.0f} KiB")  # noqa: T201 - CLI output
    return path


def caption(image: Image.Image, text: str, *, color=(56, 189, 248)) -> Image.Image:
    """Put a short label on a frame's top-left corner (used for side-by-side comparisons)."""
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(FONT), 15) if FONT.exists() else ImageFont.load_default()
    width = int(draw.textlength(text, font=font)) + 18
    draw.rounded_rectangle((8, 8, 8 + width, 36), radius=6, fill=(8, 12, 17), outline=color)
    draw.text((17, 13), text, font=font, fill=(230, 237, 243))
    return canvas


def side_by_side(left: list[Image.Image], right: list[Image.Image]) -> list[Image.Image]:
    count = max(len(left), len(right))
    left = left + [left[-1]] * (count - len(left))
    right = right + [right[-1]] * (count - len(right))
    out = []
    for a, b in zip(left, right, strict=True):
        canvas = Image.new("RGB", (a.width + b.width + 8, max(a.height, b.height)), (30, 41, 52))
        canvas.paste(a, (0, 0))
        canvas.paste(b, (a.width + 8, 0))
        out.append(canvas)
    return out


# ---------------------------------------------------------------- app driving
def click_widget(recorder: Recorder, widget, local=None, button=None) -> None:  # noqa: ANN001
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    point = local if local is not None else widget.rect().center()
    QTest.mouseClick(widget, button or Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    recorder.pump(0.05)


def find_button(root, text: str):  # noqa: ANN001
    from PySide6.QtWidgets import QAbstractButton

    for button in root.findChildren(QAbstractButton):
        if button.text().strip() == text and button.isVisible():
            return button
    raise LookupError(f"button not found: {text!r}")


def image_to_widget(viewer, x: float, y: float):  # noqa: ANN001
    """Map an image pixel of the current frame to the viewer's viewport coordinates."""
    from PySide6.QtCore import QPointF

    scene_point = viewer._view.mapViewToScene(QPointF(float(x), float(y)))
    local = viewer._graphics.mapFromScene(scene_point)
    return local


def drag_path(recorder: Recorder, viewer, points, *, capture_every: int = 3, widget=None) -> None:  # noqa: ANN001
    """Press at the first point, move through the rest, release. Captures frames while drawing."""
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest

    target = viewer._graphics.viewport()
    first = image_to_widget(viewer, *points[0])
    QTest.mousePress(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    recorder.pump(0.04)
    for index, point in enumerate(points[1:], start=1):
        local = image_to_widget(viewer, *point)
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            local.toPointF(),
            target.mapToGlobal(QPoint(local.x(), local.y())).toPointF(),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        recorder.app.sendEvent(target, move)
        recorder.pump(0.03)
        if index % capture_every == 0:
            recorder.snap(widget, hold_ms=70)
    last = image_to_widget(viewer, *points[-1])
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, last)
    recorder.pump(0.1)


def lv_phantom_points(*, sides: int = 36) -> dict[str, tuple[float, float]]:
    """Landmark image coordinates on the phantom (end-diastolic frame 0)."""
    cx, cy = 360 - 6, 262.0  # variant 0 centre (see make_phantom_cine)
    rx, ry = 135, 175
    return {
        "septal": (cx - rx * 0.92, cy + ry * 0.80),
        "lateral": (cx + rx * 0.92, cy + ry * 0.80),
        "apex": (cx, cy - ry * 0.98),
        "_sides": (sides, 0),
    }


def ellipse_arc_from_annulus(step_px: float = 9.0) -> list[tuple[float, float]]:
    """Hand-like freehand stroke: septal annulus → along the septum → apex → lateral wall → lateral annulus.

    Built from control points on the phantom's LV border (apex at the top of the image,
    mitral annulus at the bottom) and densified with a small, reproducible wobble.
    """
    cx, cy = 360 - 6, 262.0
    rx, ry = 135, 175
    controls = [
        (cx - 0.92 * rx, cy + 0.80 * ry),
        (cx - 0.96 * rx, cy + 0.20 * ry),
        (cx - 0.86 * rx, cy - 0.45 * ry),
        (cx - 0.50 * rx, cy - 0.84 * ry),
        (cx, cy - 0.98 * ry),
        (cx + 0.50 * rx, cy - 0.84 * ry),
        (cx + 0.86 * rx, cy - 0.45 * ry),
        (cx + 0.96 * rx, cy + 0.20 * ry),
        (cx + 0.92 * rx, cy + 0.80 * ry),
    ]
    rng = np.random.default_rng(3)
    pts: list[tuple[float, float]] = []
    for (x0, y0), (x1, y1) in zip(controls, controls[1:], strict=False):
        length = float(np.hypot(x1 - x0, y1 - y0))
        count = max(2, int(length / step_px))
        for k in range(count):
            t = k / count
            x = x0 + (x1 - x0) * t + 0.8 * rng.standard_normal()
            y = y0 + (y1 - y0) * t + 0.8 * rng.standard_normal()
            pts.append((float(x), float(y)))
    x_last, y_last = controls[-1]
    pts.append((float(x_last), float(y_last)))
    return pts


# ---------------------------------------------------------------- scenarios
PHANTOM_A = "phantom-a"
PHANTOM_B = "phantom-b"


def _study_folders(work: Path) -> tuple[Path, Path]:
    folder_a = work / "study-a"
    folder_b = work / "study-b"
    make_phantom_cine(folder_a / "cine_a.mp4", variant=0)
    make_phantom_cine(folder_b / "cine_b.mp4", variant=1)
    return folder_a, folder_b


def _new_window(recorder: Recorder):  # noqa: ANN202
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    prefs = UserPreferences(layout_state_json="")
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    window.resize(1280, 800)
    window.show()
    recorder.window = window
    recorder.pump(1.0)
    return window


def scenario_open_study(recorder: Recorder, folder_a: Path) -> None:
    """Start page / empty window → open a folder → thumbnail → first frame → cine playback."""
    recorder.snap(hold_ms=1200)
    recorder.hold(0.6)
    recorder.open_study(folder_a)
    recorder.hold(0.8, step_ms=160)
    # Press the real Play button so the cine actually advances in the capture.
    click_widget(recorder, recorder.window._viewer._play_button)
    recorder.hold(3.0, step_ms=160)
    save_gif("open-study", *recorder.take())


def scenario_tabs(recorder: Recorder, folder_a: Path, folder_b: Path) -> None:
    """Each study opens in its own tab; Ctrl+Tab switches between them."""

    recorder.open_study(folder_a)
    recorder.hold(0.6, step_ms=200)
    recorder.window.open_folder_path(folder_b)
    recorder.wait_until(lambda: recorder.gallery_count() > 0, timeout=60)
    recorder.select_thumbnail(0)
    recorder.wait_until(recorder.frame_ready, timeout=60)
    recorder.pump(0.8)
    recorder.hold(1.0, step_ms=200)
    ids = recorder.window._tab_strip.tab_ids()
    for tab_id in (ids[0], ids[1], ids[0]):
        recorder.window._on_tab_selected(tab_id)
        recorder.pump(0.4)
        recorder.hold(1.0, step_ms=200)
    save_gif("tabs", *recorder.take())


def scenario_lv_contours(recorder: Recorder, folder_a: Path) -> None:
    """Same end-diastolic frame: three landmark clicks vs one freehand stroke."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    viewer = recorder.window._viewer
    points = lv_phantom_points()
    septal, lateral, apex = points["septal"], points["lateral"], points["apex"]
    results: list[list[Image.Image]] = []
    durations_per: list[list[int]] = []

    recorder.open_study(folder_a)
    viewer = recorder.window._viewer
    viewer.set_magnetic_snap_enabled(False)

    # A — three landmarks (septal annulus → lateral annulus → apex), then finish.
    viewer.set_lv_contour_input("landmarks")
    viewer.start_contour(phase="ED", view="A4C", chamber="LV", force_landmarks=True)
    recorder.pump(0.3)
    recorder.snap(viewer, hold_ms=600)
    for point in (septal, lateral, apex):
        click_widget(recorder, viewer._graphics.viewport(), image_to_widget(viewer, *point))
        recorder.hold(0.35, widget=viewer, step_ms=170)
    QTest.keyClick(viewer, Qt.Key.Key_Return)
    recorder.hold(1.2, widget=viewer, step_ms=170)
    results.append(recorder.take()[0])
    durations_per.append([170] * len(results[-1]))
    # B — freehand stroke on a fresh window, so contour A is not on screen.
    recorder.window.close()
    recorder.pump(0.2)
    _new_window(recorder)
    recorder.open_study(folder_a)
    viewer = recorder.window._viewer
    viewer.set_magnetic_snap_enabled(False)
    viewer.set_lv_contour_input("trace")
    viewer.start_contour(phase="ED", view="A4C", chamber="LV")
    recorder.pump(0.3)
    recorder.snap(viewer, hold_ms=600)
    drag_path(recorder, viewer, ellipse_arc_from_annulus(), capture_every=2, widget=viewer)
    QTest.keyClick(viewer, Qt.Key.Key_Return)
    recorder.hold(1.2, widget=viewer, step_ms=170)
    results.append(recorder.take()[0])
    durations_per.append([70] * len(results[-1]))

    left = [caption(f, "3 landmarks: septal → lateral → apex") for f in results[0]]
    right = [caption(f, "Freehand trace (one stroke)") for f in results[1]]
    frames = side_by_side(left, right)
    durations = [FRAME_MS] * len(frames)
    save_gif("lv-contours", frames, durations, width=GIF_WIDTH)


def scenario_tools_customization(recorder: Recorder) -> None:
    """Settings → Tools: show/hide tools and reorder/extend sections; the Measures panel follows."""
    from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

    window = recorder.window
    dialog = UserPreferencesDialog(window)
    dialog.resize(980, 720)
    dialog.show()
    recorder.pump(0.4)
    tab_index = dialog._tabs.indexOf(dialog._tool_panel_settings)
    dialog._tabs.setCurrentIndex(tab_index)
    recorder.pump(0.3)
    recorder.hold(1.0, widget=dialog, step_ms=200)
    from PySide6.QtWidgets import QAbstractButton

    # Reorder sections with the real ↑/↓ header buttons of the Tools tab.
    arrows = [b for b in dialog._tool_panel_settings.findChildren(QAbstractButton) if b.text().strip() in ("↓", "↑")]
    down = [b for b in arrows if b.text().strip() == "↓" and b.isVisible()]
    for button in down[:2]:
        click_widget(recorder, button)
        recorder.hold(0.6, widget=dialog, step_ms=160)
    dialog.close()
    recorder.pump(0.3)
    recorder.hold(1.0, step_ms=200)
    save_gif("tools-customization", *recorder.take())


def scenario_layout(recorder: Recorder) -> None:
    """Layout menu: gallery position, activity bar and status bar follow the chosen arrangement."""
    window = recorder.window
    recorder.hold(0.6, step_ms=200)
    for attr in ("gallery_horizontal", "status_bar_visible"):
        window._on_layout_toggle(attr, False)
        recorder.pump(0.4)
        recorder.hold(0.9, step_ms=200)
    window._on_layout_toggle("gallery_horizontal", True)
    recorder.pump(0.4)
    recorder.hold(0.9, step_ms=200)
    window._on_layout_toggle("status_bar_visible", True)
    recorder.pump(0.4)
    recorder.hold(0.8, step_ms=200)
    save_gif("layout", *recorder.take())


def scenario_linear_caliper(recorder: Recorder, folder_a: Path) -> None:
    """Click-click linear caliper with the result placed on the frame."""
    viewer = recorder.window._viewer
    cx, cy = 360 - 6, 262.0
    recorder.open_study(folder_a)
    recorder.hold(0.4, step_ms=180)
    viewer.start_linear_caliper_for("LVIDd")
    recorder.pump(0.3)
    start = (cx - 135 * 0.86, cy + 10)
    end = (cx + 135 * 0.86, cy + 10)
    click_widget(recorder, viewer._graphics.viewport(), image_to_widget(viewer, *start))
    recorder.hold(0.5, widget=viewer, step_ms=170)
    recorder.snap(viewer, hold_ms=300)
    click_widget(recorder, viewer._graphics.viewport(), image_to_widget(viewer, *end))
    recorder.hold(1.6, widget=viewer, step_ms=170)
    save_gif("linear-caliper", *recorder.take())


def scenario_calculators(recorder: Recorder, folder_a: Path) -> None:
    """Right panel → Calculators tab; the continuity and PISA cards expand in place."""
    from PySide6.QtWidgets import QTabBar

    recorder.open_study(folder_a)
    recorder.hold(0.6, step_ms=200)
    bars = [bar for bar in recorder.window.findChildren(QTabBar) if bar.isVisible()]
    target = None
    for bar in bars:
        for index in range(bar.count()):
            if bar.tabText(index).strip().lower() == "calculators":
                target = (bar, index)
    if target is None:
        raise LookupError("Calculators tab not found")
    bar, index = target
    click_widget(recorder, bar, bar.tabRect(index).center())
    recorder.hold(0.8, step_ms=200)
    from echo_personal_tool.presentation.calculators_panel import CalculatorsPanel

    panel = next(p for p in recorder.window.findChildren(CalculatorsPanel) if p.isVisible())
    # The panel builds its surface lazily; in this scripted run the surface was not
    # shown with the tab, so show it explicitly before capturing (no effect on the app).
    if panel._surface is not None:
        panel._surface.show()
    recorder.pump(0.5)
    sections = list(panel._section_labels)[:3]
    for section in sections:
        panel.set_section_expanded(section, True)
        recorder.hold(0.9, step_ms=180)
    save_gif("calculators", *recorder.take())


SCENARIOS = {
    "open-study": "open_study",
    "tabs": "tabs",
    "lv-contours": "lv_contours",
    "tools-customization": "tools_customization",
    "layout": "layout",
    "linear-caliper": "linear_caliper",
    "calculators": "calculators",
}


def run(selected: list[str]) -> None:
    recorder = Recorder()
    folder_a, folder_b = _study_folders(_WORK)
    for name in selected:
        recorder.frames, recorder.durations = [], []
        recorder.window = None  # type: ignore[assignment]
        _new_window(recorder)
        try:
            if name == "open-study":
                scenario_open_study(recorder, folder_a)
            elif name == "tabs":
                scenario_tabs(recorder, folder_a, folder_b)
            elif name == "lv-contours":
                scenario_lv_contours(recorder, folder_a)
            elif name == "tools-customization":
                recorder.open_study(folder_a)
                scenario_tools_customization(recorder)
            elif name == "layout":
                recorder.open_study(folder_a)
                scenario_layout(recorder)
            elif name == "linear-caliper":
                scenario_linear_caliper(recorder, folder_a)
            elif name == "calculators":
                scenario_calculators(recorder, folder_a)
            else:
                raise SystemExit(f"unknown scenario {name}")
        finally:
            recorder.window.close()
            recorder.window.deleteLater()
            recorder.pump(0.2)


def main(argv: list[str]) -> int:
    selected = argv[1:] or list(SCENARIOS)
    unknown = [name for name in selected if name not in SCENARIOS]
    if unknown:
        print("unknown scenario(s):", ", ".join(unknown), file=sys.stderr)  # noqa: T201 - CLI output
        return 2
    try:
        run(selected)
    finally:
        shutil.rmtree(_WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
