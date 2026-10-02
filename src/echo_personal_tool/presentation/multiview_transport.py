"""Shared transport bar of the Multiview layout.

Sits permanently under both cine panes and owns everything that is *common* to
the two clips: the playback mode, the global rate, play/pause/stop and the
synchronisation status.  In the two synchronised modes the repeat is always on,
so the bar shows it as a state instead of a toggle (spec §5.2).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from echo_personal_tool.domain.models.multiview import PlaybackMode

#: Rates offered in the transport combo, in display order.
_RATE_STEPS: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)

_MODE_KEYS = {
    PlaybackMode.INDEPENDENT: "multiview.mode.independent",
    PlaybackMode.COMMON_WINDOW: "multiview.mode.common_window",
    PlaybackMode.EVENT_CYCLE: "multiview.mode.event_cycle",
}


class MultiViewTransportBar(QWidget):
    """Common transport for both panes."""

    mode_changed = Signal(object)  # PlaybackMode
    play_pause_clicked = Signal()
    stop_clicked = Signal()
    rate_changed = Signal(float)
    cycle_count_changed = Signal(int)
    unlink_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("multiviewTransport")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel(self._tr("multiview.transport.mode")))

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons: dict[PlaybackMode, QPushButton] = {}
        for mode in (PlaybackMode.INDEPENDENT, PlaybackMode.COMMON_WINDOW, PlaybackMode.EVENT_CYCLE):
            button = QPushButton(self._tr(_MODE_KEYS[mode]))
            button.setObjectName(f"multiviewMode_{mode.value}")
            button.setCheckable(True)
            button.setChecked(mode is PlaybackMode.INDEPENDENT)
            button.clicked.connect(lambda _checked=False, mode=mode: self.mode_changed.emit(mode))
            self._mode_group.addButton(button)
            self._mode_buttons[mode] = button
            layout.addWidget(button)

        self._play_button = QPushButton(self._tr("multiview.transport.play"))
        self._play_button.setObjectName("multiviewTransportPlay")
        self._play_button.clicked.connect(self.play_pause_clicked.emit)
        layout.addWidget(self._play_button)

        self._stop_button = QPushButton(self._tr("multiview.transport.stop"))
        self._stop_button.setObjectName("multiviewTransportStop")
        self._stop_button.setToolTip(self._tr("multiview.transport.stop_tooltip"))
        self._stop_button.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self._stop_button)

        layout.addWidget(QLabel(self._tr("multiview.transport.rate")))

        self._rate_combo = QComboBox()
        self._rate_combo.setObjectName("multiviewTransportRate")
        for rate in _RATE_STEPS:
            self._rate_combo.addItem(f"{rate:g}×", rate)
        self._rate_combo.setCurrentText("1×")
        self._rate_combo.currentIndexChanged.connect(self._on_rate_index_changed)
        layout.addWidget(self._rate_combo)

        self._cycle_label = QLabel(self._tr("multiview.transport.cycles"))
        layout.addWidget(self._cycle_label)

        self._cycle_combo = QComboBox()
        self._cycle_combo.setObjectName("multiviewTransportCycles")
        self._cycle_combo.addItem(self._tr("multiview.cycles.one"), 1)
        self._cycle_combo.addItem(self._tr("multiview.cycles.two"), 2)
        self._cycle_combo.setCurrentIndex(0)
        self._cycle_combo.currentIndexChanged.connect(self._on_cycle_index_changed)
        layout.addWidget(self._cycle_combo)

        self._unlink_button = QPushButton(self._tr("multiview.transport.unlink"))
        self._unlink_button.setObjectName("multiviewTransportUnlink")
        self._unlink_button.setToolTip(self._tr("multiview.transport.unlink_tooltip"))
        self._unlink_button.clicked.connect(self.unlink_clicked.emit)
        layout.addWidget(self._unlink_button)

        layout.addStretch(1)

        self._status_label = QLabel("—")
        self._status_label.setObjectName("multiviewTransportStatus")
        layout.addWidget(self._status_label)

        self._left_rate_label = QLabel("—")
        self._left_rate_label.setObjectName("multiviewTransportRateLeft")
        layout.addWidget(self._left_rate_label)

        self._right_rate_label = QLabel("—")
        self._right_rate_label.setObjectName("multiviewTransportRateRight")
        layout.addWidget(self._right_rate_label)

        self._is_playing = False
        self.refresh_mode(PlaybackMode.INDEPENDENT)

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _tr(key: str, **kwargs: str) -> str:
        from echo_personal_tool.infrastructure.i18n import tr

        return tr(key, **kwargs)

    # ── state ───────────────────────────────────────────────────────

    def refresh_mode(self, mode: PlaybackMode) -> None:
        """Show only the controls that make sense for ``mode``."""
        button = self._mode_buttons.get(mode)
        if button is not None:
            button.setChecked(True)
        synchronized = mode is not PlaybackMode.INDEPENDENT
        self._cycle_combo.setVisible(mode is PlaybackMode.EVENT_CYCLE)
        self._cycle_label.setVisible(mode is PlaybackMode.EVENT_CYCLE)
        self._unlink_button.setVisible(synchronized)
        self._left_rate_label.setVisible(synchronized)
        self._right_rate_label.setVisible(synchronized)
        self._play_button.setText(
            self._tr("multiview.transport.pause") if self._is_playing else self._tr("multiview.transport.play")
        )
        self._stop_button.setEnabled(synchronized)

    def set_playing(self, playing: bool) -> None:
        self._is_playing = playing
        self._play_button.setText(
            self._tr("multiview.transport.pause") if playing else self._tr("multiview.transport.play")
        )

    def set_rate(self, rate: float) -> None:
        for index in range(self._rate_combo.count()):
            if abs(float(self._rate_combo.itemData(index)) - rate) < 1e-6:
                self._rate_combo.setCurrentIndex(index)
                return
        # A rate outside the preset list (should not happen: it is clamped).
        self._rate_combo.setCurrentText(f"{rate:g}×")

    def set_cycle_count(self, cycle_count: int) -> None:
        index = self._cycle_combo.findData(int(cycle_count))
        if index >= 0:
            self._cycle_combo.setCurrentIndex(index)

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.setToolTip(text)

    def set_pane_rates(self, left: str, right: str) -> None:
        self._left_rate_label.setText(left)
        self._left_rate_label.setToolTip(left)
        self._right_rate_label.setText(right)
        self._right_rate_label.setToolTip(right)

    # ── slots ───────────────────────────────────────────────────────

    def _on_rate_index_changed(self, index: int) -> None:
        if index < 0:
            return
        rate = self._rate_combo.itemData(index)
        if rate is not None:
            self.rate_changed.emit(float(rate))

    def _on_cycle_index_changed(self, index: int) -> None:
        if index < 0:
            return
        value = self._cycle_combo.itemData(index)
        if value is not None:
            self.cycle_count_changed.emit(int(value))
