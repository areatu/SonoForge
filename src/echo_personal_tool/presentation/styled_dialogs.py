"""Styled file dialogs for dark theme."""

from __future__ import annotations

import re
import sys
import weakref
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QSplitter, QWidget

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_palette

if TYPE_CHECKING:
    from PySide6.QtGui import QScreen


def styled_open_file(
    parent: QWidget | None = None,
    title: str = tr("styled_dialogs.open_file"),
    directory: str = "",
    filter: str = tr("styled_dialogs.all_files"),
) -> tuple[str, str]:
    """Open file dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return (files[0], dialog.selectedNameFilter()) if files else ("", "")
    return ("", "")


def styled_open_files(
    parent: QWidget | None = None,
    title: str = tr("styled_dialogs.open_files"),
    directory: str = "",
    filter: str = tr("styled_dialogs.all_files"),
) -> list[str]:
    """Open multiple files dialog with dark theme styling."""
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _style_dialog(dialog)
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        return dialog.selectedFiles()
    return []


def styled_save_file(
    parent: QWidget | None = None,
    title: str = tr("styled_dialogs.save_file"),
    directory: str = "",
    filter: str = tr("styled_dialogs.all_files"),
) -> tuple[str, str]:
    """Save file dialog with dark theme styling.

    Uses a non-native QFileDialog so the theme applies.  Native dialogs
    auto-append the selected filter's extension; this custom dialog does not,
    so we replicate that behaviour to avoid saving files without a usable
    extension (which breaks e.g. QPixmap.save() and cv2.VideoWriter()).
    """
    dialog = QFileDialog(parent, title, directory, filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _style_dialog(dialog)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ("", "")
    files = dialog.selectedFiles()
    if not files:
        return ("", "")
    path = files[0]
    name_filter = dialog.selectedNameFilter()
    return (_append_extension(path, name_filter), name_filter)


def _append_extension(path: str, name_filter: str) -> str:
    """Append an extension from *name_filter* if *path* lacks a matching one."""
    path_obj = Path(path)
    match = re.search(r"\(([^()]+)\)", name_filter)
    filter_exts: list[str] = []
    if match:
        filter_exts = [p[1:] for p in match.group(1).split() if p.startswith("*")]
    if not filter_exts:
        return path
    suffix = path_obj.suffix.lower()
    if suffix:
        if suffix in filter_exts:
            return path
        # Filename has a suffix that is not part of the filter (e.g. a dot in
        # the middle of the name) — append the filter's first extension.
        return f"{path}{filter_exts[0]}"
    return f"{path}{filter_exts[0]}"


def _standard_places() -> list[tuple[str, str]]:
    """Known folders of the OS: Desktop, Documents, Downloads, OneDrive, drives.

    The paths come from ``QStandardPaths`` (Windows known folders), so a
    redirected Desktop — including OneDrive Known Folder Move — resolves to the
    real location instead of ``~/Desktop``, and the cloud folder is offered
    explicitly when the environment exposes it.
    """
    import os

    from PySide6.QtCore import QStandardPaths

    candidates = [
        ("open_folder.place_desktop", QStandardPaths.StandardLocation.DesktopLocation),
        ("open_folder.place_documents", QStandardPaths.StandardLocation.DocumentsLocation),
        ("open_folder.place_downloads", QStandardPaths.StandardLocation.DownloadLocation),
        ("open_folder.place_home", QStandardPaths.StandardLocation.HomeLocation),
    ]
    places: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, location in candidates:
        path = QStandardPaths.writableLocation(location)
        if path and path not in seen:
            seen.add(path)
            places.append((tr(key), path))

    for env_name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        path = os.environ.get(env_name, "").strip()
        if path and path not in seen:
            seen.add(path)
            places.append((tr("open_folder.place_onedrive"), path))

    if sys.platform == "win32":
        from PySide6.QtCore import QDir

        for drive in QDir.drives():
            path = drive.absolutePath()
            if path and path not in seen:
                seen.add(path)
                places.append((path.rstrip("\\/") or path, path))
    return places


def _recents_bar(dialog: QFileDialog, store) -> QWidget:
    """Bottom strip: recent folders with pin / remove / clear (Э3).

    ``QFileDialog`` has no public API for a custom sidebar section, so the
    recents live in a small strip added to the dialog's own grid layout.  The
    strip is defensive: if the layout is not a grid (platform quirk), the
    dialog still opens, just without the strip.
    """
    from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton

    bar = QWidget(dialog)
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(8, 2, 8, 6)
    layout.setSpacing(6)
    layout.addWidget(QLabel(tr("open_folder.recent_folders"), bar))

    combo = QComboBox(bar)
    combo.setObjectName("recentFoldersCombo")
    # Width follows the widest path (a font metric), not a fixed pixel count.
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    combo.setMinimumContentsLength(30)

    def populate() -> None:
        """(Re)build the list: pinned first, unavailable folders greyed out."""
        entries = store.entries()
        combo.clear()
        if not entries:
            combo.addItem(tr("open_folder.no_recent_folders"), "")
            combo.setEnabled(False)
            return
        combo.setEnabled(True)
        for index, entry in enumerate(entries):
            prefix = "★ " if entry.pinned else ""
            combo.addItem(f"{prefix}{entry.path}", entry.path)
            if not entry.exists:
                # Unavailable folders stay visible but cannot be navigated to.
                combo.model().item(index).setEnabled(False)

    populate()
    layout.addWidget(combo, 1)

    pin_button = QPushButton(tr("open_folder.pin"), bar)
    pin_button.setObjectName("recentPinButton")
    remove_button = QPushButton(tr("open_folder.remove"), bar)
    remove_button.setObjectName("recentRemoveButton")
    clear_button = QPushButton(tr("open_folder.clear"), bar)
    clear_button.setObjectName("recentClearButton")

    def selected() -> str:
        return str(combo.currentData() or "")

    def refresh() -> None:
        populate()
        update_buttons()

    def update_buttons() -> None:
        path = selected()
        pin_button.setEnabled(bool(path))
        remove_button.setEnabled(bool(path))
        pin_button.setText(tr("open_folder.unpin") if path and store.is_pinned(path) else tr("open_folder.pin"))

    def navigate(index: int) -> None:
        path = str(combo.itemData(index) or "")
        if path:
            dialog.setDirectory(path)

    def toggle_pin() -> None:
        path = selected()
        if path:
            store.toggle_pinned(path)
            refresh()

    def remove_selected() -> None:
        path = selected()
        if path:
            store.remove(path)
            refresh()

    combo.activated.connect(navigate)
    combo.currentIndexChanged.connect(update_buttons)
    pin_button.clicked.connect(toggle_pin)
    remove_button.clicked.connect(remove_selected)
    clear_button.clicked.connect(lambda: (store.clear(), refresh()))
    update_buttons()

    layout.addWidget(pin_button)
    layout.addWidget(remove_button)
    layout.addWidget(clear_button)
    return bar


# --- Open Folder geometry ---------------------------------------------------
#
# Reference layout, pinned to a 1920x1200 screen: a 750x600 dialog whose
# section divider (the splitter handle between "places" and the file list)
# sits 200 px from the left edge.  Everything else is that layout scaled to
# the actual screen, so the dialog keeps the same share of the display.

_OPEN_FOLDER_REF_SCREEN = (1920, 1200)
_OPEN_FOLDER_REF_WIDTH = 750
_OPEN_FOLDER_REF_HEIGHT = 600
_OPEN_FOLDER_REF_DIVIDER = 200
_OPEN_FOLDER_MIN_SCALE = 0.7
_OPEN_FOLDER_MAX_SCALE = 1.5
#: The places column never shrinks below this, and never eats more than 45 %
#: of the dialog, so the file list stays usable on small screens.
_OPEN_FOLDER_MIN_DIVIDER = 160
_OPEN_FOLDER_MAX_DIVIDER = 320
#: Keep this much of the work area free around the dialog (per side).
_OPEN_FOLDER_WORK_AREA_MARGIN = 16


def open_folder_geometry(screen: QScreen | None = None) -> tuple[int, int, int]:
    """``(width, height, divider_x)`` for the Open Folder dialog, logical px.

    The scale is derived from the *physical* size of *screen*
    (``geometry() * devicePixelRatio()``), not from the logical one, so a
    desktop scale factor (100 / 125 / 150 % …, applied by Qt through
    ``QT_SCALE_FACTOR``) grows the dialog together with the fonts instead of
    squeezing the same content into fewer logical pixels.

    On the reference 1920x1200 screen at any scale factor this returns the
    reference layout: ``(750, 600, 200)``.
    """
    ref_width, ref_height = _OPEN_FOLDER_REF_SCREEN
    if screen is None:
        return (_OPEN_FOLDER_REF_WIDTH, _OPEN_FOLDER_REF_HEIGHT, _OPEN_FOLDER_REF_DIVIDER)

    available = screen.availableGeometry().size()
    try:
        ratio = float(screen.devicePixelRatio() or 1.0)
    except (AttributeError, TypeError):
        ratio = 1.0

    # Work area first: with no screen information there is nothing to adapt to.
    if available.width() <= 0 or available.height() <= 0:
        return (_OPEN_FOLDER_REF_WIDTH, _OPEN_FOLDER_REF_HEIGHT, _OPEN_FOLDER_REF_DIVIDER)

    physical = (screen.geometry().width() * ratio, screen.geometry().height() * ratio)
    scale = min(physical[0] / ref_width, physical[1] / ref_height)
    scale = max(_OPEN_FOLDER_MIN_SCALE, min(_OPEN_FOLDER_MAX_SCALE, scale))

    width = min(round(_OPEN_FOLDER_REF_WIDTH * scale), available.width() - 2 * _OPEN_FOLDER_WORK_AREA_MARGIN)
    height = min(round(_OPEN_FOLDER_REF_HEIGHT * scale), available.height() - 2 * _OPEN_FOLDER_WORK_AREA_MARGIN)
    width = max(width, 320)
    height = max(height, 240)

    divider = round(_OPEN_FOLDER_REF_DIVIDER * scale)
    max_divider = min(_OPEN_FOLDER_MAX_DIVIDER, round(width * 0.45), width - 120)
    divider = max(_OPEN_FOLDER_MIN_DIVIDER, min(divider, max_divider))
    return (width, height, divider)


def _dialog_screen(dialog: QFileDialog) -> QScreen | None:
    """The screen the dialog belongs to: its parent's, then the primary one."""
    parent = dialog.parentWidget()
    if parent is not None:
        screen = parent.screen()
        if screen is not None:
            return screen
    screen = dialog.screen()
    if screen is not None:
        return screen
    return QApplication.primaryScreen()


