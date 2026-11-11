"""The 2.0 measurement panel must follow the viewer context (§4.2)."""

from __future__ import annotations

from echo_personal_tool.presentation.tool_context import sync_tool_panel_context


class _FakePanel:
    is_v2 = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def set_view_context(self, context: str, mode: str = "", *, defer: bool = False) -> None:
        self.calls.append((context, mode, defer))


class _FakeDoppler:
    def __init__(self, *, context: bool, mode: str = "spectral") -> None:
        self._context = context
        self.resolved_mode = lambda: mode

    def is_context(self) -> bool:
        return self._context


class _LegacyPanel:
    is_v2 = False


def test_a_b_mode_viewer_asks_for_the_2d_context() -> None:
    panel = _FakePanel()

    sync_tool_panel_context(panel, mmode_active=False, doppler=_FakeDoppler(context=False))

    assert panel.calls == [("2d", "", True)]


def test_a_doppler_viewer_carries_its_resolved_mode() -> None:
    panel = _FakePanel()

    sync_tool_panel_context(panel, mmode_active=False, doppler=_FakeDoppler(context=True, mode="HPRF"))

    assert panel.calls == [("doppler", "HPRF", True)]


def test_m_mode_wins_over_doppler() -> None:
    panel = _FakePanel()

    sync_tool_panel_context(panel, mmode_active=True, doppler=_FakeDoppler(context=True))

    assert panel.calls == [("m", "", True)]


def test_the_legacy_panel_and_a_missing_panel_are_left_alone() -> None:
    legacy = _LegacyPanel()

    sync_tool_panel_context(legacy, mmode_active=True, doppler=_FakeDoppler(context=True))
    sync_tool_panel_context(None, mmode_active=True, doppler=_FakeDoppler(context=True))

    assert not hasattr(legacy, "calls")
