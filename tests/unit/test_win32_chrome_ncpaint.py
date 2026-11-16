"""WM_NCPAINT ownership (2026-11-16 list, item 1 — «белая рамка»).

On Win10 closing the settings dialog reactivated the window and let
``DefWindowProc`` paint the classic light frame around the dark UI.  The
handler must swallow ``WM_NCPAINT``: DWM keeps whatever it claims, the rest is
coloured by us, and ``DefWindowProc`` never sees the message.
"""

from __future__ import annotations

import ctypes

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QWidget

from echo_personal_tool.presentation.window_chrome.win32_chrome import (
    MSG,
    NCBAND_COLOR_COLORREF,
    WM_NCPAINT,
    Win32Chrome,
)

pytestmark = pytest.mark.gui


class _FakeApi:
    def __init__(self) -> None:
        self.dwm_calls: list[tuple[int, int, int, int]] = []
        self.painted: list[tuple[int, int]] = []
        self.dwm_handles = False
        self.dwm_result = 0

    # Win32Api surface used by the handler under test.
    def dwm_def_window_proc(self, hwnd: int, message: int, w_param: int, l_param: int) -> tuple[bool, int]:
        self.dwm_calls.append((hwnd, message, w_param, l_param))
        return self.dwm_handles, self.dwm_result

    def paint_nonclient_band(self, hwnd: int, color: int) -> bool:
        self.painted.append((hwnd, color))
        return True

    # Unused surface of the protocol; kept so the fake is a drop-in replacement.
    def get_window_style(self, hwnd: int) -> int:  # pragma: no cover - not under test
        return 0

    def set_window_style(self, hwnd: int, style: int) -> int:  # pragma: no cover
        return 0

    def notify_frame_changed(self, hwnd: int) -> bool:  # pragma: no cover
        return True

    def set_dwm_attribute(self, hwnd: int, attribute: int, value: int) -> int:  # pragma: no cover
        return 0

    def extend_frame_into_client_area(self, hwnd: int, margins: tuple[int, int, int, int]) -> int:  # pragma: no cover
        return 0

    def is_zoomed(self, hwnd: int) -> bool:  # pragma: no cover
        return False

    def frame_padding(self, hwnd: int) -> tuple[int, int]:  # pragma: no cover
        return 0, 0

    def screen_to_client(self, hwnd: int, screen_x: int, screen_y: int) -> tuple[int, int] | None:  # pragma: no cover
        return screen_x, screen_y

    def track_nonclient_mouse_leave(self, hwnd: int) -> bool:  # pragma: no cover
        return True


def _chrome(qtbot, api: _FakeApi | None) -> Win32Chrome:
    window = QWidget()
    qtbot.addWidget(window)

    def geometry() -> tuple[QRect, dict, list]:
        return QRect(0, 0, 1200, 40), {}, []

    return Win32Chrome(window, geometry_provider=geometry, api=api)


def _send_ncpaint(chrome: Win32Chrome, *, hwnd: int = 1234) -> tuple[bool, int] | None:
    msg = MSG(hWnd=hwnd, message=WM_NCPAINT, wParam=1, lParam=0)
    return chrome.handle_native_event(b"windows_generic_MSG", ctypes.addressof(msg))


def test_ncpaint_is_swallowed_and_the_band_is_ours(qtbot) -> None:
    api = _FakeApi()
    chrome = _chrome(qtbot, api)

    handled = _send_ncpaint(chrome)

    assert handled == (True, 0), "WM_NCPAINT must never fall through to DefWindowProc"
    assert api.dwm_calls and api.dwm_calls[0][1] == WM_NCPAINT, "DWM paints its part first"
    assert api.painted == [(1234, NCBAND_COLOR_COLORREF)]


def test_ncpaint_lets_dwm_keep_its_own_painting(qtbot) -> None:
    api = _FakeApi()
    api.dwm_handles = True
    api.dwm_result = 42
    chrome = _chrome(qtbot, api)

    handled = _send_ncpaint(chrome)

    assert handled == (True, 42)
    assert api.painted == [], "a band DWM already painted is not painted again"


def test_ncpaint_without_a_win32_api_is_still_swallowed(qtbot) -> None:
    chrome = _chrome(qtbot, None)

    assert _send_ncpaint(chrome) == (True, 0)
