"""MainWindow layout rebuild regression tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication, QMenu, QSplitter, QWidget


@pytest.fixture(autouse=True)
def _isolate_qsettings(isolated_qsettings):
    """Layout rebuilds persist to QSettings — keep them out of the real store."""
    return isolated_qsettings


from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.layout.presets import (
    PRESET_CLASSIC,
    PRESET_FILMSTRIP,
    PRESET_MIRRORED,
    LayoutConfigV2,
)
from echo_personal_tool.presentation.main_window import MainWindow


def _make_window(qtbot) -> MainWindow:
    prefs = UserPreferences(layout_state_json="")
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    # These tests describe the chosen preset, not the single-file focus view
    # (UI-6) that a one-clip study opens by itself: keep the automatic entry off
    # so the layout assertions read the preset's own assembly.
    window._layout_document = LayoutConfigV2(single_file_focus=False)
    window._multiview_mode = False
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    return window


def _publish_one_study(window: MainWindow) -> None:
    from datetime import datetime

    from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata

    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.layout",
        series_uid="1.2.3.layout.series",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )
    series = SeriesMetadata(
        series_uid="1.2.3.layout.series",
        study_uid="1.2.3.layout",
        modality="US",
        description="A4C",
        instances=(instance,),
    )
    study = StudyMetadata(study_uid="1.2.3.layout", study_datetime=datetime(2026, 10, 1), series=(series,))
    window._controller.studies_loaded.emit([study])
    QApplication.processEvents()


def _apply(
    window: MainWindow,
    *,
    preset: str = PRESET_CLASSIC,
    tool_buttons: str = "auto",
    status_bar_visible: bool = True,
    multiview: bool = False,
) -> None:
    """UI-2 PR-2: the window state is a v2 document plus the session flag."""
    window._layout_document = LayoutConfigV2(
        preset=preset, tool_buttons=tool_buttons, status_bar_visible=status_bar_visible
    )
    window._multiview_mode = multiview
    window._rebuild_layout()
    QApplication.processEvents()


@pytest.fixture(autouse=True)
def _stub_load_failure_dialog(monkeypatch) -> None:
    """Synthetic publishes autoload a clip whose files do not exist; the async
    load failure would open a modal QMessageBox and block headless runs."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)


def _holds(window: MainWindow, container, surface) -> bool:
    """Whether ``container`` holds ``surface`` — directly or through the column.

    UI-2 PR-3 (§9): the image lives in the snapshot column, which carries the tool
    row above it, so a layout assertion has to allow for the extra widget instead
    of pinning the stack to a specific parent.
    """
    if container.indexOf(surface) >= 0:
        return True
    column = getattr(window, "_viewer_column", None)
    return column is not None and column.part("center") is surface and container.indexOf(column) >= 0


def _viewer_in_content_tree(window: MainWindow) -> bool:
    viewer = window._viewer
    surface = window._viewer_stack
    if _holds(window, window._content_layout, surface):
        return True
    if _holds(window, window._content_splitter, surface):
        return True
    for index in range(window._content_splitter.count()):
        child = window._content_splitter.widget(index)
        if isinstance(child, QSplitter) and _holds(window, child, surface):
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
        {"preset": PRESET_MIRRORED},
        {"preset": PRESET_FILMSTRIP},
        {"tool_buttons": "rail"},
        {"multiview": True},
        {"preset": PRESET_MIRRORED, "tool_buttons": "rail"},
        {"preset": PRESET_FILMSTRIP, "tool_buttons": "rail"},
        {"preset": PRESET_MIRRORED, "multiview": True},
        {"preset": PRESET_FILMSTRIP, "multiview": True},
    ],
    ids=[
        "default",
        "mirrored",
        "filmstrip",
        "rail",
        "multiview",
        "mirrored_rail",
        "filmstrip_rail",
        "mirrored_multiview",
        "filmstrip_multiview",
    ],
)
def test_layout_preserves_viewer_and_gallery(qtbot, cfg_kwargs: dict) -> None:
    window = _make_window(qtbot)
    # Tabs show the viewer page once the start tab holds a study (Э9); the
    # placeholder hides the whole content area while the tab is empty.
    _publish_one_study(window)
    _apply(window, **cfg_kwargs)

    assert _viewer_in_content_tree(window)
    if not cfg_kwargs.get("multiview"):
        # Under Multiview the viewers live in the panes (checked below), so
        # the stack page is moot; otherwise the loaded study owns the page.
        assert window._viewer_stack.currentWidget() is window._viewer
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
    _publish_one_study(window)
    gallery_id = id(window._gallery)

    _apply(window, preset=PRESET_FILMSTRIP)
    assert window._gallery.isVisible()
    assert window._bottom_container is not None

    _apply(window)
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
    window._multiview_mode = True
    window._rebuild_layout()

    assert window._viewer_stack.currentWidget() is window._start_page
    assert _holds(window, window._content_layout, window._viewer_stack)
    assert window._pane_left is None

    window._has_loaded_study = True
    window._rebuild_layout()
    assert window._pane_left is not None
    pane_left = window._pane_left
    assert window._content_splitter.indexOf(pane_left) >= 0

    window.show_empty_start_page()
    assert window._viewer_stack.currentWidget() is window._start_page
    assert _holds(window, window._content_layout, window._viewer_stack)
    assert pane_left.isHidden()

    window._has_loaded_study = True
    window._rebuild_layout()
    assert window._pane_left is pane_left
    assert not pane_left.isHidden()
    assert window._content_splitter.indexOf(pane_left) >= 0


