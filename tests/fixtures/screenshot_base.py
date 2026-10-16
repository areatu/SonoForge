"""Screenshot baseline helper (UI-0 PR-2, spec 2026-10-16 §5.3, §10).

A *probe* widget is rendered with the real stylesheet of a theme and compared
with a committed PNG baseline (``tests/baselines/ui/<theme>.png``).

The comparison is deliberately tolerant, because a pixel-exact comparison is
not possible:

* the PySide6 version differs between the machines that run the tests
  (``pyside6>=6.6,<6.12``) — the widgets are laid out a little differently;
* the bundled font is rasterized differently on every platform.

So the gate is not «the pixels are equal», but «the theme is the same»:

1. the *strong* colours of the rendering (a share of the pixels above the
   threshold) are exactly the colours of the design tokens — a changed token
   is caught here, and the check does not depend on the font or on the Qt
   version;
2. the image does not differ from the baseline beyond the tolerance (the
   largest per-channel difference and the share of the differing pixels) — a
   big visual change is caught here.

Regenerate the baselines after an intentional change of a theme::

    SONOFORGE_UPDATE_SCREENSHOTS=1 pytest tests/unit/test_ui_screenshot_base.py
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from echo_personal_tool.presentation.theme_tokens import tokens_for

#: Size of the probe widget (pixels).
PROBE_SIZE = (320, 200)

#: A colour counts as *strong* when it covers at least this share of the image.
STRONG_SHARE = 0.005

#: Per-channel difference that still counts as «the same colour».
CHANNEL_TOLERANCE = 48

#: Share of the pixels that may differ from the baseline beyond the tolerance.
DIFFERING_SHARE = 0.10

BASELINE_DIR = Path(__file__).resolve().parents[1] / "baselines" / "ui"


def baseline_path(theme: str) -> Path:
    """Path of the committed baseline of a theme."""
    return BASELINE_DIR / f"{theme}.png"


def update_requested() -> bool:
    """Whether the baselines shall be rewritten (env var of the regeneration)."""
    return os.environ.get("SONOFORGE_UPDATE_SCREENSHOTS", "").strip() not in {"", "0", "false"}


def build_probe(theme: str) -> QWidget:
    """The probe widget: a label, a line edit and a button of the real theme."""
    from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

    widget = QWidget()
    widget.setObjectName("screenshotProbe")
    widget.setStyleSheet(build_clinical_stylesheet(theme=theme))
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    label = QLabel("SonoForge")
    label.setObjectName("probeLabel")
    layout.addWidget(label)
    edit = QLineEdit()
    edit.setObjectName("probeEdit")
    # No focus: the focus styles (accent border) would depend on the focus of
    # the window and make the rendering non-deterministic.
    edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    layout.addWidget(edit)
    button = QPushButton("Актив")
    button.setObjectName("probeButton")
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    layout.addWidget(button)
    widget.resize(*PROBE_SIZE)
    widget.show()
    QApplication.processEvents()
    return widget


def render_probe(theme: str) -> QImage:
    """Render the probe of a theme and return the image."""
    widget = build_probe(theme)
    try:
        image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    finally:
        widget.close()
        widget.deleteLater()
    return image


def colour_histogram(image: QImage) -> Counter:
    """Counter of the colours of the image (``#rrggbb`` → pixels)."""
    counter: Counter = Counter()
    width, height = image.width(), image.height()
    for y in range(height):
        for x in range(width):
            counter[f"#{image.pixel(x, y) & 0xFFFFFF:06x}"] += 1
    return counter


def strong_colours(image: QImage, min_share: float = STRONG_SHARE) -> dict[str, float]:
    """Colours that cover at least *min_share* of the image → their share."""
    counter = colour_histogram(image)
    total = max(1, image.width() * image.height())
    return {colour: count / total for colour, count in counter.items() if count / total >= min_share}


def expected_colours(theme: str) -> set[str]:
    """Colours the probe may show: the tokens of the theme."""
    tokens = tokens_for(theme)
    return {
        value.lower()
        for name, value in tokens.items()
        if name in {"surface.1", "surface.2", "surface.3", "line.1", "line.2", "text.1", "accent"}
    }


def required_colours(theme: str) -> set[str]:
    """Colours the probe must show as a large area."""
    tokens = tokens_for(theme)
    return {tokens[name].lower() for name in ("surface.1", "surface.2", "surface.3")}


def text_colour(theme: str) -> str:
    """Colour of the primary text of the theme."""
    return tokens_for(theme)["text.1"].lower()


def blend_pairs(theme: str) -> list[tuple[str, str]]:
    """Pairs of theme colours the probe may mix (background and foreground)."""
    tokens = tokens_for(theme)
    return [
        (tokens["surface.1"], tokens["text.1"]),
        (tokens["surface.2"], tokens["text.1"]),
        (tokens["surface.3"], tokens["text.1"]),
        (tokens["surface.1"], tokens["surface.3"]),
        (tokens["surface.2"], tokens["surface.3"]),
        (tokens["line.1"], tokens["surface.1"]),
        (tokens["line.1"], tokens["surface.2"]),
        (tokens["line.1"], tokens["surface.3"]),
    ]


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def is_blend(colour: str, background: str, foreground: str, tolerance: int = 4) -> bool:
    """Whether *colour* is a mixture of *background* and *foreground*.

    The check does not depend on the font: the antialiasing of the glyphs
    produces exactly such mixtures.
    """
    pixel = _rgb(colour)
    back = _rgb(background)
    front = _rgb(foreground)
    deltas = [front[index] - back[index] for index in range(3)]
    pivot = max(range(3), key=lambda index: abs(deltas[index]))
    if deltas[pivot] == 0:
        return all(abs(pixel[index] - back[index]) <= tolerance for index in range(3))
    share = (pixel[pivot] - back[pivot]) / deltas[pivot]
    if share < -tolerance / max(1, abs(deltas[pivot])) or share > 1 + tolerance / max(1, abs(deltas[pivot])):
        return False
    for index in range(3):
        if abs(deltas[index]) <= tolerance:
            continue
        expected = back[index] + share * deltas[index]
        if abs(pixel[index] - expected) > tolerance:
            return False
    return True


def foreign_pixels(image: QImage, theme: str, tolerance: int = 4) -> list[str]:
    """Colours of the image that are no mixture of two colours of the theme."""
    pairs = blend_pairs(theme)
    foreign: list[str] = []
    for colour in colour_histogram(image):
        if any(is_blend(colour, background, foreground, tolerance) for background, foreground in pairs):
            continue
        foreign.append(colour)
    return foreign


def compare_images(
    current: QImage,
    baseline: QImage,
    *,
    max_channel_diff: int = CHANNEL_TOLERANCE,
    max_differing_share: float = DIFFERING_SHARE,
) -> list[str]:
    """Differences between the current rendering and the baseline (empty = same)."""
    problems: list[str] = []
    if (current.width(), current.height()) != (baseline.width(), baseline.height()):
        return [
            f"size {current.width()}x{current.height()} differs from the baseline "
            f"{baseline.width()}x{baseline.height()}"
        ]
    width, height = current.width(), current.height()
    differing = 0
    worst = 0
    for y in range(height):
        for x in range(width):
            left = current.pixel(x, y)
            right = baseline.pixel(x, y)
            diff = max(
                abs(((left >> 16) & 0xFF) - ((right >> 16) & 0xFF)),
                abs(((left >> 8) & 0xFF) - ((right >> 8) & 0xFF)),
                abs((left & 0xFF) - (right & 0xFF)),
            )
            worst = max(worst, diff)
            if diff > max_channel_diff:
                differing += 1
    share = differing / max(1, width * height)
    if share > max_differing_share:
        problems.append(f"{share:.1%} of the pixels differ from the baseline (limit {max_differing_share:.0%})")
    if worst > max_channel_diff:
        problems.append(f"the largest per-channel difference is {worst} (limit {max_channel_diff})")
    return problems


def save_baseline(image: QImage, theme: str) -> Path:
    """Write the baseline of a theme and return its path."""
    path = baseline_path(theme)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path), "PNG")
    return path


def load_baseline(theme: str) -> QImage | None:
    """Read the committed baseline of a theme (``None`` when there is none)."""
    path = baseline_path(theme)
    if not path.exists():
        return None
    image = QImage(str(path))
    if image.isNull():
        return None
    return image.convertToFormat(QImage.Format.Format_RGB32)
