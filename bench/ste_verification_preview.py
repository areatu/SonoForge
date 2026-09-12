"""Render the contour-verification figures for ``docs/STE_TRACKING_VERIFICATION.md``.

Produces:

* ``docs/screenshots/ste-tracking-verification-clean.png`` — 40 dB phantom, the
  round trip confirms nearly every node;
* ``docs/screenshots/ste-tracking-verification-noisy.png`` — 10 dB phantom, most
  nodes carry the "not confirmed" cross.

Nothing in the picture is placed by hand: the frames are the repository's own
kinematic phantom (``tests/fixtures/ste_phantom.py``), the positions come from the
production ``SpeckleTrackingWorker``, and the marks, their gate and the legend
text are the same calls ``presentation/viewer_widget.py`` makes for the frame on
screen (``strain.overlay_verification``).

The frames are drawn through :mod:`bench.render_utils`, which asks pyqtgraph for
``axisOrder="row-major"`` exactly like every product path does. Skipping that
argument does **not** raise: pyqtgraph's default reads a ``(rows, cols)`` array as
``(x, y)`` and quietly draws the myocardium transposed — contours correctly
placed, heart rotated by 90°. The first version of these two figures was made
that way, so the script now proves its own picture before writing it: the probe
in ``render_utils.verify_render_orientation`` fails the run instead of shipping a
transposed frame.

Usage::

    LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen \\
        ./.venv/bin/python bench/ste_verification_preview.py            # both figures
    ... bench/ste_verification_preview.py --variant clean --noise-db 30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
# ``tests/fixtures`` must win over the script's own directory: ``bench/ste_phantom.py``
# is the metrics harness, ``tests/fixtures/ste_phantom.py`` is the phantom itself.
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from render_utils import make_image_item, verify_render_orientation  # noqa: E402
from ste_phantom import StePhantom, StePhantomConfig  # noqa: E402

from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker  # noqa: E402
from echo_personal_tool.domain.models.speckle import SpeckleConfig  # noqa: E402
from echo_personal_tool.infrastructure.i18n import set_language, tr  # noqa: E402
from echo_personal_tool.presentation.speckle_overlay import SpeckleOverlay  # noqa: E402

SCREENSHOTS = ROOT / "docs" / "screenshots"

#: ``--variant`` → (output file, speckle SNR in dB). The dB values are the ones
#: the document quotes; the counts printed by the run go into the caption.
VARIANTS: dict[str, tuple[Path, float]] = {
    "clean": (SCREENSHOTS / "ste-tracking-verification-clean.png", 40.0),
    "noisy": (SCREENSHOTS / "ste-tracking-verification-noisy.png", 10.0),
}


def track_frames(config: StePhantomConfig) -> tuple[np.ndarray, object]:
    """Run the production worker over the phantom and return frames + result."""
    phantom = StePhantom(config)
    frames = phantom.frames()
    payload: dict[str, object] = {}
    worker = SpeckleTrackingWorker(
        frames=frames,
        zone=phantom.zone(),
        pixel_spacing=(config.pixel_spacing_mm, config.pixel_spacing_mm),
        frame_time_ms=config.frame_time_ms,
        manual_ed=0,
        manual_es=config.es_index,
        view="A4C",
        config=SpeckleConfig.preset_standard(),
    )
    worker.signals.finished.connect(lambda result: payload.setdefault("result", result))
    worker.signals.error.connect(lambda message: payload.setdefault("error", message))
    worker.run()
    if "error" in payload:
        raise RuntimeError(f"speckle worker failed: {payload['error']}")
    return frames, payload["result"]


def render_variant(variant: str, noise_db: float, size: int, language: str) -> int:
    """Draw one figure; return the number of nodes the round trip rejected."""
    import pyqtgraph as pg
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    set_language(language)

    config = StePhantomConfig.quick(noise_db=noise_db)
    frames, result = track_frames(config)

    frame = int(result.es_index)
    positions = np.asarray(result.tracked_positions_all[frame], dtype=np.float64)
    ncc = np.asarray(result.ncc_all_frames[frame], dtype=np.float64)
    valid = np.isfinite(ncc) & (ncc >= result.ncc_threshold)

    closure = np.asarray(result.closure_all_frames[frame], dtype=np.float64)
    rejected = np.isfinite(closure) & (closure > float(result.closure_gate_px))
    unverified = ~np.isfinite(closure)
    n_rejected, n_unverified = int(rejected.sum()), int(unverified.sum())
    legend = (
        tr("strain.overlay_verification", rejected=n_rejected, unverified=n_unverified)
        if (n_rejected or n_unverified)
        else ""
    )

    plot = pg.PlotWidget()
    plot.setBackground("k")
    plot.invertY(True)
    plot.setAspectLocked(True)
    plot.addItem(make_image_item(frames[frame]))

    overlay = SpeckleOverlay(plot)
    overlay.show_kernels(result.kernels, valid, ncc, positions=positions)
    overlay.show_verification_marks(positions, rejected, unverified, legend)

    height, width = frames.shape[1], frames.shape[2]
    plot.setXRange(0, width, padding=0)
    plot.setYRange(0, height, padding=0)
    plot.resize(size, size)
    plot.show()
    app.processEvents()

    out_path, _ = VARIANTS[variant]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plot.grab().save(str(out_path))
    plot.close()
    print(
        f"{variant}: {noise_db:.0f} dB, кадр {frame} (ES), узлов {positions.shape[0]}, "
        f"не подтверждено {n_rejected} ({100 * n_rejected / max(positions.shape[0], 1):.0f} %), "
        f"без вердикта {n_unverified} -> {out_path.relative_to(ROOT)}"
    )
    return n_rejected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=(*VARIANTS, "all"), default="all")
    parser.add_argument("--noise-db", type=float, default=None, help="override the variant's SNR")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--language", default="en", choices=("ru", "en"))
    parser.add_argument("--skip-orientation-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_orientation_check:
        verify_render_orientation()
        print("orientation probe: кадр не транспонирован относительно координат оверлея")

    selected = list(VARIANTS) if args.variant == "all" else [args.variant]
    for variant in selected:
        noise_db = args.noise_db if args.noise_db is not None else VARIANTS[variant][1]
        render_variant(variant, noise_db, args.size, args.language)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