def test_empty_studies_reveal_start_page_in_multiview_and_restore_on_reload(qtbot) -> None:
    window = _make_window(qtbot)
    window._has_loaded_study = True
    window._multiview_mode = True
    window._rebuild_layout()
    pane = window._pane_left
    assert pane is not None

    window._on_studies_loaded([])
    assert not window._has_loaded_study
    assert window._viewer_stack.currentWidget() is window._start_page
    assert _holds(window, window._content_layout, window._viewer_stack)
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

    assert _holds(window, window._content_splitter, window._viewer_stack)
    assert window._viewer_stack.currentWidget() is window._start_page


def test_mmode_wraps_a_direct_viewer_stack_layout(qtbot) -> None:
    window = _make_window(qtbot)
    window._layout_document = LayoutConfigV2(preset=PRESET_FILMSTRIP)
    window._rebuild_layout()
    assert _holds(window, window._content_layout, window._viewer_stack)

    window._activate_mmode()
    assert _holds(window, window._content_layout, window._mmode_vertical_splitter)

    window._finish_mmode_deactivation()
    QApplication.processEvents()
    assert _holds(window, window._content_layout, window._viewer_stack)
    assert window._viewer_stack.currentWidget() is window._start_page


def test_main_viewer_is_restored_when_multiview_is_reenabled(qtbot) -> None:
    window = _make_window(qtbot)
    window._has_loaded_study = True
    window._multiview_mode = True
    window._rebuild_layout()
    pane = window._pane_left
    assert pane is not None
    assert pane.layout().indexOf(window._viewer) >= 0

    window._multiview_mode = False
    window._rebuild_layout()
    assert window._viewer_stack.indexOf(window._viewer) >= 0

    window._multiview_mode = True
    window._rebuild_layout()
    assert window._pane_left is pane
    assert pane.layout().indexOf(window._viewer) >= 0
    assert window._viewer_stack.indexOf(window._viewer) < 0


def test_rail_evicts_the_panel_only_where_the_panel_has_no_slot(qtbot) -> None:
    """UI-2 PR-3, §4.2: under a filmstrip the rail sits beside the strip, so the
    wide panel keeps its right slot; in the classic layout the rail takes its place."""
    window = _make_window(qtbot)
    _publish_one_study(window)

    _apply(window, preset=PRESET_FILMSTRIP, tool_buttons="rail")
    assert window._tool_rail.isVisible()
    assert window._tool_panel.isVisible()
    assert window._content_layout.indexOf(window._tool_panel) >= 0

    _apply(window, preset=PRESET_CLASSIC, tool_buttons="rail")
    assert window._tool_rail.isVisible()
    assert not window._tool_panel.isVisible()

    _apply(window, preset=PRESET_CLASSIC, tool_buttons="row")
    assert window._tool_panel.isVisible()
    assert window._content_layout.indexOf(window._tool_panel) < 0


