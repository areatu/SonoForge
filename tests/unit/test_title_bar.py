"""The window title bar of UI-1 PR-2: tabs, command field, window controls (spec §4.1).

The bar is the row the earlier PR-1 contracts point at: the window controls it
owns are the ones ``WM_NCHITTEST`` reports as ``HTMAXBUTTON`` (Snap Layouts),
its empty space drags the window and the tabs live inside it. These tests pin
the geometry of §4.1 (38 px row, 46 px window controls), the localisation of the
buttons, the command field (Ctrl+K, Enter, Escape) and the theme discipline of
the row — its stylesheet paints tokens only.
"""

from __future__ import annotations

import re

import pytest
from PySide6.QtWidgets import QWidget

from echo_personal_tool.presentation.window_chrome import ZONE_TO_HT, Zone, load_icon
from echo_personal_tool.presentation.window_chrome.title_bar import (
    TITLE_BAR_HEIGHT_PX,
    WINDOW_CONTROL_WIDTH_PX,
    WindowTitleBar,
)

pytestmark = pytest.mark.gui

_COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _bar(qtbot, parent=None) -> WindowTitleBar:
    bar = WindowTitleBar(parent)
    qtbot.addWidget(bar)
    return bar


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _glyph_colour(icon, size: int = 24) -> tuple[int, int, int]:
    import collections

    image = icon.pixmap(size, size).toImage()
    colours: collections.Counter = collections.Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() >= 200:
                colours[(pixel.red(), pixel.green(), pixel.blue())] += 1
    assert colours, "the glyph rendered nothing — the icon file is missing?"
    return colours.most_common(1)[0][0]


# ── Geometry and content of the row (spec §4.1) ─────────────────────


def test_title_bar_is_the_design_row_with_46px_window_controls(qtbot) -> None:
    bar = _bar(qtbot)
    bar.show()
    qtbot.waitExposed(bar)

    assert bar.objectName() == "windowTitleBar"
    assert bar.height() == TITLE_BAR_HEIGHT_PX == 38
    for button in (bar._btn_minimize, bar._btn_maximize, bar._btn_close):
        assert button.width() == WINDOW_CONTROL_WIDTH_PX == 46
        assert button.height() == bar.height() - 1, "the controls reach the bottom border"


def test_title_bar_adopts_the_study_tabs(qtbot) -> None:
    from echo_personal_tool.presentation.tab_bar import TabStrip

    bar = _bar(qtbot)
    strip = TabStrip()
    bar.adopt_tab_strip(strip)

    assert bar.tab_strip is strip
    assert strip.parent() is bar
    assert strip.height() <= bar.height()
    # The caption carries the tabs only: the free-standing «+» was never placed
    # in the layout and covered the logo/menu button (item 7 of the 2026-10-23
    # acceptance list), so it is gone.
    assert bar.findChild(QWidget, "newTabButton") is None


def test_tabs_visibility_hides_the_strip(qtbot) -> None:
    from echo_personal_tool.presentation.tab_bar import TabStrip

    bar = _bar(qtbot)
    bar.adopt_tab_strip(TabStrip())
    bar.show()
    qtbot.waitExposed(bar)

    bar.set_tabs_visible(False)
    assert bar.tab_strip.isHidden()

    bar.set_tabs_visible(True)
    assert not bar.tab_strip.isHidden()


def test_app_menu_is_the_logo_button(qtbot) -> None:
    from PySide6.QtWidgets import QMenu

    bar = _bar(qtbot)
    menu = QMenu(bar)
    menu.addAction("Settings")
    bar.set_app_menu(menu)

    assert bar._app_button.menu() is menu
    assert not bar._app_button.icon().isNull(), "the logo is the menu button"


# ── Window controls of the caption (PR-1 contracts) ──────────────────


def test_window_controls_visibility_and_caption_buttons(qtbot) -> None:
    bar = _bar(qtbot)
    buttons = bar.caption_buttons()
    assert set(buttons) == {Zone.MIN, Zone.MAX, Zone.CLOSE}
    assert window_controls_mapping(bar) == {
        Zone.MIN: "minimizeButton",
        Zone.MAX: "maximizeButton",
        Zone.CLOSE: "closeButton",
    }
    assert bar.window_controls_visible() is True
    bar.set_window_controls_visible(False)
    assert bar.window_controls_visible() is False
    bar.set_window_controls_visible(True)
    assert bar.window_controls_visible() is True


def window_controls_mapping(bar: WindowTitleBar) -> dict[Zone, str]:
    return {zone: widget.objectName() for zone, widget in bar.caption_buttons().items() if widget is not None}


def test_maximize_button_is_the_snap_layouts_zone(qtbot) -> None:
    """HTMAXBUTTON is what Windows 11 turns into the Snap Layouts flyout (§4.3)."""
    bar = _bar(qtbot)
    assert ZONE_TO_HT[Zone.MAX] == 9  # HTMAXBUTTON


