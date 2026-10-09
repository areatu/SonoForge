"""MainWindow layout rebuild regression tests."""

from __future__ import annotations

from dataclasses import asdict, replace

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication, QSplitter


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """Layout rebuilds persist to QSettings — keep them out of the real store."""
    return isolated_qsettings


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
    surface = window._viewer_stack
    if window._content_layout.indexOf(surface) >= 0:
        return True
    splitter_idx = window._content_layout.indexOf(window._content_splitter)
    if splitter_idx >= 0 and window._content_splitter.indexOf(surface) >= 0:
        return True
    for index in range(window._content_splitter.count()):
        child = window._content_splitter.widget(index)
        if isinstance(child, QSplitter) and child.indexOf(surface) >= 0:
            return True
    # Multiview: the main viewer lives inside its pane widget, which in turn
    # sits in the content splitter.
    pane = getattr(window, "_pane_left", None)
    if pane is not None and window._content_splitter.indexOf(pane) >= 0 and pane.viewer is viewer:
        return True
    return False


def _gallery_alive(window: MainWindow) -> bool:
    try:
        return window._gallery.width() >= 0
    except RuntimeError:
        return False


def test_maximize_sets_geometry_before_first_show(qtbot, monkeypatch) -> None:
    """No show-small-then-resize flash: geometry lands before the window appears."""
    from PySide6.QtWidgets import QMainWindow

    from echo_personal_tool.presentation.main_window import apply_maximized_to_work_area

    calls: list[str] = []
    orig_show = QMainWindow.show
    orig_set_geometry = QMainWindow.setGeometry

    def _show(self) -> None:
        calls.append("show")
        orig_show(self)

    def _set_geometry(self, rect) -> None:
        calls.append("setGeometry")
        orig_set_geometry(self, rect)

    monkeypatch.setattr(QMainWindow, "show", _show)
    monkeypatch.setattr(QMainWindow, "setGeometry", _set_geometry)

    window = QMainWindow()
    qtbot.addWidget(window)
    assert not window.isVisible()
    apply_maximized_to_work_area(window)
    assert window.isVisible()
    assert window._user_maximized is True
    import sys

    if sys.platform == "win32":
        # Geometry first, show second — never show() before setGeometry().
        assert calls[0] == "setGeometry"
        assert window.size() == window.screen().availableGeometry().size()


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
    if cfg_kwargs.get("multiview"):
        assert window._viewer_stack.currentWidget() is window._start_page
        assert window._pane_left is None  # empty workspaces defer pane creation
    else:
        assert window._viewer_stack.isVisible()
        assert window._viewer_stack.currentWidget() is window._start_page
    assert _gallery_alive(window)
    assert window._gallery.isVisible()

    if cfg_kwargs.get("multiview") and window._has_loaded_study:
        assert window._viewer.isVisible()
        assert window._viewer2 is not None
        assert window._viewer2.isVisible()
        # The second clip lives in its own pane widget inside the splitter.
        pane_right = window._pane_right
        assert pane_right is not None
        assert window._content_splitter.indexOf(pane_right) >= 0
        assert pane_right.viewer is window._viewer2
        assert window._content_layout.indexOf(window._tool_panel) >= 0
        # Shared transport under the two panes; marker bars hidden by default.
        assert window._multiview_transport is not None
        assert window._multiview_transport.isVisible()


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


def test_viewer_stack_switches_between_welcome_and_loaded_viewer(qtbot) -> None:
    window = _make_window(qtbot)
    assert window._viewer_stack.currentWidget() is window._start_page

    window._has_loaded_study = True
    window._set_start_page_visible(False)
    assert window._viewer_stack.currentWidget() is window._viewer

    window.show_empty_start_page()
    assert window._viewer_stack.currentWidget() is window._start_page


def test_persisted_multiview_layout_keeps_welcome_page_until_studies_load(qtbot) -> None:
    window = _make_window(qtbot)
    window._layout_config = replace(window._layout_config, multiview=True)
    window._rebuild_layout()

    assert window._viewer_stack.currentWidget() is window._start_page
    assert window._content_layout.indexOf(window._viewer_stack) >= 0
    assert window._pane_left is None

    window._has_loaded_study = True
    window._rebuild_layout()
    assert window._pane_left is not None
    pane_left = window._pane_left
    assert window._content_splitter.indexOf(pane_left) >= 0

    window.show_empty_start_page()
    assert window._viewer_stack.currentWidget() is window._start_page
    assert window._content_layout.indexOf(window._viewer_stack) >= 0
    assert pane_left.isHidden()

    window._has_loaded_study = True
    window._rebuild_layout()
    assert window._pane_left is pane_left
    assert not pane_left.isHidden()
    assert window._content_splitter.indexOf(pane_left) >= 0