def test_swap_then_default_restores_viewer(qtbot) -> None:
    window = _make_window(qtbot)
    _apply(window, preset=PRESET_MIRRORED)
    assert window._viewer_stack.currentWidget() is window._start_page

    _apply(window)
    assert window._viewer_stack.currentWidget() is window._start_page
    assert _holds(window, window._content_splitter, window._viewer_stack)
    assert window._content_splitter.indexOf(window._tool_panel) >= 0


def test_horizontal_swap_activity_toggle_restores_tool_panel(qtbot) -> None:
    """Regression: horizontal gallery + preset and button-view toggles must not
    leave an empty 280 px strip where the wide panel used to sit.

    UI-2 PR-3 replaces the interim bar's tab buttons with the rail's single
    «показать / скрыть боковые панели»: the pin is what survives a rebuild, while
    the panel's own tab bar (Э11) is now the only thing that selects a tab.
    """
    window = _make_window(qtbot)
    _publish_one_study(window)
    _apply(window, preset=PRESET_FILMSTRIP)
    _apply(window, preset=PRESET_FILMSTRIP)
    _apply(window, preset=PRESET_CLASSIC, tool_buttons="rail")

    window._on_rail_panels_toggled()
    assert window._content_layout.indexOf(window._tool_panel) >= 0
    assert window._tool_panel.isVisible()
    assert window._tool_panel._tabs.isVisible()

    window._on_rail_panels_toggled()
    assert not window._tool_panel.isVisible()

    _apply(window, preset=PRESET_FILMSTRIP, tool_buttons="rail")
    assert window._content_layout.indexOf(window._tool_panel) >= 0
    assert window._tool_panel.isVisible()
    assert window._tool_panel._tabs.isVisible()

    _apply(window, preset=PRESET_CLASSIC, tool_buttons="rail")
    window._on_rail_panels_toggled()
    assert window._content_layout.indexOf(window._tool_panel) >= 0

    _apply(window, preset=PRESET_CLASSIC, tool_buttons="panel")
    assert window._content_layout.indexOf(window._tool_panel) < 0
    assert window._tool_panel.isVisible()


def test_calculator_override_reaches_the_controller(qtbot) -> None:
    window = _make_window(qtbot)
    controller = window._controller
    window._tool_panel.calculators.study_input_changed.emit("hr", 70.0)
    assert controller._calculator_inputs.manual(controller._resolve_study_uid()) == {"hr": 70.0}


def test_native_window_frame_toggle_updates_flags_and_hides_custom_controls(qtbot) -> None:
    """UI-1 PR-1 (UA-20): 'Системная рамка окна' switches between frameless and OS frame."""
    from PySide6.QtCore import QPoint, Qt

    window = _make_window(qtbot)
    assert window.is_native_window_frame() is False
    assert bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint) is True
    assert window._title_bar.window_controls_visible() is True

    window.apply_window_frame_mode(True)
    assert window.is_native_window_frame() is True
    assert bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint) is False
    assert window._title_bar.window_controls_visible() is False
    assert window.chrome_hit_test(QPoint(2, 2)) is not None

    window.apply_window_frame_mode(False)
    assert window.is_native_window_frame() is False
    assert bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint) is True
    assert window._title_bar.window_controls_visible() is True