def test_window_control_buttons_emit_their_requests(qtbot) -> None:
    bar = _bar(qtbot)
    with qtbot.waitSignal(bar.minimize_requested, timeout=1000):
        bar._btn_minimize.click()
    with qtbot.waitSignal(bar.maximize_requested, timeout=1000):
        bar._btn_maximize.click()
    with qtbot.waitSignal(bar.close_requested, timeout=1000):
        bar._btn_close.click()


def test_maximize_button_localizes_and_switches_glyph(qtbot) -> None:
    """UI-1 PR-1 translated «maximize»; PR-2 keeps the pair on the new button."""
    from echo_personal_tool.infrastructure.i18n import get_language, set_language, tr

    prev = get_language()
    try:
        set_language("ru")
        bar = _bar(qtbot)
        bar.update_maximize_button(False)
        assert bar._btn_maximize.toolTip() == tr("system_bar.maximize")
        bar.update_maximize_button(True)
        assert bar._btn_maximize.toolTip() == tr("system_bar.restore")
        bar.reload_text()
        assert bar._btn_maximize.toolTip() == tr("system_bar.restore")
        assert bar._btn_minimize.toolTip() == tr("system_bar.minimize")
        assert bar._btn_close.toolTip() == tr("system_bar.close")

        set_language("en")
        bar.reload_text()
        assert bar._btn_close.toolTip() == tr("system_bar.close")
    finally:
        set_language(prev)


# ── Drag, resize, double click (spec §4.3, UA-02, UA-03) ─────────────


