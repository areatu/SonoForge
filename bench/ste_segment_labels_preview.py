"""Render the cine segment labels on the kinematic phantom (doc illustration).

Produces ``docs/screenshots/ste-segment-labels.png``: the overlay with the short
segment names next to the walls they measure — the vendor convention from
``docs/STE_IMPROVEMENT_PLAN.md`` §5.3 п.4 (Samsung's «БазПерг/СрЛат» on the
image).

Nothing in the picture is placed by hand: the image is the repository's own
kinematic phantom (``tests/fixtures/ste_phantom.py``), the node positions are its
ground-truth endocardial arc at end diastole, and the segment ids come from the
production assignment ``assign_segments_from_arc`` — the same call the analysis
worker makes.

The frame goes through :mod:`bench.render_utils` (``axisOrder="row-major"``, as
every product path does) and the run self-checks the orientation before writing:
without the explicit axis order pyqtgraph transposes a ``(rows, cols)`` frame, and
the first version of this figure showed the labels and contours correctly placed
over a myocardium rotated by 90°.

Usage::

    LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen \\
        python bench/ste_segment_labels_preview.py [--out docs/screenshots/ste-segment-labels.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from render_utils import make_image_item, verify_render_orientation  # noqa: E402
from ste_phantom import StePhantom, StePhantomConfig  # noqa: E402

from echo_personal_tool.domain.models.speckle import TrackingKernel  # noqa: E402
from echo_personal_tool.domain.services.segment_map import assign_segments_from_arc  # noqa: E402
from echo_personal_tool.infrastructure.i18n import set_language  # noqa: E402
from echo_personal_tool.presentation.speckle_overlay import SpeckleOverlay  # noqa: E402

DEFAULT_OUT = ROOT / "docs" / "screenshots" / "ste-segment-labels.png"
NODE_COUNT = 36


def render(out_path: Path, language: str = "ru", scale: int = 2) -> int:
    """Draw the overlay and return the number of segment labels placed."""
    import pyqtgraph as pg
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    config = StePhantomConfig(noise_db=20.0, decorrelation=0.2)
    phantom = StePhantom(config)
    frames = phantom.frames()
    ed_index = 0
    reference = phantom.reference_endo_arc(NODE_COUNT)
    positions_ed = phantom.deform(reference, ed_index)
    positions_es = phantom.deform(reference, config.es_index)
    assignment = assign_segments_from_arc(reference, "A4C")

    kernels = [
        TrackingKernel(
            center=(float(point[0]), float(point[1])),
            radius=5,
            node_index=i,
            layer="endo",
            aha_segment=int(assignment.node_segments[i]),
            arc_length_param=float(assignment.arc_params[i]),
        )
        for i, point in enumerate(positions_ed)
    ]

    plot = pg.PlotWidget()
    plot.setBackground("k")
    plot.hideAxis("left")
    plot.hideAxis("bottom")
    plot.invertY(True)
    plot.setAspectLocked(True)
    plot.addItem(make_image_item(frames[ed_index]))

    plot.setXRange(0, config.width, padding=0)
    plot.setYRange(0, config.height, padding=0)

    set_language(language)
    overlay = SpeckleOverlay(plot)
    overlay.show_phase_contours(positions_ed, positions_es)
    overlay.show_kernels(
        kernels,
        ncc_scores=np.full(len(kernels), 0.85),
        valid_mask=np.ones(len(kernels), bool),
        positions=positions_ed,
    )
    drawn = overlay.show_segment_labels(kernels, positions_ed)

    plot.resize(scale * config.width, scale * config.height)
    plot.show()
    app.processEvents()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plot.grab().save(str(out_path))
    return drawn


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--language", default="ru", choices=("ru", "en"))
    parser.add_argument("--scale", type=int, default=2)
    args = parser.parse_args()

    verify_render_orientation()
    drawn = render(args.out, language=args.language, scale=args.scale)
    print(f"segment labels drawn: {drawn} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