def test_main_window_chrome_hit_test_and_native_event(qtbot) -> None:
    """UI-1 PR-1 (UA-01, UA-03): MainWindow hit-test & Win32 nativeEvent return HTMAXBUTTON/borders."""
    import ctypes

    from PySide6.QtCore import QPoint

    from echo_personal_tool.presentation.window_chrome import (
        HTCLIENT,
        HTMAXBUTTON,
        HTTOPLEFT,
        MSG,
        WM_NCHITTEST,
        Zone,
        pack_lparam_point,
    )

    window = _make_window(qtbot)
    window.resize(1280, 800)
    window.show()
    QApplication.processEvents()

    # Top-left corner resolves to TOP_LEFT in normal state
    assert window.chrome_hit_test(QPoint(2, 2)) is Zone.TOP_LEFT

    # Maximize button center of the *title bar* resolves to Zone.MAX (HTMAXBUTTON)
    max_btn = window._title_bar._btn_maximize
    max_center_in_win = max_btn.mapTo(window, max_btn.rect().center())
    # Ensure y is below the 6px top resize border
    probe = QPoint(max_center_in_win.x(), max(max_center_in_win.y(), 12))
    assert window.chrome_hit_test(probe) is Zone.MAX

    # Interactive button in SystemBar (the patient row after PR-3) resolves to Zone.CLIENT
    open_btn = window._system_bar._btn_open
    open_center_in_win = open_btn.mapTo(window, open_btn.rect().center())
    open_probe = QPoint(open_center_in_win.x(), max(open_center_in_win.y(), 12))
    assert window.chrome_hit_test(open_probe) is Zone.CLIENT

    # UI-1 PR-2: the caption row mixes draggable space with interactive controls —
    # the free space before the command field still moves the window (UA-02), while
    # a study tab takes the click (UA-19).
    title_mid = window._title_bar.height() // 2
    strip_right = window._title_bar.tab_strip.mapTo(window, window._title_bar.tab_strip.rect().topRight()).x()
    field_left = window._title_bar.command_field.mapTo(window, QPoint(0, 0)).x()
    assert field_left > strip_right, "the mockup keeps a free caption gap between them"
    gap_probe = QPoint((strip_right + field_left) // 2, title_mid)
    assert window.chrome_hit_test(gap_probe) is Zone.CAPTION

    tab = window._title_bar.tab_strip._bar
    tab_rect = tab.tabRect(0)
    tab_center = tab.mapTo(window, tab_rect.center())
    assert window.chrome_hit_test(tab_center) is Zone.CLIENT

    # The «+» of a new tab is gone (acceptance 2026-10-23, item 7): the gap
    # between the tabs and the command field is plain caption again.
    assert window._title_bar.findChild(QWidget, "newTabButton") is None

    # Verify nativeEvent delegation to Win32Chrome with a stubbed screen_to_client
    class _StubApi:
        def is_zoomed(self, _hwnd: int) -> bool:
            return False

        def screen_to_client(self, _hwnd: int, sx: int, sy: int) -> tuple[int, int]:
            return sx, sy

    window._win32_chrome._api = _StubApi()  # type: ignore[assignment]
    msg_max = MSG(
        hWnd=int(window.winId()),
        message=WM_NCHITTEST,
        wParam=0,
        lParam=pack_lparam_point(probe.x(), probe.y()),
    )
    assert window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg_max)) == (True, HTMAXBUTTON)

    msg_open = MSG(
        hWnd=int(window.winId()),
        message=WM_NCHITTEST,
        wParam=0,
        lParam=pack_lparam_point(open_probe.x(), open_probe.y()),
    )
    assert window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg_open)) == (True, HTCLIENT)

    msg_corner = MSG(
        hWnd=int(window.winId()),
        message=WM_NCHITTEST,
        wParam=0,
        lParam=pack_lparam_point(2, 2),
    )
    assert window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg_corner)) == (True, HTTOPLEFT)


# ── The caption of UI-1 PR-2: tabs, «+», the command field, the app menu ──


def test_app_menu_of_the_logo_carries_the_window_commands(qtbot) -> None:
    """The logo replaces the scattered bar buttons: settings, layout, help, about, quit (§4.1)."""
    window = _make_window(qtbot)
    menu = window._title_bar.app_button.menu()
    assert menu is not None, "the logo button opens the application menu"
    assert menu.objectName() == "appMenu"

    labels = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert labels == [
        tr("app_menu.settings"),
        tr("app_menu.layout"),
        tr("app_menu.references"),
        tr("app_menu.help"),
        tr("app_menu.guide"),
        tr("app_menu.about"),
        tr("app_menu.quit"),
    ]

    layout_menu = next(action.menu() for action in menu.actions() if action.menu() is not None)
    presets = [
        action for action in layout_menu.actions() if isinstance(action.data(), tuple) and action.data()[0] == "preset"
    ]
    assert [action.data()[1] for action in presets] == [PRESET_CLASSIC, PRESET_MIRRORED, PRESET_FILMSTRIP]
    assert all(action.isCheckable() for action in presets)
    assert [action.isChecked() for action in presets] == [True, False, False]
    tools_menu = layout_menu.findChild(QMenu, "layoutToolButtonsMenu")
    assert tools_menu is not None
    assert len(tools_menu.actions()) == 4
    configure = [
        action
        for action in layout_menu.actions()
        if isinstance(action.data(), tuple) and action.data()[0] == "configure"
    ]
    assert len(configure) == 1