def test_empty_studies_reveal_start_page_in_multiview_and_restore_on_reload(qtbot) -> None:
    window = _make_window(qtbot)
    window._has_loaded_study = True
    window._layout_config = replace(window._layout_config, multiview=True)
    window._rebuild_layout()
    pane = window._pane_left
    assert pane is not None

    window._on_studies_loaded([])
    assert not window._has_loaded_study
    assert window._viewer_stack.currentWidget() is window._start_page
    assert window._content_layout.indexOf(window._viewer_stack) >= 0
    assert pane.isHidden()

    window._has_loaded_study = True
    window._rebuild_layout()
    assert not pane.isHidden()
    assert window._content_splitter.indexOf(pane) >= 0


def test_mmode_wraps_and_restores_the_viewer_surface(qtbot) -> None:
    window = _make_window(qtbot)
    window._activate_mmode()

    assert window._mmode_vertical_splitter.indexOf(window._viewer_stack) >= 0
    window._finish_mmode_deactivation()
    QApplication.processEvents()

    assert window._content_splitter.indexOf(window._viewer_stack) >= 0
    assert window._viewer_stack.currentWidget() is window._start_page


def test_mmode_wraps_a_direct_viewer_stack_layout(qtbot) -> None:
    window = _make_window(qtbot)
    window._layout_config = replace(window._layout_config, gallery_horizontal=True)
    window._rebuild_layout()
    assert window._content_layout.indexOf(window._viewer_stack) >= 0

    window._activate_mmode()
    assert window._content_layout.indexOf(window._mmode_vertical_splitter) >= 0

    window._finish_mmode_deactivation()
    QApplication.processEvents()
    assert window._content_layout.indexOf(window._viewer_stack) >= 0
    assert window._viewer_stack.currentWidget() is window._start_page


def test_main_viewer_is_restored_when_multiview_is_reenabled(qtbot) -> None:
    window = _make_window(qtbot)
    window._has_loaded_study = True
    window._layout_config = replace(window._layout_config, multiview=True)
    window._rebuild_layout()
    pane = window._pane_left
    assert pane is not None
    assert pane.layout().indexOf(window._viewer) >= 0

    window._layout_config = replace(window._layout_config, multiview=False)
    window._rebuild_layout()
    assert window._viewer_stack.indexOf(window._viewer) >= 0

    window._layout_config = replace(window._layout_config, multiview=True)
    window._rebuild_layout()
    assert window._pane_left is pane
    assert pane.layout().indexOf(window._viewer) >= 0
    assert window._viewer_stack.indexOf(window._viewer) < 0


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
    assert window._viewer_stack.currentWidget() is window._start_page

    _apply(window, swap_places=False)
    assert window._viewer_stack.currentWidget() is window._start_page
    assert window._content_splitter.indexOf(window._viewer_stack) >= 0
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
    assert window._tool_panel._tabs.currentWidget() is window._tool_panel.controls

    _apply(window, gallery_horizontal=True, swap_places=False, activity_bar=False)
    assert window._content_layout.indexOf(window._tool_panel) >= 0
    assert window._tool_panel.isVisible()


def test_activity_tabs_select_widgets_not_indexes(qtbot) -> None:
    """Э11 inserted a Calculators tab: activity buttons must still hit their tab."""
    window = _make_window(qtbot)
    tabs = window._tool_panel._tabs
    for key, widget in (
        ("calculators", window._tool_panel.calculators),
        ("controls", window._tool_panel.controls),
        ("measures", window._tool_panel.measure),
    ):
        window._on_activity_tab_activated(key)
        assert tabs.currentWidget() is widget
    # A hidden tab (Properties not added yet) leaves the selection alone.
    if tabs.indexOf(window._tool_panel.properties_panel) < 0:
        window._on_activity_tab_activated("properties")
        assert tabs.currentWidget() is window._tool_panel.measure


def test_calculator_override_reaches_the_controller(qtbot) -> None:
    window = _make_window(qtbot)
    controller = window._controller
    window._tool_panel.calculators.study_input_changed.emit("hr", 70.0)
    assert controller._calculator_inputs.manual(controller._resolve_study_uid()) == {"hr": 70.0}


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