def _mouse_event(host, kind, pos, button, buttons):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent

    return QMouseEvent(
        kind,
        pos,
        host.mapToGlobal(pos.toPoint()).toPointF(),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_caption_drag_calls_start_system_move(qtbot, monkeypatch) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtWidgets import QMainWindow

    host = QMainWindow()
    bar = WindowTitleBar(host)
    host.setCentralWidget(bar)
    qtbot.addWidget(host)
    host.resize(800, 38)
    host.show()

    moved: list[str] = []

    class _FakeWindowHandle:
        def startSystemMove(self) -> bool:  # noqa: N802
            moved.append("startSystemMove")
            return True

    monkeypatch.setattr(host, "windowHandle", lambda: _FakeWindowHandle())
    bar.mousePressEvent(
        _mouse_event(
            host,
            QEvent.Type.MouseButtonPress,
            QPointF(400.0, 20.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    bar.mouseMoveEvent(
        _mouse_event(
            host, QEvent.Type.MouseMove, QPointF(420.0, 24.0), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton
        )
    )

    assert moved == ["startSystemMove"]


def test_top_border_press_calls_start_system_resize(qtbot, monkeypatch) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtWidgets import QMainWindow

    host = QMainWindow()
    bar = WindowTitleBar(host)
    host.setCentralWidget(bar)
    qtbot.addWidget(host)
    host.resize(800, 38)
    host.show()

    resized: list[Qt.Edge] = []

    class _FakeWindowHandle:
        def startSystemResize(self, edges: Qt.Edge) -> bool:  # noqa: N802
            resized.append(edges)
            return True

    monkeypatch.setattr(host, "windowHandle", lambda: _FakeWindowHandle())
    bar.mousePressEvent(
        _mouse_event(
            host,
            QEvent.Type.MouseButtonPress,
            QPointF(400.0, 2.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )

    assert resized == [Qt.Edge.TopEdge]


def test_double_click_maximizes(qtbot) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtWidgets import QMainWindow

    host = QMainWindow()
    bar = WindowTitleBar(host)
    host.setCentralWidget(bar)
    qtbot.addWidget(host)
    host.resize(800, 38)
    host.show()

    with qtbot.waitSignal(bar.maximize_requested, timeout=1000):
        bar.mouseDoubleClickEvent(
            _mouse_event(
                host,
                QEvent.Type.MouseButtonDblClick,
                QPointF(400.0, 20.0),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
            )
        )


def test_gestures_stand_down_with_the_native_frame(qtbot, monkeypatch) -> None:
    """UA-20: with the OS frame the bar must not start system moves of its own."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtWidgets import QMainWindow

    host = QMainWindow()
    bar = WindowTitleBar(host)
    host.setCentralWidget(bar)
    qtbot.addWidget(host)
    host.resize(800, 38)
    host.show()
    monkeypatch.setattr(host, "is_native_window_frame", lambda: True, raising=False)
    monkeypatch.setattr(
        host,
        "windowHandle",
        lambda: pytest.fail("the native frame must handle the drag itself"),
    )

    bar.mousePressEvent(
        _mouse_event(
            host,
            QEvent.Type.MouseButtonPress,
            QPointF(400.0, 20.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )


# ── The command field (spec §4.1, §7) ───────────────────────────────


def test_command_field_reports_the_submitted_text(qtbot) -> None:
    bar = _bar(qtbot)
    submitted: list[str] = []
    bar.command_submitted.connect(submitted.append)

    bar.set_command_text("  caliper  ")
    bar.command_field.returnPressed.emit()

    assert submitted == ["caliper"]


def test_command_field_escape_clears_and_leaves_the_field(qtbot) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    bar = _bar(qtbot)
    bar.show()
    qtbot.waitExposed(bar)
    bar.set_command_text("КДР")
    bar.focus_command_field()
    assert bar.focusWidget() is bar.command_field, "Ctrl+K target takes the keyboard"

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    assert bar.eventFilter(bar.command_field, event) is True
    assert bar.command_text() == ""
    assert bar.focusWidget() is not bar.command_field, "Escape returns the keyboard to the viewer"


def test_command_field_completion_choices(qtbot) -> None:
    from PySide6.QtCore import Qt

    bar = _bar(qtbot)
    bar.set_command_choices(["Открыть папку…", "Настройки…"])

    model = bar._command_completer.model()
    assert model.stringList() == ["Открыть папку…", "Настройки…"]
    assert bar._command_completer.filterMode() == Qt.MatchFlag.MatchContains


def test_reload_text_re_reads_the_placeholder(qtbot) -> None:
    from echo_personal_tool.infrastructure.i18n import get_language, set_language, tr

    prev = get_language()
    try:
        set_language("ru")
        bar = _bar(qtbot)
        assert bar.command_field.placeholderText() == bar._command_placeholder_text()
        assert bar.command_field.placeholderText().startswith(tr("title_bar.command_placeholder"))

        set_language("en")
        bar.reload_text()
        assert bar.command_field.placeholderText() == bar._command_placeholder_text()
        assert bar.command_field.placeholderText() != "Команда, измерение, клип…"
    finally:
        set_language(prev)


# ── The row paints tokens, never colours (UI-0 gate, spec §5) ───────


def test_title_bar_source_holds_no_colour_literal() -> None:
    """The row is painted from tokens; the shared sheet (pinned by goldens) is untouched."""
    import sys
    from pathlib import Path

    from echo_personal_tool.presentation.window_chrome import title_bar

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import check_ui_colors

    source = Path(title_bar.__file__).read_text(encoding="utf-8")
    assert check_ui_colors.count_literals(source) == 0


def test_title_bar_stylesheet_paints_only_theme_tokens(qtbot, monkeypatch) -> None:
    """Every colour of the scoped sheet is a value of the active palette."""
    from echo_personal_tool.presentation import dark_theme
    from echo_personal_tool.presentation.theme import palettes

    for theme in ("graphite", "dark", "light", "vscode_dark", "vscode_light"):
        monkeypatch.setattr(dark_theme, "_current_theme_mode", theme)
        bar = WindowTitleBar()
        qtbot.addWidget(bar)
        stylesheet = bar.styleSheet()
        assert stylesheet, "the title bar styles its own row"
        allowed = {value.lower() for value in palettes.PALETTES[theme].values()}
        painted = {match.group(0).lower() for match in _COLOUR_LITERAL.finditer(stylesheet)}
        assert painted, stylesheet
        assert painted <= allowed, f"{theme}: colours outside the palette: {painted - allowed}"


def test_title_bar_glyphs_take_the_text_token_and_follow_the_theme(qtbot, monkeypatch) -> None:
    from echo_personal_tool.presentation import dark_theme

    monkeypatch.setattr(dark_theme, "_current_theme_mode", "graphite")
    bar = _bar(qtbot)
    expected = _hex_to_rgb(dark_theme.get_theme_tokens()["text.1"])
    for button in (bar._btn_minimize, bar._btn_maximize, bar._btn_close):
        assert _glyph_colour(button.icon()) == expected

    monkeypatch.setattr(dark_theme, "_current_theme_mode", "vscode_dark")
    bar.reload_icons()
    other = _hex_to_rgb(dark_theme.get_theme_tokens()["text.1"])
    assert other != expected
    assert _glyph_colour(bar._btn_close.icon()) == other


def test_load_icon_returns_an_empty_icon_for_an_unknown_name() -> None:
    assert load_icon("no-such-glyph-exists").isNull()


def test_title_bar_height_grows_with_a_large_font(qtbot) -> None:
    """Э4: chrome is font-derived, so an 18 px font must not clip the row."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    previous_stylesheet = app.styleSheet() if app is not None else ""
    if app is not None:
        # An application stylesheet left by an earlier test resets widget
        # fonts on every polish (update_control_height), so the 18 px font
        # would never reach the metrics.  The real app bakes ui_font_size
        # into the QSS itself; here the font is set on the widget instead.
        app.setStyleSheet("")
    try:
        bar = _bar(qtbot)
        bar.setFont(QFont(bar.font().family(), 18))
        bar.update_control_height()

        assert bar.height() > TITLE_BAR_HEIGHT_PX
        assert bar._btn_close.height() == bar.height() - 1
        if bar.tab_strip is not None:
            assert bar.tab_strip.height() < bar.height()
    finally:
        if app is not None:
            app.setStyleSheet(previous_stylesheet)