def test_fullscreen_kiosk_hides_and_restores_the_caption(qtbot) -> None:
    """F11 hides the whole caption row, not just the bar (spec §6, fullscreen hint)."""
    window = _make_window(qtbot)

    window._enter_fullscreen_kiosk()
    assert window._title_bar.isHidden()
    assert window._system_bar.isHidden()
    assert window._tab_strip.isHidden()

    window._exit_fullscreen_kiosk()
    assert not window._title_bar.isHidden()
    assert not window._system_bar.isHidden()
    assert not window._tab_strip.isHidden()


def test_command_handlers_cover_the_whole_catalogue(qtbot) -> None:
    """Every command the field offers must do something (spec §4.1)."""
    from echo_personal_tool.presentation.command_catalog import COMMANDS

    window = _make_window(qtbot)
    handlers = window._command_handlers()
    missing = sorted(command.action for command in COMMANDS if command.action not in handlers)
    assert missing == [], f"the field would offer commands without a handler: {missing}"


def test_ctrl_k_opens_the_command_palette(qtbot, monkeypatch) -> None:
    """Ctrl+K opens the searchable command palette; the legacy field remains available."""
    import sys

    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QDialog

    from echo_personal_tool.presentation.command_catalog import command_label, commands_for_profile
    from echo_personal_tool.presentation.command_palette import CommandPalette

    opened = []

    def fake_exec(palette):
        opened.append(palette)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(CommandPalette, "exec", fake_exec)
    window = _make_window(qtbot)
    key = QKeySequence("Meta+K" if sys.platform == "darwin" else "Ctrl+K")
    shortcuts = [item for item in window.findChildren(QShortcut) if item.key() == key]
    assert shortcuts, "Ctrl+K is not installed on the window"
    assert all(item.isEnabled() for item in shortcuts)

    shortcuts[0].activated.emit()
    assert len(opened) == 1
    assert opened[0].objectName() == "commandPalette"
    expected = [command_label(command, with_shortcut=False) for command in commands_for_profile(window._profile_name)]
    assert window._title_bar._command_completer.model().stringList() == expected
    assert window._title_bar.command_field.placeholderText() == tr("title_bar.command_placeholder")


def test_command_submitted_runs_the_command_and_clears_the_field(qtbot, monkeypatch) -> None:
    """Enter in the caption field resolves the query and reports the outcome."""
    from echo_personal_tool.presentation.command_catalog import command_label, resolve_command

    window = _make_window(qtbot)
    window._title_bar.focus_command_field()
    window._title_bar.set_command_text("  caliper  ")

    calls: list[str] = []
    statuses: list[str] = []
    monkeypatch.setattr(window, "_run_command", calls.append)
    monkeypatch.setattr(window, "_show_status", statuses.append)

    window._title_bar.command_submitted.emit("caliper")

    expected = resolve_command("caliper", profile=window._profile_name)
    assert expected is not None
    assert calls == [expected.action]
    assert statuses == [tr("title_bar.command_done", label=command_label(expected))]
    assert window._title_bar.command_text() == ""
    assert window._title_bar.focusWidget() is window._title_bar.command_field


def test_command_submitted_reports_an_unknown_query(qtbot, monkeypatch) -> None:
    """A query that matches nothing keeps the field in place and says so."""
    window = _make_window(qtbot)
    statuses: list[str] = []
    monkeypatch.setattr(window, "_show_status", statuses.append)

    window._title_bar.set_command_text("эрзац-команда")
    window._title_bar.command_submitted.emit("эрзац-команда")

    assert statuses == [tr("title_bar.command_empty", query="эрзац-команда")]
    assert window._title_bar.command_text() == "эрзац-команда", "the query is not thrown away"


def test_title_bar_window_controls_follow_the_frame_mode(qtbot) -> None:
    """The caption owns the window controls; the system bar owns none (spec §4.1)."""
    from PySide6.QtWidgets import QWidget

    window = _make_window(qtbot)
    assert window._title_bar.caption_buttons()
    assert window._system_bar.caption_buttons() == {}
    for object_name in ("windowControls", "minimizeButton", "maximizeButton", "closeButton"):
        assert window._title_bar.findChild(QWidget, object_name) is not None, object_name
        assert window._system_bar.findChild(QWidget, object_name) is None, object_name


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