def _apply_open_folder_geometry(dialog: QFileDialog, screen: QScreen | None = None) -> None:
    """Resize *dialog* and pin its section divider for the current screen.

    Everything is defensive: a missing layout or splitter must leave the
    dialog usable (default Qt sizes) rather than make it fail to open.
    """
    try:
        if screen is None:
            screen = _dialog_screen(dialog)
        width, height, divider = open_folder_geometry(screen)
        dialog.resize(width, height)

        layout = dialog.layout()
        if layout is None:
            return
        # Lay out now: the splitter's position is only known once the grid
        # has been activated, and the divider is measured from the dialog edge.
        layout.activate()
        splitter = dialog.findChild(QSplitter, "splitter")
        if splitter is None or splitter.count() < 2:
            return
        handle_width = splitter.handleWidth()
        sidebar_width = divider - splitter.x() - handle_width // 2
        sidebar_width = max(48, sidebar_width)
        rest = max(64, splitter.width() - sidebar_width - handle_width)
        splitter.setSizes([sidebar_width, rest])
    except Exception:  # noqa: BLE001 - geometry must never block folder picking
        import logging

        logging.getLogger(__name__).debug("Could not apply the Open Folder geometry", exc_info=True)


def styled_select_directory(
    parent: QWidget | None = None,
    title: str = tr("styled_dialogs.select_folder"),
    directory: str = "",
    *,
    remember: bool = True,
) -> str:
    """Select directory dialog with dark theme styling, places and recents.

    Starts in ``directory`` (or in the most recent existing folder), shows the
    OS known folders and recent folders in the sidebar, and offers an explicit
    recents strip with pin / remove / clear (Э3).  Pass ``remember=False`` for
    pickers that are not about patient folders (settings, reference folder).
    """
    from echo_personal_tool.infrastructure.recent_store import RecentStore

    store = RecentStore()
    dialog = QFileDialog(parent, title, directory or store.last_folder() or _default_folder())
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    _add_sidebar_urls(dialog, store)
    _attach_recents_bar(dialog, store)
    _apply_open_folder_geometry(dialog)
    _style_dialog(dialog)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    files = dialog.selectedFiles()
    chosen = files[0] if files else ""
    if chosen and remember:
        store.record(chosen)
    return chosen


