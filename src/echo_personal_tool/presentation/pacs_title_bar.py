"""Frameless title bar of the PACS loader («Загрузка с сервера»).

The loader is frameless on purpose — it is a sheet over the viewer — so it
carries its own 35-px bar with the title, the server/transport pills and the
close button.  Building it here rather than inside the dialog's ``_build_ui``
keeps that method reading as a list of blocks (title, search, period, filters,
master–detail, footer) instead of one ~220-line body.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.presentation.system_bar import _load_icon
from echo_personal_tool.presentation.ui_metrics import icon_button_size, title_bar_height

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping


def build_pacs_title_bar(
    dialog: QWidget,
    tokens: Mapping[str, str],
    *,
    on_close: Callable[[], None],
) -> tuple[QWidget, QLabel, QLabel, QLabel, QPushButton]:
    """Build the bar and hand back its live widgets.

    Returns ``(bar, server_pill, transport_pill, title_label, close_button)``:
    the dialog keeps the pills (it updates their text) and the close button
    (``closeEvent`` checks whether focus sits on it), the bar itself is added
    to the layout like any other row.
    """
    bar = QWidget()
    bar.setFixedHeight(title_bar_height(dialog))
    bar.setStyleSheet(f"background: {tokens['surface.0']};")
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(10, 0, 4, 0)
    layout.setSpacing(8)

    title_label = QLabel(tr("dialog.orthanc.title"))
    title_label.setStyleSheet(f"color: {tokens['text.1']}; font-weight: bold; border: none;")
    layout.addWidget(title_label)

    # The server pill says which host answered; the transport pill only appears
    # when the transport is not the plain DICOMweb path (see _update_transport_pill).
    server_pill = QLabel(tr("orthanc.checking_server"))
    server_pill.setStyleSheet(f"color: {tokens['text.2']}; border: none; padding-left: 6px;")
    layout.addWidget(server_pill)
    transport_pill = QLabel()
    transport_pill.setStyleSheet(f"color: {tokens['state.warn']}; font-weight: bold; border: none; padding-left: 6px;")
    transport_pill.hide()
    layout.addWidget(transport_pill)
    layout.addStretch(1)

    close_button = QPushButton()
    close_button.setIcon(_load_icon("close"))
    close_button.setObjectName("closeButton")
    close_button.setToolTip(tr("system_bar.close"))
    close_button.setAccessibleName(tr("system_bar.close"))
    close_button.setFixedSize(*icon_button_size(close_button, "×"))
    close_button.setStyleSheet("padding: 0px;")
    close_button.clicked.connect(on_close)
    layout.addWidget(close_button)
    return bar, server_pill, transport_pill, title_label, close_button


__all__ = ["build_pacs_title_bar"]
