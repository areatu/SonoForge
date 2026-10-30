"""Unit tests for pure window-chrome hit-testing and Win32 message translation (UI-1 PR-1).

Covers spec ``2026-10-16-ui-redesign-spec-plan-ru.md`` §4.3, §8.3, §10, §11:
- all 13 :class:`Zone` values in normal and maximized states,
- interactive controls inside the caption always resolving to ``Zone.CLIENT``,
- 100 %, 150 %, and 200 % DPI scale factors,
- ``Qt.Edge`` and resize cursor mappings for non-Windows platforms,
- Win32 ``Zone -> HT*`` translation, ``WM_NCCALCSIZE``, ``WM_NCHITTEST``
  (including ``HTMAXBUTTON`` for Windows 11 Snap Layouts), non-client button
  hover/press/release/leave messages, and DWM dark/rounded-corner attributes.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field

import pytest
from PySide6.QtCore import QByteArray, QPoint, QRect, QSize, Qt

from echo_personal_tool.presentation.window_chrome import (
    BUTTON_ZONES,
    CHROME_WINDOW_STYLE_MASK,
    DEFAULT_RESIZE_BORDER_PX,
    DWMWA_USE_IMMERSIVE_DARK_MODE,
    DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
    DWMWA_WINDOW_CORNER_PREFERENCE,
    DWMWCP_DEFAULT,
    DWMWCP_ROUND,
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
    HTCAPTION,
    HTCLIENT,
    HTCLOSE,
    HTLEFT,
    HTMAXBUTTON,
    HTMINBUTTON,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    MSG,
    NCCALCSIZE_PARAMS,
    RECT,
    RESIZE_ZONES,
    WM_NCCALCSIZE,
    WM_NCHITTEST,
    WM_NCLBUTTONDOWN,
    WM_NCLBUTTONUP,
    WM_NCMOUSELEAVE,
    WM_NCMOUSEMOVE,
    ZONE_TO_HT,
    Win32Chrome,
    Zone,
    hit_test,
    pack_lparam_point,
    resize_border_for_scale,
    restore_maximized_geometry_for_drag,
    scale_point,
    scale_rect,
    scale_size,
    unpack_lparam_point,
    zone_to_cursor_shape,
    zone_to_ht,
    zone_to_qt_edges,
)


def _standard_chrome_layout() -> tuple[QSize, QRect, dict[Zone, QRect], list[QRect]]:
    """1280×800 window with a 38 px title bar, 3×46 px window controls, and interactive areas."""
    window = QSize(1280, 800)
    caption = QRect(0, 0, 1280, 38)
    buttons = {
        Zone.MIN: QRect(1142, 0, 46, 38),
        Zone.MAX: QRect(1188, 0, 46, 38),
        Zone.CLOSE: QRect(1234, 0, 46, 38),
    }
    interactive = [
        QRect(8, 5, 32, 28),  # logo menu button
        QRect(48, 4, 420, 30),  # tab strip
        QRect(560, 5, 280, 28),  # Ctrl+K command field
    ]
    return window, caption, buttons, interactive


class TestZoneEnum:
    def test_zone_members_match_spec_contract(self) -> None:
        expected = [
            "CLIENT",
            "CAPTION",
            "MIN",
            "MAX",
            "CLOSE",
            "LEFT",
            "RIGHT",
            "TOP",
            "BOTTOM",
            "TOP_LEFT",
            "TOP_RIGHT",
            "BOTTOM_LEFT",
            "BOTTOM_RIGHT",
        ]
        assert [z.name for z in Zone] == expected

    def test_resize_and_button_zone_sets_are_disjoint(self) -> None:
        assert len(RESIZE_ZONES) == 8
        assert len(BUTTON_ZONES) == 3
        assert RESIZE_ZONES.isdisjoint(BUTTON_ZONES)
        assert Zone.CLIENT not in RESIZE_ZONES | BUTTON_ZONES
        assert Zone.CAPTION not in RESIZE_ZONES | BUTTON_ZONES


class TestHitTestAllZones:
    @pytest.mark.parametrize(
        ("point", "expected"),
        [
            # 4 corners (within 6 px of both adjacent edges)
            (QPoint(0, 0), Zone.TOP_LEFT),
            (QPoint(5, 5), Zone.TOP_LEFT),
            (QPoint(1279, 0), Zone.TOP_RIGHT),
            (QPoint(1274, 5), Zone.TOP_RIGHT),
            (QPoint(0, 799), Zone.BOTTOM_LEFT),
            (QPoint(5, 794), Zone.BOTTOM_LEFT),
            (QPoint(1279, 799), Zone.BOTTOM_RIGHT),
            (QPoint(1274, 794), Zone.BOTTOM_RIGHT),
            # 4 edges
            (QPoint(0, 400), Zone.LEFT),
            (QPoint(5, 20), Zone.LEFT),
            (QPoint(1279, 400), Zone.RIGHT),
            (QPoint(1274, 20), Zone.RIGHT),
            (QPoint(500, 0), Zone.TOP),
            (QPoint(500, 5), Zone.TOP),
            (QPoint(1200, 3), Zone.TOP),  # top 6 px above MAX button is still resize TOP
            (QPoint(500, 799), Zone.BOTTOM),
            (QPoint(500, 794), Zone.BOTTOM),
            # Caption control buttons (below the 6 px top resize border)
            (QPoint(1160, 18), Zone.MIN),
            (QPoint(1210, 18), Zone.MAX),
            (QPoint(1255, 18), Zone.CLOSE),
            # Interactive controls inside the caption always resolve to CLIENT
            (QPoint(20, 18), Zone.CLIENT),  # logo button
            (QPoint(200, 18), Zone.CLIENT),  # tab strip
            (QPoint(700, 18), Zone.CLIENT),  # command field
            # Empty space inside the caption resolves to CAPTION
            (QPoint(500, 6), Zone.CAPTION),
            (QPoint(500, 20), Zone.CAPTION),
            (QPoint(950, 20), Zone.CAPTION),
            # Main client area below the caption
            (QPoint(6, 38), Zone.CLIENT),
            (QPoint(640, 400), Zone.CLIENT),
            (QPoint(1273, 793), Zone.CLIENT),
        ],
    )
    def test_normal_window_zones(self, point: QPoint, expected: Zone) -> None:
        window, caption, buttons, interactive = _standard_chrome_layout()
        result = hit_test(
            point,
            window,
            border=DEFAULT_RESIZE_BORDER_PX,
            caption=caption,
            buttons=buttons,
            interactive=interactive,
            maximized=False,
        )
        assert result is expected

    @pytest.mark.parametrize(
        "out_of_bounds",
        [
            QPoint(-1, 10),
            QPoint(10, -1),
            QPoint(1280, 10),
            QPoint(10, 800),
            QPoint(-50, -50),
        ],
    )
    def test_points_outside_window_return_client(self, out_of_bounds: QPoint) -> None:
        window, caption, buttons, interactive = _standard_chrome_layout()
        assert (
            hit_test(
                out_of_bounds,
                window,
                border=DEFAULT_RESIZE_BORDER_PX,
                caption=caption,
                buttons=buttons,
                interactive=interactive,
                maximized=False,
            )
            is Zone.CLIENT
        )

    def test_empty_window_size_returns_client(self) -> None:
        assert (
            hit_test(
                QPoint(0, 0),
                QSize(0, 0),
                border=6,
                caption=QRect(0, 0, 100, 38),
                buttons={},
                interactive=[],
                maximized=False,
            )
            is Zone.CLIENT
        )


class TestHitTestMaximized:
    def test_maximized_disables_all_resize_borders_and_corners(self) -> None:
        window, caption, buttons, interactive = _standard_chrome_layout()
        # Top edge in empty caption space becomes draggable CAPTION, not TOP
        assert (
            hit_test(
                QPoint(500, 0),
                window,
                border=DEFAULT_RESIZE_BORDER_PX,
                caption=caption,
                buttons=buttons,
                interactive=interactive,
                maximized=True,
            )
            is Zone.CAPTION
        )
        # Top-right corner pixel (1279, 0) lands directly on the CLOSE button (Fitts's law)
        assert (
            hit_test(
                QPoint(1279, 0),
                window,
                border=DEFAULT_RESIZE_BORDER_PX,
                caption=caption,
                buttons=buttons,
                interactive=interactive,
                maximized=True,
            )
            is Zone.CLOSE
        )
        # Top edge over MAX button lands on MAX (Snap Layouts at y=0 when maximized)
        assert (
            hit_test(
                QPoint(1210, 0),
                window,
                border=DEFAULT_RESIZE_BORDER_PX,
                caption=caption,
                buttons=buttons,
                interactive=interactive,
                maximized=True,
            )
            is Zone.MAX
        )
        # Left, right, bottom edges and bottom corners become CLIENT when maximized
        for pt in (
            QPoint(0, 400),
            QPoint(1279, 400),
            QPoint(640, 799),
            QPoint(0, 799),
            QPoint(1279, 799),
        ):
            assert (
                hit_test(
                    pt,
                    window,
                    border=DEFAULT_RESIZE_BORDER_PX,
                    caption=caption,
                    buttons=buttons,
                    interactive=interactive,
                    maximized=True,
                )
                is Zone.CLIENT
            )


class TestHitTestScaling:
    @pytest.mark.parametrize(
        ("scale", "expected_border"),
        [
            (100, 6),
            (150, 9),
            (200, 12),
            (1.0, 6),
            (1.5, 9),
            (2.0, 12),
        ],
    )
    def test_resize_border_for_scale(self, scale: float | int, expected_border: int) -> None:
        assert resize_border_for_scale(scale) == expected_border

    @pytest.mark.parametrize("scale_percent", [100, 150, 200])
    def test_all_zones_consistent_across_100_150_200_percent(self, scale_percent: int) -> None:
        base_win, base_caption, base_buttons, base_interactive = _standard_chrome_layout()
        border = resize_border_for_scale(scale_percent)
        win = scale_size(base_win, scale_percent)
        caption = scale_rect(base_caption, scale_percent)
        buttons = {z: scale_rect(r, scale_percent) for z, r in base_buttons.items()}
        interactive = [scale_rect(r, scale_percent) for r in base_interactive]

        # Border transition: border - 1 is TOP/LEFT, border is CAPTION
        assert (
            hit_test(
                QPoint(scale_point(QPoint(500, 0), scale_percent).x(), border - 1),
                win,
                border=border,
                caption=caption,
                buttons=buttons,
                interactive=interactive,
                maximized=False,
            )
            is Zone.TOP
        )
        assert (
            hit_test(
                QPoint(scale_point(QPoint(500, 0), scale_percent).x(), border),
                win,
                border=border,
                caption=caption,
                buttons=buttons,
                interactive=interactive,
                maximized=False,
            )
            is Zone.CAPTION
        )

        probes = [
            (QPoint(2, 2), Zone.TOP_LEFT),
            (QPoint(1277, 2), Zone.TOP_RIGHT),
            (QPoint(2, 797), Zone.BOTTOM_LEFT),
            (QPoint(1277, 797), Zone.BOTTOM_RIGHT),
            (QPoint(2, 400), Zone.LEFT),
            (QPoint(1277, 400), Zone.RIGHT),
            (QPoint(500, 2), Zone.TOP),
            (QPoint(500, 797), Zone.BOTTOM),
            (QPoint(1160, 20), Zone.MIN),
            (QPoint(1210, 20), Zone.MAX),
            (QPoint(1255, 20), Zone.CLOSE),
            (QPoint(200, 20), Zone.CLIENT),
            (QPoint(700, 20), Zone.CLIENT),
            (QPoint(500, 20), Zone.CAPTION),
            (QPoint(640, 400), Zone.CLIENT),
        ]
        for base_pt, expected_zone in probes:
            scaled_pt = scale_point(base_pt, scale_percent)
            actual = hit_test(
                scaled_pt,
                win,
                border=border,
                caption=caption,
                buttons=buttons,
                interactive=interactive,
                maximized=False,
            )
            assert actual is expected_zone, f"scale={scale_percent}% point={base_pt}->{scaled_pt}"


class TestQtEdgesAndRestoreGeometry:
    def test_zone_to_qt_edges_covers_all_eight_resize_zones(self) -> None:
        assert zone_to_qt_edges(Zone.LEFT) == Qt.Edge.LeftEdge
        assert zone_to_qt_edges(Zone.RIGHT) == Qt.Edge.RightEdge
        assert zone_to_qt_edges(Zone.TOP) == Qt.Edge.TopEdge
        assert zone_to_qt_edges(Zone.BOTTOM) == Qt.Edge.BottomEdge
        assert zone_to_qt_edges(Zone.TOP_LEFT) == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge)
        assert zone_to_qt_edges(Zone.TOP_RIGHT) == (Qt.Edge.TopEdge | Qt.Edge.RightEdge)
        assert zone_to_qt_edges(Zone.BOTTOM_LEFT) == (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge)
        assert zone_to_qt_edges(Zone.BOTTOM_RIGHT) == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
        for non_resize in (Zone.CLIENT, Zone.CAPTION, Zone.MIN, Zone.MAX, Zone.CLOSE):
            assert zone_to_qt_edges(non_resize) == Qt.Edge(0)

    def test_zone_to_cursor_shape(self) -> None:
        assert zone_to_cursor_shape(Zone.LEFT) == Qt.CursorShape.SizeHorCursor
        assert zone_to_cursor_shape(Zone.RIGHT) == Qt.CursorShape.SizeHorCursor
        assert zone_to_cursor_shape(Zone.TOP) == Qt.CursorShape.SizeVerCursor
        assert zone_to_cursor_shape(Zone.BOTTOM) == Qt.CursorShape.SizeVerCursor
        assert zone_to_cursor_shape(Zone.TOP_LEFT) == Qt.CursorShape.SizeFDiagCursor
        assert zone_to_cursor_shape(Zone.BOTTOM_RIGHT) == Qt.CursorShape.SizeFDiagCursor
        assert zone_to_cursor_shape(Zone.TOP_RIGHT) == Qt.CursorShape.SizeBDiagCursor
        assert zone_to_cursor_shape(Zone.BOTTOM_LEFT) == Qt.CursorShape.SizeBDiagCursor
        for non_resize in (Zone.CLIENT, Zone.CAPTION, Zone.MIN, Zone.MAX, Zone.CLOSE):
            assert zone_to_cursor_shape(non_resize) is None

    def test_restore_maximized_geometry_for_drag_centers_proportionally_under_cursor(self) -> None:
        max_geo = QRect(0, 0, 1920, 1040)
        normal_size = QSize(1200, 800)
        cursor = QPoint(960, 18)  # 50 % across maximized width
        restored = restore_maximized_geometry_for_drag(max_geo, normal_size, cursor)
        assert restored.size() == normal_size
        assert restored.x() == 960 - 600
        assert restored.y() == 0
        assert restored.contains(cursor)


# ── Fake window & Win32 API for cross-platform Win32Chrome testing ────


@dataclass
class _FakeButton:
    down: bool = False
    hovered: bool = False
    clicks: int = 0

    def setAttribute(self, _attr: object, on: bool) -> None:  # noqa: N802
        self.hovered = bool(on)

    def setProperty(self, name: str, value: bool) -> None:  # noqa: N802
        assert name == "nativeHovered"
        self.hovered = value

    def style(self):
        return self

    def unpolish(self, _button: object) -> None:
        pass

    def polish(self, _button: object) -> None:
        pass

    def _on_enter(self) -> None:
        self.hovered = True

    def _on_leave(self) -> None:
        self.hovered = False

    def update(self) -> None:
        pass

    def setDown(self, down: bool) -> None:  # noqa: N802
        self.down = bool(down)

    def click(self) -> None:
        self.clicks += 1


@dataclass
class _FakeWindow:
    window_size: QSize = field(default_factory=lambda: QSize(1280, 800))
    maximized: bool = False
    dpr: float = 1.0
    hwnd: int = 0x1234

    def winId(self) -> int:  # noqa: N802
        return self.hwnd

    def size(self) -> QSize:
        return self.window_size

    def isMaximized(self) -> bool:  # noqa: N802
        return self.maximized

    def devicePixelRatioF(self) -> float:  # noqa: N802
        return self.dpr

    def mapToGlobal(self, pt: QPoint) -> QPoint:  # noqa: N802
        return pt


@dataclass
class _FakeWin32Api:
    style: int = 0
    frame_notified: int = 0
    dwm_attributes: dict[int, int] = field(default_factory=dict)
    fail_dwm_attrs: set[int] = field(default_factory=set)
    margins: tuple[int, int, int, int] | None = None
    zoomed: bool = False
    padding: tuple[int, int] = (8, 8)
    client_origin: tuple[int, int] = (0, 0)
    tracked_leave: int = 0

    def get_window_style(self, hwnd: int) -> int:
        del hwnd
        return self.style

    def set_window_style(self, hwnd: int, style: int) -> int:
        del hwnd
        prev = self.style
        self.style = style
        return prev

    def notify_frame_changed(self, hwnd: int) -> bool:
        del hwnd
        self.frame_notified += 1
        return True

    def set_dwm_attribute(self, hwnd: int, attribute: int, value: int) -> int:
        del hwnd
        if attribute in self.fail_dwm_attrs:
            return -1
        self.dwm_attributes[attribute] = value
        return 0

    def extend_frame_into_client_area(self, hwnd: int, margins: tuple[int, int, int, int]) -> int:
        del hwnd
        self.margins = margins
        return 0

    def is_zoomed(self, hwnd: int) -> bool:
        del hwnd
        return self.zoomed

    def frame_padding(self, hwnd: int) -> tuple[int, int]:
        del hwnd
        return self.padding

    def screen_to_client(self, hwnd: int, screen_x: int, screen_y: int) -> tuple[int, int] | None:
        del hwnd
        return screen_x - self.client_origin[0], screen_y - self.client_origin[1]

    def track_nonclient_mouse_leave(self, hwnd: int) -> bool:
        del hwnd
        self.tracked_leave += 1
        return True


class TestWin32Chrome:
    def test_zone_to_ht_covers_every_zone(self) -> None:
        expected = {
            Zone.CLIENT: HTCLIENT,
            Zone.CAPTION: HTCAPTION,
            Zone.MIN: HTMINBUTTON,
            Zone.MAX: HTMAXBUTTON,
            Zone.CLOSE: HTCLOSE,
            Zone.LEFT: HTLEFT,
            Zone.RIGHT: HTRIGHT,
            Zone.TOP: HTTOP,
            Zone.BOTTOM: HTBOTTOM,
            Zone.TOP_LEFT: HTTOPLEFT,
            Zone.TOP_RIGHT: HTTOPRIGHT,
            Zone.BOTTOM_LEFT: HTBOTTOMLEFT,
            Zone.BOTTOM_RIGHT: HTBOTTOMRIGHT,
        }
        assert ZONE_TO_HT == expected
        for zone, code in expected.items():
            assert zone_to_ht(zone) == code

    @pytest.mark.parametrize("coords", [(0, 0), (1210, 18), (-1920, -400), (3839, 2159)])
    def test_lparam_point_pack_and_unpack_signed_coordinates(self, coords: tuple[int, int]) -> None:
        packed = pack_lparam_point(*coords)
        assert unpack_lparam_point(packed) == coords

    def test_install_applies_window_styles_and_dwm_attributes(self) -> None:
        win = _FakeWindow()
        api = _FakeWin32Api()
        _, caption, buttons, interactive = _standard_chrome_layout()
        chrome = Win32Chrome(
            win,  # type: ignore[arg-type]
            geometry_provider=lambda: (caption, buttons, interactive),
            api=api,
        )
        assert chrome.install(dark=True, round_corners=True) is True
        assert (api.style & CHROME_WINDOW_STYLE_MASK) == CHROME_WINDOW_STYLE_MASK
        assert api.frame_notified == 1
        assert api.dwm_attributes[DWMWA_USE_IMMERSIVE_DARK_MODE] == 1
        assert api.dwm_attributes[DWMWA_WINDOW_CORNER_PREFERENCE] == DWMWCP_ROUND
        assert api.margins == (0, 0, 0, 1)

    def test_dwm_dark_mode_falls_back_to_attribute_19_on_older_win10(self) -> None:
        win = _FakeWindow()
        api = _FakeWin32Api(fail_dwm_attrs={DWMWA_USE_IMMERSIVE_DARK_MODE})
        _, caption, buttons, interactive = _standard_chrome_layout()
        chrome = Win32Chrome(
            win,  # type: ignore[arg-type]
            geometry_provider=lambda: (caption, buttons, interactive),
            api=api,
        )
        chrome.apply_dwm_attributes(win.hwnd, dark=False, round_corners=False)
        assert api.dwm_attributes[DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1] == 0
        assert api.dwm_attributes[DWMWA_WINDOW_CORNER_PREFERENCE] == DWMWCP_DEFAULT

    def test_wm_nccalcsize_strips_frame_and_insets_when_maximized(self) -> None:
        win = _FakeWindow()
        api = _FakeWin32Api(zoomed=False, padding=(8, 8))
        _, caption, buttons, interactive = _standard_chrome_layout()
        chrome = Win32Chrome(
            win,  # type: ignore[arg-type]
            geometry_provider=lambda: (caption, buttons, interactive),
            api=api,
        )
        params = NCCALCSIZE_PARAMS()
        params.rgrc[0] = RECT(0, 0, 1920, 1080)
        msg = MSG(
            hWnd=win.hwnd,
            message=WM_NCCALCSIZE,
            wParam=1,
            lParam=ctypes.addressof(params),
        )
        result = chrome.handle_native_event(QByteArray(b"windows_generic_MSG"), ctypes.addressof(msg))
        assert result == (True, 0)
        assert (params.rgrc[0].left, params.rgrc[0].top, params.rgrc[0].right, params.rgrc[0].bottom) == (
            0,
            0,
            1920,
            1080,
        )

        # Work-area geometry is already inset by Qt; it must not lose another frame.
        win._user_maximized = True
        chrome.handle_native_event(b"windows_generic_MSG", ctypes.addressof(msg))
        assert (params.rgrc[0].left, params.rgrc[0].top, params.rgrc[0].right, params.rgrc[0].bottom) == (
            0,
            0,
            1920,
            1080,
        )

        # When zoomed/maximized, rgrc[0] is inset by the 8 px frame padding
        api.zoomed = True
        result = chrome.handle_native_event(b"windows_generic_MSG", ctypes.addressof(msg))
        assert result == (True, 0)
        assert (params.rgrc[0].left, params.rgrc[0].top, params.rgrc[0].right, params.rgrc[0].bottom) == (
            8,
            8,
            1912,
            1072,
        )

    @pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
    def test_wm_nchittest_returns_snap_layouts_htmaxbutton_and_all_ht_codes(self, dpr: float) -> None:
        win = _FakeWindow(dpr=dpr)
        api = _FakeWin32Api(client_origin=(100, 50))
        _, caption, buttons, interactive = _standard_chrome_layout()
        chrome = Win32Chrome(
            win,  # type: ignore[arg-type]
            geometry_provider=lambda: (caption, buttons, interactive),
            api=api,
        )

        def send_hittest(logical_x: int, logical_y: int) -> tuple[bool, int] | None:
            screen_x = api.client_origin[0] + round(logical_x * dpr)
            screen_y = api.client_origin[1] + round(logical_y * dpr)
            msg = MSG(
                hWnd=win.hwnd,
                message=WM_NCHITTEST,
                wParam=0,
                lParam=pack_lparam_point(screen_x, screen_y),
            )
            return chrome.handle_native_event(b"windows_generic_MSG", ctypes.addressof(msg))

        assert send_hittest(1210, 18) == (True, HTMAXBUTTON)
        assert send_hittest(1160, 18) == (True, HTMINBUTTON)
        assert send_hittest(1255, 18) == (True, HTCLOSE)
        assert send_hittest(500, 20) == (True, HTCAPTION)
        assert send_hittest(200, 18) == (True, HTCLIENT)  # interactive tab strip
        assert send_hittest(700, 18) == (True, HTCLIENT)  # interactive command field
        assert send_hittest(2, 2) == (True, HTTOPLEFT)
        assert send_hittest(1277, 2) == (True, HTTOPRIGHT)
        assert send_hittest(2, 797) == (True, HTBOTTOMLEFT)
        assert send_hittest(1277, 797) == (True, HTBOTTOMRIGHT)
        assert send_hittest(2, 400) == (True, HTLEFT)
        assert send_hittest(1277, 400) == (True, HTRIGHT)
        assert send_hittest(500, 2) == (True, HTTOP)
        assert send_hittest(500, 797) == (True, HTBOTTOM)

    def test_nonclient_button_hover_press_release_and_leave(self) -> None:
        win = _FakeWindow()
        api = _FakeWin32Api()
        _, caption, buttons, interactive = _standard_chrome_layout()
        btn_min = _FakeButton()
        btn_max = _FakeButton()
        btn_close = _FakeButton()
        lookup = {Zone.MIN: btn_min, Zone.MAX: btn_max, Zone.CLOSE: btn_close}
        chrome = Win32Chrome(
            win,  # type: ignore[arg-type]
            geometry_provider=lambda: (caption, buttons, interactive),
            button_Lookup=lambda: lookup,  # type: ignore[arg-type]
            api=api,
        )

        # Hover over HTMAXBUTTON
        move_msg = MSG(hWnd=win.hwnd, message=WM_NCMOUSEMOVE, wParam=HTMAXBUTTON, lParam=0)
        assert chrome.handle_native_event(b"windows_generic_MSG", ctypes.addressof(move_msg)) == (True, 0)
        assert btn_max.hovered is True
        assert chrome.hovered_button_zone is Zone.MAX
        assert api.tracked_leave == 1

        # Press HTMAXBUTTON
        down_msg = MSG(hWnd=win.hwnd, message=WM_NCLBUTTONDOWN, wParam=HTMAXBUTTON, lParam=0)
        assert chrome.handle_native_event(b"windows_generic_MSG", ctypes.addressof(down_msg)) == (True, 0)
        assert btn_max.down is True
        assert chrome.pressed_button_zone is Zone.MAX

        # Release HTMAXBUTTON -> triggers click
        up_msg = MSG(hWnd=win.hwnd, message=WM_NCLBUTTONUP, wParam=HTMAXBUTTON, lParam=0)
        assert chrome.handle_native_event(b"windows_generic_MSG", ctypes.addressof(up_msg)) == (True, 0)
        assert btn_max.down is False
        assert btn_max.clicks == 1
        assert chrome.pressed_button_zone is None

        # Non-client mouse leave clears hover state
        leave_msg = MSG(hWnd=win.hwnd, message=WM_NCMOUSELEAVE, wParam=0, lParam=0)
        assert chrome.handle_native_event(b"windows_generic_MSG", ctypes.addressof(leave_msg)) == (True, 0)
        assert btn_max.hovered is False
        assert chrome.hovered_button_zone is None

    def test_unrelated_event_type_returns_none(self) -> None:
        win = _FakeWindow()
        _, caption, buttons, interactive = _standard_chrome_layout()
        chrome = Win32Chrome(
            win,  # type: ignore[arg-type]
            geometry_provider=lambda: (caption, buttons, interactive),
            api=None,
        )
        assert chrome.handle_native_event(b"xcb_generic_event_t", 12345) is None
        assert chrome.handle_native_event(b"windows_generic_MSG", 0) is None