def _default_folder() -> str:
    """Where to start when there is no history yet.

    An empty start directory means "the process working directory" for
    ``QFileDialog``, which is never a useful first screen.
    """
    from PySide6.QtCore import QStandardPaths

    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    if documents and Path(documents).is_dir():
        return documents
    return str(Path.home())


def _add_sidebar_urls(dialog: QFileDialog, store) -> None:
    """Add the known places and the recent folders to the dialog sidebar.

    The default entries (the drive list / "Computer" node) are preserved: the
    call only appends, so a study on the D: drive stays one click away.
    """
    from PySide6.QtCore import QUrl

    defaults = list(dialog.sidebarUrls())
    known = {url.toLocalFile() for url in defaults}
    urls = list(defaults)
    for _label, path in _standard_places():
        if path and path not in known and Path(path).is_dir():
            known.add(path)
            urls.append(QUrl.fromLocalFile(path))
    for entry in store.entries():
        if entry.exists and entry.path not in known:
            known.add(entry.path)
            urls.append(QUrl.fromLocalFile(entry.path))
    if urls != defaults:
        dialog.setSidebarUrls(urls)


def _attach_recents_bar(dialog: QFileDialog, store) -> None:
    from PySide6.QtWidgets import QGridLayout

    try:
        layout = dialog.layout()
        if not isinstance(layout, QGridLayout):
            return
        bar = _recents_bar(dialog, store)
        layout.addWidget(bar, layout.rowCount(), 0, 1, layout.columnCount())
    except Exception:  # noqa: BLE001 - a missing strip must not break the dialog
        import logging

        logging.getLogger(__name__).debug("Could not attach the recents strip", exc_info=True)


