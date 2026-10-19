"""QPdfView layout model of the report preview (UI-4 PR-1, spike UI-4.0 §4).

``layout_pages`` reproduces ``QPdfViewPrivate::calculateDocumentLayout``
(Qt 6.11) as a pure function; the spike verified the same maths against the
real widget pixel-by-pixel (``tools/report_preview_spike/hover_probe.py``).
These cases pin the formulas with hand-computed expectations — including the
two quirks that make a naive model wrong: FitInView budgets the height with
the page spacing (not the margins), and page sizes go through C++ ``qRound``
(half away from zero), not Python's banker's rounding.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.measurement_report_pdf import PageRect
from echo_personal_tool.presentation.report_mode.view_map import (
    ZOOM_CUSTOM,
    ZOOM_FIT_IN_VIEW,
    ZOOM_FIT_WIDTH,
    PageGeometry,
    ViewLayout,
    hit_test_anchors,
    layout_pages,
    viewport_point_to_page_pt,
)

# A page of round points keeps every expectation checkable by hand.
_PAGE = (600.0, 800.0)


def _view(**overrides) -> ViewLayout:
    base = {
        "viewport_w": 1000,
        "viewport_h": 1200,
        "margin_left": 20,
        "margin_top": 10,
        "margin_right": 20,
        "page_spacing": 6,
    }
    base.update(overrides)
    return ViewLayout(**base)  # type: ignore[arg-type]


class TestLayoutPages:
    def test_fit_to_width_scales_the_page_to_the_viewport_minus_side_margins(self) -> None:
        geoms = layout_pages(_view(zoom_mode=ZOOM_FIT_WIDTH), [_PAGE], screen_res=1.0)
        assert len(geoms) == 1
        geom = geoms[0]
        # (1000 - 20 - 20) / 600 = 1.6; the page is centred in 1000 px total width.
        assert (geom.w, geom.h) == (960, 1280)
        assert geom.scale == pytest.approx(1.6)
        assert (geom.x, geom.y) == (20, 10)
        assert (geom.pt_w, geom.pt_h) == pytest.approx((600.0, 800.0))

    def test_pages_stack_from_the_top_margin_with_the_page_spacing(self) -> None:
        geoms = layout_pages(_view(zoom_mode=ZOOM_FIT_WIDTH), [_PAGE, _PAGE], screen_res=1.0)
        assert [geom.page for geom in geoms] == [0, 1]
        assert geoms[1].y == 10 + 1280 + 6

    def test_each_page_fits_its_own_width(self) -> None:
        geoms = layout_pages(
            _view(zoom_mode=ZOOM_FIT_WIDTH), [_PAGE, (300.0, 800.0)], screen_res=1.0
        )
        assert geoms[0].scale == pytest.approx(1.6)
        assert geoms[1].scale == pytest.approx(3.2)
        assert (geoms[1].w, geoms[1].h) == (960, 2560)
        assert geoms[1].y == 10 + 1280 + 6

    def test_fit_in_view_budgets_height_with_spacing_not_margins(self) -> None:
        geoms = layout_pages(
            _view(viewport_h=900, zoom_mode=ZOOM_FIT_IN_VIEW), [_PAGE], screen_res=1.0
        )
        geom = geoms[0]
        # factor = min(960/600, (900-6)/800) = 1.1175 — the height wins, and
        # 600 * 1.1175 = 670.5 rounds to 671 (qRound, half away from zero).
        assert (geom.w, geom.h) == (671, 894)
        assert geom.h == 900 - 6
        assert geom.scale == pytest.approx(671 / 600)

    def test_custom_zoom_multiplies_points_by_screen_res_and_factor(self) -> None:
        geoms = layout_pages(
            _view(zoom_mode=ZOOM_CUSTOM, zoom_factor=2.0), [_PAGE], screen_res=1.5
        )
        geom = geoms[0]
        assert (geom.w, geom.h) == (1800, 2400)
        assert geom.scale == pytest.approx(3.0)
        # Wider than the viewport: centring runs over the total width.
        assert geom.x == 20

    def test_scroll_offsets_every_page(self) -> None:
        geoms = layout_pages(
            _view(zoom_mode=ZOOM_FIT_WIDTH, scroll_x=30, scroll_y=120),
            [_PAGE, _PAGE],
            screen_res=1.0,
        )
        assert (geoms[0].x, geoms[0].y) == (20 - 30, 10 - 120)
        assert geoms[1].y == 10 + 1280 + 6 - 120

    def test_single_page_mode_lays_out_only_the_current_page_at_the_top(self) -> None:
        geoms = layout_pages(
            _view(zoom_mode=ZOOM_FIT_WIDTH, single_page=True, current_page=1),
            [_PAGE, _PAGE, _PAGE],
            screen_res=1.0,
        )
        assert [geom.page for geom in geoms] == [1]
        assert geoms[0].y == 10

    def test_single_page_with_a_stale_current_page_falls_back_to_the_first(self) -> None:
        geoms = layout_pages(
            _view(single_page=True, current_page=99), [_PAGE, _PAGE], screen_res=1.0
        )
        assert [geom.page for geom in geoms] == [0]

    def test_an_empty_document_lays_out_to_nothing(self) -> None:
        assert layout_pages(_view(), [], screen_res=1.0) == []

    def test_an_unknown_zoom_mode_uses_the_fit_in_view_branch_like_qt(self) -> None:
        fitted = layout_pages(_view(viewport_h=900, zoom_mode=ZOOM_FIT_IN_VIEW), [_PAGE], screen_res=1.0)
        unknown = layout_pages(_view(viewport_h=900, zoom_mode="bogus"), [_PAGE], screen_res=1.0)
        assert unknown == fitted


class TestPointMapping:
    def test_viewport_point_maps_back_to_page_points(self) -> None:
        geom = PageGeometry(page=0, x=20, y=10, w=960, h=1280, scale=1.6)
        assert viewport_point_to_page_pt(geom, 20 + 480, 10 + 640) == pytest.approx((300.0, 400.0))
        assert viewport_point_to_page_pt(geom, 20, 10) == (0.0, 0.0)

    def test_contains_pt_forgives_the_tolerance_on_every_edge(self) -> None:
        geom = PageGeometry(page=0, x=0, y=0, w=600, h=800, scale=1.0)
        assert geom.contains_pt(-2.0, 802.0, tolerance_pt=2.0)
        assert not geom.contains_pt(-2.5, 400.0, tolerance_pt=2.0)
        assert not geom.contains_pt(300.0, 802.5, tolerance_pt=2.0)


class TestHitTestAnchors:
    _GEOM = PageGeometry(page=0, x=20, y=10, w=960, h=1280, scale=1.6)
    _ANCHORS = {(0, 1): [PageRect(page=0, x=100.0, y=50.0, w=80.0, h=12.0)]}

    def test_the_centre_of_a_cell_hits_its_value(self) -> None:
        x = 20 + 140 * 1.6
        y = 10 + 56 * 1.6
        assert hit_test_anchors([self._GEOM], x, y, self._ANCHORS) == (0, 1)

    def test_a_point_on_the_page_but_outside_every_cell_misses(self) -> None:
        assert hit_test_anchors([self._GEOM], 20 + 300 * 1.6, 10 + 400 * 1.6, self._ANCHORS) is None

    def test_a_point_outside_the_page_misses(self) -> None:
        assert hit_test_anchors([self._GEOM], 5, 5, self._ANCHORS, tolerance_pt=2.0) is None

    def test_tolerance_covers_the_cell_edge_but_no_further(self) -> None:
        # Exactly 2 pt left of the cell still counts; 2.5 pt does not.
        y = 10 + 56 * 1.6
        assert hit_test_anchors([self._GEOM], 20 + 98 * 1.6, y, self._ANCHORS) == (0, 1)
        assert hit_test_anchors([self._GEOM], 20 + 97.5 * 1.6, y, self._ANCHORS) is None

    def test_rectangles_of_other_pages_do_not_hit(self) -> None:
        anchors = {(1, 0): [PageRect(page=1, x=100.0, y=50.0, w=80.0, h=12.0)]}
        assert hit_test_anchors([self._GEOM], 20 + 140 * 1.6, 10 + 56 * 1.6, anchors) is None

    def test_no_geometry_or_no_anchors_means_no_hit(self) -> None:
        assert hit_test_anchors([], 100, 100, self._ANCHORS) is None
        assert hit_test_anchors([self._GEOM], 100, 100, {}) is None
