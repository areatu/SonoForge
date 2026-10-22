"""Guard the figure renderers against the transposed-frame defect.

The STE verification figures once shipped with correctly placed contours over a
myocardium rotated by 90°: ``pg.ImageItem`` defaults to ``axisOrder="col-major"``,
so a ``(rows, cols)`` frame drawn without an explicit ``axisOrder`` is transposed
with respect to the overlay coordinates — and nothing raises, because both are
"valid" pictures. ``bench/render_utils.py`` renders in the application's
convention and carries a probe that fails instead of shipping such a figure.

These tests keep that guard alive: the helper must keep image coordinates, the
probe must really catch the default axis order, and no bench script may build a
frame item without the helper.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench import render_utils  # noqa: E402


class TestImageItemsKeepImageCoordinates:
    def test_row_major_item_puts_the_probe_where_image_coordinates_say(self, qapp_session, tmp_path: Path) -> None:
        """A mark at rows 20-30 / cols 70-80 must land in the upper right."""
        path = render_utils.render_probe(str(tmp_path / "probe.png"))
        fx, fy = render_utils.check_orientation(path)
        assert abs(fx - render_utils.PROBE_EXPECTED[0]) < render_utils.PROBE_TOLERANCE
        assert abs(fy - render_utils.PROBE_EXPECTED[1]) < render_utils.PROBE_TOLERANCE

    def test_make_image_item_matches_the_application_axis_order(self) -> None:
        """Product paths ask for row-major; the helper must do the same."""
        item = render_utils.make_image_item(render_utils.probe_frame())
        assert item.axisOrder == "row-major"

    def test_helper_rect_defaults_to_the_frame_size(self) -> None:
        frame = render_utils.probe_frame()
        item = render_utils.make_image_item(frame)
        rect = item.boundingRect()
        assert (rect.height(), rect.width()) == frame.shape[:2]


class TestProbeCatchesThePitfall:
    def test_default_axis_order_is_reported_as_transposed(self, qapp_session, tmp_path: Path) -> None:
        """Negative control: the defect that shipped must fail the probe."""
        path = render_utils.render_probe(str(tmp_path / "transposed.png"), row_major=False)
        with pytest.raises(RuntimeError, match="convention"):
            render_utils.check_orientation(path)

    def test_verify_render_orientation_accepts_the_helper(self, qapp_session, tmp_path: Path) -> None:
        render_utils.verify_render_orientation(str(tmp_path / "selfcheck.png"))


class TestNoBenchScriptBypassesTheHelper:
    """A script that builds ``pg.ImageItem(...)`` directly silently transposes."""

    def test_bench_scripts_use_the_helper(self) -> None:
        offenders: list[str] = []
        for script in sorted((ROOT / "bench").rglob("*.py")):
            if script.name == "render_utils.py":
                continue  # the helper itself, and its negative control
            for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), start=1):
                if "ImageItem(" not in line or "axisOrder" in line:
                    continue
                if "orientation-ok" in line:  # explicit, reviewed exception
                    continue
                offenders.append(f"{script.relative_to(ROOT)}:{number}: {line.strip()}")
        assert not offenders, (
            "bench scripts must render frames through render_utils.make_image_item "
            "(axisOrder='row-major'), otherwise the figure is transposed:\n" + "\n".join(offenders)
        )