def _style_dialog(dialog: QFileDialog) -> None:
    """Apply dark theme styling to file dialog."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap

    p = get_theme_palette()

    # Apply palette to all child widgets recursively
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(p["bg_panel"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(p["bg_panel"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(p["bg_control"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(p["bg_control"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(p["bg_control"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(p["accent_tab"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(p["accent_tab"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(p["accent_tab"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    dialog.setPalette(palette)

    # Recursively apply palette to all children
    def apply_palette(widget):
        widget.setPalette(palette)
        for child in widget.findChildren(QWidget):
            child.setPalette(palette)
            # For buttons with icons, recolor icon to text color
            if child.__class__.__name__ in ("QToolButton", "QPushButton"):
                old_icon = child.icon()
                if not old_icon.isNull():
                    pixmap = old_icon.pixmap(16, 16)
                    if not pixmap.isNull():
                        from PySide6.QtGui import QImage, QPainter

                        image = QImage(16, 16, QImage.Format.Format_ARGB32)
                        image.fill(Qt.GlobalColor.transparent)
                        painter = QPainter(image)
                        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                        painter.drawPixmap(0, 0, pixmap)
                        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                        painter.fillRect(image.rect(), QColor(p["text"]))
                        painter.end()
                        child.setIcon(QIcon(QPixmap.fromImage(image)))

    apply_palette(dialog)

    dialog.setStyleSheet(f"""
        * {{
            color: {p["text"]};
        }}
        QFileDialog {{
            background: {p["bg_panel"]};
        }}
        QTreeView {{
            background: {p["bg_panel"]};
            border: 1px solid {p["border"]};
        }}
        QTreeView::item {{
            padding: 4px;
        }}
        QTreeView::item:selected {{
            background: {p["accent_tab"]};
            color: {p["progress_text"]};
        }}
        QTreeView::item:hover {{
            background: {p["bg_button_hover"]};
        }}
        QTreeView::section {{
            background: {p["bg_control"]};
            border: 1px solid {p["border"]};
            padding: 4px;
        }}
        QPushButton {{
            background: {p["bg_control"]};
            border: 1px solid {p["border"]};
            border-radius: 4px;
            padding: 6px 12px;
            min-width: 60px;
        }}
        QPushButton:hover {{
            background: {p["bg_button_hover"]};
        }}
        QPushButton:pressed {{
            background: {p["bg_button_pressed"]};
        }}
        QToolButton {{
            background: {p["bg_control"]};
            border: 1px solid {p["border"]};
            border-radius: 4px;
            padding: 4px;
            min-width: 24px;
            min-height: 24px;
        }}
        QToolButton:hover {{
            background: {p["bg_button_hover"]};
        }}
        QToolButton:pressed {{
            background: {p["bg_button_pressed"]};
        }}
        QLineEdit {{
            background: {p["bg_panel"]};
            border: 1px solid {p["border"]};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QComboBox {{
            background: {p["bg_control"]};
            border: 1px solid {p["border"]};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QComboBox::drop-down {{
            border: none;
        }}
        QComboBox QAbstractItemView {{
            background: {p["bg_control"]};
            selection-background-color: {p["accent_tab"]};
        }}
    """)


def localize_dialog_button_box(
    box: QDialogButtonBox,
    *,
    overrides: dict[QDialogButtonBox.StandardButton, str] | None = None,
) -> None:
    """Translate standard buttons and keep them current after a language switch."""
    from echo_personal_tool.infrastructure.i18n import register_ui_reload, unregister_ui_reload

    standard = QDialogButtonBox.StandardButton
    translations = (
        (standard.Ok, "button.ok"),
        (standard.Cancel, "button.cancel"),
        (standard.Close, "button.close"),
        (standard.Yes, "button.yes"),
        (standard.No, "button.no"),
        (standard.Apply, "button.apply"),
        (standard.Save, "button.save"),
        (standard.Discard, "button.discard"),
        (standard.RestoreDefaults, "button.restore_defaults"),
        (standard.Reset, "button.reset"),
        (standard.Help, "button.help"),
        (standard.Open, "button.open"),
        (standard.Retry, "button.retry"),
        (standard.Ignore, "button.ignore"),
        (standard.Abort, "button.abort"),
        (standard.YesToAll, "button.yes_to_all"),
        (standard.NoToAll, "button.no_to_all"),
        (standard.SaveAll, "button.save_all"),
    )
    box_ref = weakref.ref(box)

    def _refresh() -> None:
        target = box_ref()
        if target is None:
            unregister_ui_reload(_refresh)
            return
        for button_id, key in translations:
            button = target.button(button_id)
            if button is not None:
                button.setText(tr((overrides or {}).get(button_id, key)))

    register_ui_reload(_refresh)
    box.destroyed.connect(lambda *_args: unregister_ui_reload(_refresh))
    _refresh()


def _icon_device_pixel_ratio() -> float:
    """Device pixel ratio of the screen the dialog will appear on (Э4)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1.0
    return max(1.0, float(screen.devicePixelRatio()))


def theme_button_box_icons(box: QDialogButtonBox, *, refresh: bool = False) -> None:
    """Add theme-contrast icons to standard OK / Cancel buttons.

    A themed checkmark (✓) is added to the **OK** button and a
    contrasting close / cross (✗) icon to **Cancel** / **Close**.
    Icons use *text_dim* color — light on dark themes, dark on light themes —
    so they are visible regardless of the active palette. Pass ``refresh=True``
    after a palette change on a box whose icons are managed by this helper.
    Otherwise existing (possibly custom) icons are kept.

    Mirrors the icon styling already present in the *Open folder…* dialog's
    :func:`_style_dialog`, extending it to custom QDialogButtonBox buttons.
    """

    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    p = get_theme_palette()
    icon_color = p["text_dim"]

    def _svg_icon(name: str) -> QIcon:
        from echo_personal_tool.resources import icons

        svg_path = str(icons.__path__[0]) + f"/{name}.svg"
        from pathlib import Path

        svg_file = Path(svg_path)
        if not svg_file.is_file():
            return QIcon()
        svg_text = svg_file.read_text(encoding="utf-8").replace("currentColor", icon_color)
        renderer = QSvgRenderer(svg_text.encode("utf-8"))
        # Rasterize at the screen's device pixel ratio: a 16 px pixmap on a
        # 150–200 % screen was drawn blurred (Э4, «иконки — сразу size × dpr»).
        dpr = _icon_device_pixel_ratio()
        side = int(round(16 * dpr))
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(dpr)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
    if ok_btn is not None and (refresh or ok_btn.icon().isNull()):
        ok_btn.setIcon(_svg_icon("ok"))
        ok_btn.setIconSize(QSize(16, 16))

    cancel_btn = box.button(QDialogButtonBox.StandardButton.Cancel)
    if cancel_btn is not None and (refresh or cancel_btn.icon().isNull()):
        cancel_btn.setIcon(_svg_icon("close"))
        cancel_btn.setIconSize(QSize(16, 16))

    close_btn = box.button(QDialogButtonBox.StandardButton.Close)
    if close_btn is not None and (refresh or close_btn.icon().isNull()):
        close_btn.setIcon(_svg_icon("close"))
        close_btn.setIconSize(QSize(16, 16))
