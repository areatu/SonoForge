"""Windows 10/11 custom window chrome via ``nativeEvent`` and ``ctypes`` (UI-1 PR-1).

Implements §4.3 and §8.3 of ``docs/superpowers/specs/2026-10-16-ui-redesign-spec-plan-ru.md``:

- Preserves ``WS_THICKFRAME | WS_CAPTION | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU``
  while stripping the standard non-client frame in ``WM_NCCALCSIZE`` (and
  insetting by the padded resize border when maximized so the client rect does
  not overhang the monitor work area).
- Translates :func:`hit_test` :class:`Zone` results into Win32 ``HT*`` codes in
  ``WM_NCHITTEST``, returning ``HTMAXBUTTON`` over the maximize button so
  Windows 11 shows the native Snap Layouts flyout.
- Paints/drives caption button hover and click states across ``WM_NCMOUSEMOVE``,
  ``WM_NCLBUTTONDOWN``, ``WM_NCLBUTTONUP``, and ``WM_NCMOUSELEAVE`` without
  letting ``DefWindowProc`` draw classic Win32 caption glyphs.
- Applies DWM dark frame (``DWMWA_USE_IMMERSIVE_DARK_MODE``), rounded corners
  (``DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND``), and 1 px frame extension
  for the native DWM shadow.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QByteArray, QPoint, QRect

from echo_personal_tool.presentation.window_chrome.hit_test import (
    BUTTON_ZONES,
    DEFAULT_RESIZE_BORDER_PX,
    Zone,
    hit_test,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QAbstractButton, QWidget

# ── Win32 Hit-Test Codes ──────────────────────────────────────────
HTCLIENT = 1
HTCAPTION = 2
HTSYSMENU = 3
HTMINBUTTON = 8
HTMAXBUTTON = 9
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
HTCLOSE = 20

ZONE_TO_HT: dict[Zone, int] = {
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

_HT_TO_BUTTON_ZONE: dict[int, Zone] = {
    HTMINBUTTON: Zone.MIN,
    HTMAXBUTTON: Zone.MAX,
    HTCLOSE: Zone.CLOSE,
}

# ── Win32 Messages ────────────────────────────────────────────────
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCMOUSEMOVE = 0x00A0
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCLBUTTONDBLCLK = 0x00A3
WM_NCMOUSELEAVE = 0x02A2

# ── Window Styles & SetWindowPos Flags ────────────────────────────
GWL_STYLE = -16
WS_MAXIMIZEBOX = 0x00010000
WS_MINIMIZEBOX = 0x00020000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_CAPTION = 0x00C00000
CHROME_WINDOW_STYLE_MASK = WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

# ── System Metrics ────────────────────────────────────────────────
SM_CXSIZEFRAME = 32
SM_CYSIZEFRAME = 33
SM_CXPADDEDBORDER = 92

# ── DWM Attributes ────────────────────────────────────────────────
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33

DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3

# ── TrackMouseEvent Flags ─────────────────────────────────────────
TME_LEAVE = 0x00000002
TME_NONCLIENT = 0x00000010

_WIN_EVENT_TYPES = frozenset({b"windows_generic_MSG", b"windows_dispatcher_MSG"})


def zone_to_ht(zone: Zone) -> int:
    """Translate a :class:`Zone` into its Win32 ``HT*`` hit-test code."""
    return ZONE_TO_HT.get(zone, HTCLIENT)


def unpack_lparam_point(l_param: int) -> tuple[int, int]:
    """Extract signed 16-bit ``(x, y)`` screen coordinates from a Win32 ``lParam``."""
    x = ctypes.c_short(l_param & 0xFFFF).value
    y = ctypes.c_short((l_param >> 16) & 0xFFFF).value
    return int(x), int(y)


def pack_lparam_point(x: int, y: int) -> int:
    """Pack signed 16-bit ``(x, y)`` coordinates into a Win32 ``lParam`` integer."""
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cxTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [
        ("rgrc", RECT * 3),
        ("lppos", ctypes.c_void_p),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hWnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt", POINT),
    ]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("hwndTrack", ctypes.c_void_p),
        ("dwHoverTime", ctypes.c_uint),
    ]


class Win32Api(Protocol):
    """Testable abstraction over ``user32`` and ``dwmapi`` Win32 calls."""

    def get_window_style(self, hwnd: int) -> int: ...

    def set_window_style(self, hwnd: int, style: int) -> int: ...

    def notify_frame_changed(self, hwnd: int) -> bool: ...

    def set_dwm_attribute(self, hwnd: int, attribute: int, value: int) -> int: ...

    def extend_frame_into_client_area(self, hwnd: int, margins: tuple[int, int, int, int]) -> int: ...

    def is_zoomed(self, hwnd: int) -> bool: ...

    def frame_padding(self, hwnd: int) -> tuple[int, int]: ...

    def screen_to_client(self, hwnd: int, screen_x: int, screen_y: int) -> tuple[int, int] | None: ...

    def track_nonclient_mouse_leave(self, hwnd: int) -> bool: ...


class _CtypesWin32Api:
    """Default ``ctypes.windll`` implementation used on Windows."""

    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]  # mypy does not check this file (outside tool.mypy.files)
        self._dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]  # mypy does not check this file (outside tool.mypy.files)
        self._get_long = getattr(self._user32, "GetWindowLongPtrW", self._user32.GetWindowLongW)
        self._set_long = getattr(self._user32, "SetWindowLongPtrW", self._user32.SetWindowLongW)
        self._get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._get_long.restype = ctypes.c_ssize_t
        self._set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        self._set_long.restype = ctypes.c_ssize_t

    def get_window_style(self, hwnd: int) -> int:
        return int(self._get_long(ctypes.c_void_p(hwnd), GWL_STYLE))

    def set_window_style(self, hwnd: int, style: int) -> int:
        return int(self._set_long(ctypes.c_void_p(hwnd), GWL_STYLE, ctypes.c_ssize_t(style)))

    def notify_frame_changed(self, hwnd: int) -> bool:
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        return bool(self._user32.SetWindowPos(ctypes.c_void_p(hwnd), 0, 0, 0, 0, 0, flags))

    def set_dwm_attribute(self, hwnd: int, attribute: int, value: int) -> int:
        val = ctypes.c_int(int(value))
        return int(
            self._dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(attribute),
                ctypes.byref(val),
                ctypes.sizeof(val),
            )
        )

    def extend_frame_into_client_area(self, hwnd: int, margins: tuple[int, int, int, int]) -> int:
        m = MARGINS(*margins)
        return int(self._dwmapi.DwmExtendFrameIntoClientArea(ctypes.c_void_p(hwnd), ctypes.byref(m)))

    def is_zoomed(self, hwnd: int) -> bool:
        return bool(self._user32.IsZoomed(ctypes.c_void_p(hwnd)))

    def frame_padding(self, hwnd: int) -> tuple[int, int]:
        get_metrics_dpi = getattr(self._user32, "GetSystemMetricsForDpi", None)
        get_dpi_for_window = getattr(self._user32, "GetDpiForWindow", None)
        if get_metrics_dpi is not None and get_dpi_for_window is not None:
            dpi = int(get_dpi_for_window(ctypes.c_void_p(hwnd))) or 96
            fx = int(get_metrics_dpi(SM_CXSIZEFRAME, dpi)) + int(get_metrics_dpi(SM_CXPADDEDBORDER, dpi))
            fy = int(get_metrics_dpi(SM_CYSIZEFRAME, dpi)) + int(get_metrics_dpi(SM_CXPADDEDBORDER, dpi))
            return max(fx, 0), max(fy, 0)
        fx = int(self._user32.GetSystemMetrics(SM_CXSIZEFRAME)) + int(self._user32.GetSystemMetrics(SM_CXPADDEDBORDER))
        fy = int(self._user32.GetSystemMetrics(SM_CYSIZEFRAME)) + int(self._user32.GetSystemMetrics(SM_CXPADDEDBORDER))
        return max(fx, 0), max(fy, 0)

    def screen_to_client(self, hwnd: int, screen_x: int, screen_y: int) -> tuple[int, int] | None:
        pt = POINT(screen_x, screen_y)
        if not self._user32.ScreenToClient(ctypes.c_void_p(hwnd), ctypes.byref(pt)):
            return None
        return int(pt.x), int(pt.y)

    def track_nonclient_mouse_leave(self, hwnd: int) -> bool:
        tme = TRACKMOUSEEVENT(
            cbSize=ctypes.sizeof(TRACKMOUSEEVENT),
            dwFlags=TME_LEAVE | TME_NONCLIENT,
            hwndTrack=ctypes.c_void_p(hwnd),
            dwHoverTime=0,
        )
        return bool(self._user32.TrackMouseEvent(ctypes.byref(tme)))


def _default_win32_api() -> Win32Api | None:
    if sys.platform != "win32":
        return None
    try:
        return _CtypesWin32Api()
    except Exception:
        return None


def _set_button_hover(button: QAbstractButton, hovered: bool) -> None:
    """Drive hover visual state on a caption button during non-client Win32 events."""
    from PySide6.QtCore import Qt

    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, hovered)
    # Non-client mouse messages do not update Qt stylesheet pseudo-states.
    button.setProperty("nativeHovered", hovered)
    button.style().unpolish(button)
    button.style().polish(button)
    on_enter = getattr(button, "_on_enter", None)
    on_leave = getattr(button, "_on_leave", None)
    if hovered and callable(on_enter):
        on_enter()
    elif not hovered and callable(on_leave):
        on_leave()
    button.update()


class Win32Chrome:
    """Win32 custom title-bar, Snap Layouts, resize border, and DWM controller."""

    def __init__(
        self,
        window: QWidget,
        *,
        geometry_provider: Callable[[], tuple[QRect, Mapping[Zone, QRect], list[QRect]]],
        button_Lookup: Callable[[], Mapping[Zone, QAbstractButton | None]] | None = None,
        api: Win32Api | None = None,
        border_px: int = DEFAULT_RESIZE_BORDER_PX,
    ) -> None:
        self._window = window
        self._geometry_provider = geometry_provider
        self._button_lookup = button_Lookup
        self._api = api if api is not None else _default_win32_api()
        self._border_px = border_px
        self._hovered_zone: Zone | None = None
        self._pressed_zone: Zone | None = None

    @property
    def hovered_button_zone(self) -> Zone | None:
        return self._hovered_zone

    @property
    def pressed_button_zone(self) -> Zone | None:
        return self._pressed_zone

    def install(self, *, dark: bool = True, round_corners: bool = True) -> bool:
        """Apply Win32 frame styles and DWM attributes to the window."""
        if self._api is None:
            return False
        hwnd = int(self._window.winId())
        styles_ok = self.apply_window_styles(hwnd)
        dwm_ok = self.apply_dwm_attributes(hwnd, dark=dark, round_corners=round_corners)
        return styles_ok or dwm_ok

    def apply_window_styles(self, hwnd: int) -> bool:
        """Ensure ``WS_THICKFRAME | WS_CAPTION`` are set on ``hwnd`` for Snap & resize."""
        if self._api is None:
            return False
        current = self._api.get_window_style(hwnd)
        desired = current | CHROME_WINDOW_STYLE_MASK
        if desired != current:
            self._api.set_window_style(hwnd, desired)
        return self._api.notify_frame_changed(hwnd)

    def apply_dwm_attributes(
        self,
        hwnd: int,
        *,
        dark: bool = True,
        round_corners: bool = True,
    ) -> bool:
        """Apply DWM immersive dark mode, rounded corners, and shadow margins."""
        if self._api is None:
            return False
        dark_val = 1 if dark else 0
        hr = self._api.set_dwm_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, dark_val)
        if hr != 0:
            self._api.set_dwm_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1, dark_val)
        corner_pref = DWMWCP_ROUND if round_corners else DWMWCP_DEFAULT
        self._api.set_dwm_attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, corner_pref)
        self._api.extend_frame_into_client_area(hwnd, (0, 0, 0, 1))
        return True

    def _is_maximized(self, hwnd: int) -> bool:
        if self._api is not None and hwnd and self._api.is_zoomed(hwnd):
            return True
        return bool(self._window.isMaximized() or getattr(self._window, "_user_maximized", False))

    def _screen_to_local_point(self, hwnd: int, screen_x: int, screen_y: int) -> QPoint:
        dpr = max(float(self._window.devicePixelRatioF()), 1.0)
        if self._api is not None and hwnd:
            client = self._api.screen_to_client(hwnd, screen_x, screen_y)
            if client is not None:
                return QPoint(round(client[0] / dpr), round(client[1] / dpr))
        origin = self._window.mapToGlobal(QPoint(0, 0))
        return QPoint(round((screen_x - origin.x()) / dpr), round((screen_y - origin.y()) / dpr))

    def _buttons_by_zone(self) -> Mapping[Zone, QAbstractButton | None]:
        if self._button_lookup is None:
            return {}
        return self._button_lookup()

    def _update_button_hover(self, zone: Zone | None) -> None:
        target = zone if zone in BUTTON_ZONES else None
        if target == self._hovered_zone:
            return
        buttons = self._buttons_by_zone()
        if self._hovered_zone is not None:
            prev_btn = buttons.get(self._hovered_zone)
            if prev_btn is not None:
                _set_button_hover(prev_btn, False)
        self._hovered_zone = target
        if target is not None:
            next_btn = buttons.get(target)
            if next_btn is not None:
                _set_button_hover(next_btn, True)

    def _clear_button_states(self) -> None:
        buttons = self._buttons_by_zone()
        if self._pressed_zone is not None:
            btn = buttons.get(self._pressed_zone)
            if btn is not None:
                btn.setDown(False)
            self._pressed_zone = None
        self._update_button_hover(None)

    def handle_native_event(
        self,
        event_type: QByteArray | bytes | str,
        message_ptr: int,
    ) -> tuple[bool, int] | None:
        """Process a Win32 ``MSG`` from ``QWidget.nativeEvent``.

        Returns ``(True, result)`` when handled, or ``None`` to fall through to
        Qt's default ``nativeEvent`` handler.
        """
        raw_type = bytes(event_type) if isinstance(event_type, QByteArray) else event_type
        if isinstance(raw_type, str):
            raw_type = raw_type.encode("ascii", errors="ignore")
        if raw_type not in _WIN_EVENT_TYPES or not message_ptr:
            return None

        msg = MSG.from_address(int(message_ptr))
        hwnd = int(msg.hWnd or 0)
        message = int(msg.message)

        if message == WM_NCCALCSIZE:
            if msg.wParam and msg.lParam:
                if self._api is not None and self._api.is_zoomed(hwnd):
                    fx, fy = self._api.frame_padding(hwnd)
                    if fx > 0 or fy > 0:
                        params = NCCALCSIZE_PARAMS.from_address(int(msg.lParam))
                        params.rgrc[0].left += fx
                        params.rgrc[0].top += fy
                        params.rgrc[0].right -= fx
                        params.rgrc[0].bottom -= fy
                return True, 0
            return None

        if message == WM_NCHITTEST:
            screen_x, screen_y = unpack_lparam_point(int(msg.lParam))
            local_pos = self._screen_to_local_point(hwnd, screen_x, screen_y)
            caption_rect, buttons, interactive = self._geometry_provider()
            zone = hit_test(
                local_pos,
                self._window.size(),
                border=self._border_px,
                caption=caption_rect,
                buttons=buttons,
                interactive=interactive,
                maximized=self._is_maximized(hwnd),
            )
            if zone not in BUTTON_ZONES and self._hovered_zone is not None:
                self._update_button_hover(None)
            return True, zone_to_ht(zone)

        if message == WM_NCMOUSEMOVE:
            btn_zone = _HT_TO_BUTTON_ZONE.get(int(msg.wParam))
            if btn_zone is not None:
                self._update_button_hover(btn_zone)
                if self._api is not None and hwnd:
                    self._api.track_nonclient_mouse_leave(hwnd)
                return True, 0
            self._update_button_hover(None)
            return None

        if message == WM_NCLBUTTONDOWN:
            btn_zone = _HT_TO_BUTTON_ZONE.get(int(msg.wParam))
            if btn_zone is not None:
                self._update_button_hover(btn_zone)
                self._pressed_zone = btn_zone
                btn = self._buttons_by_zone().get(btn_zone)
                if btn is not None:
                    btn.setDown(True)
                return True, 0
            return None

        if message == WM_NCLBUTTONUP:
            btn_zone = _HT_TO_BUTTON_ZONE.get(int(msg.wParam))
            if btn_zone is not None:
                was_pressed = self._pressed_zone == btn_zone
                btn = self._buttons_by_zone().get(btn_zone)
                if btn is not None:
                    btn.setDown(False)
                self._pressed_zone = None
                if was_pressed and btn is not None:
                    btn.click()
                return True, 0
            self._clear_button_states()
            return None

        if message == WM_NCMOUSELEAVE:
            self._clear_button_states()
            return True, 0

        return None
