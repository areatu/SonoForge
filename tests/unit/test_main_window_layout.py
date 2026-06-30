"""MainWindow layout rebuild regression tests."""

from __future__ import annotations

from dataclasses import asdict, replace

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.main_window import LayoutConfig, MainWindow


def _make_window(qtbot) -> MainWindow:
    prefs = UserPreferences(layout_state_json="")
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    window._layout_config = LayoutConfig()
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    return window


def _apply(window: MainWindow, **kwargs: object) -> None:
    window._layout_config = replace(LayoutConfig(), **{**asdict(window._layout_config), **kwargs})
    window._rebuild_layout()
    QApplication.processEvents()


def _viewer_in_content_tree(window: MainWindow) -> bool:
    viewer = window._viewer
    if window._content_layout.indexOf(viewer) >= 0:
        return True
    splitter_idx = window._content_layout.indexOf(window._content_splitter)
    if splitter_idx >= 0 and window._content_splitter.indexOf(viewer) >= 0:
        return True
    return False


def _gallery_alive(window: MainWindow) -> bool:
    try:
        return window._gallery.width() >= 0
    except RuntimeError:
        return False


@pytest.mark.parametrize(
    "cfg_kwargs",
    [
        {},
        {"swap_places": True},
        {"gallery_horizontal": True},
        {"activity_bar": True},
        {"multiview": True},
        {"swap_places": True, "gallery_horizontal": True},
        {"activity_bar": True, "gallery_horizontal": True},
        {"activity_bar": True, "swap_places": True},
        {"gallery_horizontal": True, "activity_bar": True, "swap_places": True},
    ],
    ids=[
        "default",
        "swap",
        "horizontal_gallery",
        "activity_bar",
        "multiview",
        "swap_horizontal",
        "activity_horizontal",
        "activity_swap",
        "activity_swap_horizontal",
    ],
)
def test_layout_preserves_viewer_and_gallery(qtbot, cfg_kwargs: dict) -> None:
    window = _make_window(qtbot)
    _apply(window, **cfg_kwargs)

    assert _viewer_in_content_tree(window)
    assert window._viewer.isVisible()
    assert _gallery_alive(window)
    assert window._gallery.isVisible()

    if cfg_kwargs.get("multiview"):
        assert window._viewer2 is not None
        assert window._viewer2.isVisible()
        assert window._content_splitter.indexOf(window._viewer2) >= 0
        assert window._content_layout.indexOf(window._tool_panel) >= 0


def test_horizontal_gallery_toggle_does_not_destroy_gallery(qtbot) -> None:
    window = _make_window(qtbot)
    gallery_id = id(window._gallery)

    _apply(window, gallery_horizontal=True)
    assert window._gallery.isVisible()
    assert window._bottom_container is not None

    _apply(window, gallery_horizontal=False)
    assert id(window._gallery) == gallery_id
    assert window._gallery.isVisible()
    assert window._content_layout.indexOf(window._gallery) >= 0


def test_activity_bar_off_restores_tool_panel_with_horizontal_gallery(qtbot) -> None:
    window = _make_window(qtbot)
    _apply(window, activity_bar=True, gallery_horizontal=True)
    assert not window._tool_panel.isVisible()

    _apply(window, activity_bar=False, gallery_horizontal=True)
    assert window._tool_panel.isVisible()
    assert window._content_layout.indexOf(window._tool_panel) >= 0


def test_swap_then_default_restores_viewer(qtbot) -> None:
    window = _make_window(qtbot)
    _apply(window, swap_places=True)
    assert window._viewer.isVisible()

    _apply(window, swap_places=False)
    assert window._viewer.isVisible()
    assert window._content_splitter.indexOf(window._viewer) >= 0
    assert window._content_splitter.indexOf(window._tool_panel) >= 0


def test_horizontal_swap_activity_toggle_restores_tool_panel(qtbot) -> None:
    """Regression: horizontal gallery + swap/activity toggles must not leave empty 280px strip."""
    window = _make_window(qtbot)
    _apply(window, gallery_horizontal=True)
    _apply(window, gallery_horizontal=True, swap_places=True)
    _apply(window, gallery_horizontal=True, swap_places=True, activity_bar=True)

    window._on_activity_tab_activated("measures")
    assert window._content_layout.indexOf(window._tool_panel) >= 0
    assert window._tool_panel.isVisible()
    assert window._tool_panel._tabs.isVisible()

    window._on_activity_tab_deactivated("measures")
    assert window._content_layout.indexOf(window._tool_panel) < 0

    _apply(window, gallery_horizontal=True, swap_places=True, activity_bar=False)
    assert window._content_layout.indexOf(window._tool_panel) >= 0
    assert window._tool_panel.isVisible()
    assert window._tool_panel._tabs.isVisible()

    _apply(window, gallery_horizontal=True, swap_places=False, activity_bar=True)
    window._activity_bar._buttons["controls"].setChecked(True)
    window._on_activity_tab_activated("controls")
    assert window._content_layout.indexOf(window._tool_panel) >= 0
    assert window._tool_panel._tabs.currentIndex() == 1

    _apply(window, gallery_horizontal=True, swap_places=False, activity_bar=False)
    assert window._content_layout.indexOf(window._tool_panel) >= 0
    assert window._tool_panel.isVisible()


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
