"""Тонкий адаптер вьюера для проекции протокола (TP-3 PR-3, QH-3).

Адаптер только читает то, что вьюер уже считает (``is_doppler_context``,
``resolved_doppler_mode``), и возвращает плоские значения для
``build_study_projection``: новый протоколо-ориентированного состояния в
``ViewerWidget`` не появляется.  Неизвестный режим допплера ничего не
блокирует: блокировка требует знания о проблеме.
"""

from __future__ import annotations

from echo_personal_tool.presentation.viewer_clip_context import (
    UNKNOWN_DOPPLER,
    clip_modes,
    clip_view,
)


class _FakeViewer:
    def __init__(self, *, doppler: bool = False, mode: str = "", view: str | None = None, broken=False):
        self._doppler = doppler
        self._mode = mode
        self._view = view
        self._broken = broken

    def is_doppler_context(self) -> bool:
        return self._doppler

    def resolved_doppler_mode(self) -> str:
        return self._mode

    def current_clip_view(self) -> str:
        if self._broken:
            raise RuntimeError("no view metadata")
        return self._view or ""


def test_bmode_clip_offers_the_2d_context() -> None:
    assert clip_modes(_FakeViewer()) == frozenset({"2d"})


def test_mmode_widget_overrides_the_viewer() -> None:
    assert clip_modes(_FakeViewer(doppler=True, mode="PW"), mmode_active=True) == frozenset({"m"})


def test_doppler_clip_reports_its_own_mode() -> None:
    assert clip_modes(_FakeViewer(doppler=True, mode="PW")) == frozenset({"pw"})
    assert clip_modes(_FakeViewer(doppler=True, mode="cw")) == frozenset({"cw"})


def test_unknown_doppler_mode_blocks_nothing() -> None:
    assert clip_modes(_FakeViewer(doppler=True, mode="")) == UNKNOWN_DOPPLER
    assert clip_modes(_FakeViewer(doppler=True, mode="")) == frozenset()


def test_clip_view_is_normalised_uppercase() -> None:
    assert clip_view(_FakeViewer(view=" a4c ")) == "A4C"
    assert clip_view(_FakeViewer(view="PLAX")) == "PLAX"


def test_clip_view_stays_unknown_without_metadata() -> None:
    class _NoView:
        def is_doppler_context(self) -> bool:
            return False

    assert clip_view(_NoView()) == ""
    assert clip_view(_FakeViewer(broken=True)) == ""


def test_viewer_without_doppler_api_is_bmode() -> None:
    class _Plain:
        pass

    assert clip_modes(_Plain()) == frozenset({"2d"})
