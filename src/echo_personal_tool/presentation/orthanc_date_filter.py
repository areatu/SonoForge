"""Period/date filter of the PACS study browser (chips + arbitrary day).

The loader's period row used to live inside
:class:`~echo_personal_tool.presentation.orthanc_study_dialog.OrthancStudyDialog`,
which is already the largest class in the file and is ratcheted
(``scripts/check_class_size.py``): every new behaviour there needs a method
removed somewhere else.  The period is a self-contained state machine — which
chip is active, which day the picker holds, does a row survive — so it belongs
in a collaborator that owns exactly that state and nothing else.

Two rules drive the behaviour and are worth stating once:

* the period is a **client-side** filter.  ``query_studies()`` takes a single
  ``study_date``, not a range, so «за 30 дней» has always been decided by
  hiding rows that are already in the tree.  An arbitrary day follows the same
  path, which is why the filter exposes a row predicate instead of a query;
* an arbitrary day must **also** reach the server, because the wanted
  examination may simply not be among the loaded rows — that is the
  ``reload_requested`` signal, emitted when the user presses Enter.

The chip row itself is built here too (``create_period_chips`` /
``create_picker_row``), so the dialog only assembles what it gets back.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from echo_personal_tool.application.localization import tr
from echo_personal_tool.presentation.orthanc_date_picker import OrthancDatePicker

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

    from PySide6.QtWidgets import QWidget

#: Injectable clock: tests pin «now» instead of sleeping into the future.
_NowFn = Callable[[], datetime]
#: How the loader fills its list from a finished query.
_FeedFn = Callable[[list[object], "str | None"], None]

#: ``days`` value of the «date» chip: an exact day, not a lookback window.
EXACT_DATE_CHIP = -1

#: ``(days, locale key)`` of the preset chips, in display order.
PERIOD_CHIPS: tuple[tuple[int, str], ...] = (
    (0, "orthanc.date_filter_all"),
    (1, "orthanc.date_filter_1d"),
    (7, "orthanc.date_filter_7d"),
    (30, "orthanc.date_filter_30d"),
    (90, "orthanc.date_filter_90d"),
    (EXACT_DATE_CHIP, "orthanc.date_filter_day"),
)


def create_period_chips(
    parent: QWidget,
) -> tuple[QButtonGroup, dict[int, QPushButton], QPushButton]:
    """The exclusive chip group, its buttons by ``days``, and the «date» chip."""
    group = QButtonGroup(parent)
    group.setExclusive(True)
    buttons: dict[int, QPushButton] = {}
    date_chip: QPushButton | None = None
    for days, label_key in PERIOD_CHIPS:
        button = QPushButton(tr(label_key), parent)
        button.setCheckable(True)
        button.setObjectName("periodChip")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setChecked(days == 0)
        if days == EXACT_DATE_CHIP:
            button.setToolTip(tr("orthanc.date_filter_day_tooltip"))
            date_chip = button
        group.addButton(button)
        buttons[days] = button
    assert date_chip is not None  # PERIOD_CHIPS always contains it
    return group, buttons, date_chip


def create_picker_row(picker: OrthancDatePicker) -> QHBoxLayout:
    """The second line of the period block, holding the day/month/year selector."""
    row = QHBoxLayout()
    row.setContentsMargins(10, 6, 10, 0)
    row.setSpacing(6)
    row.addWidget(picker)
    row.addStretch(1)
    return row


def build_period_block(
    parent: QWidget,
    *,
    on_select_all: Callable[[], None],
    on_clear_selection: Callable[[], None],
) -> tuple[QVBoxLayout, dict[int, QPushButton], OrthancDatePicker, QButtonGroup, QPushButton, QPushButton]:
    """Assemble the period block the loader inserts under its search row.

    Two lines: the chips keep the toolbar row they had (with the bulk actions on
    the right), the selector sits underneath, hidden until «Дата» is chosen -
    four extra controls would push «Выбрать все» off the first line at the
    dialog's minimum width.
    """
    group, buttons, _date_chip = create_period_chips(parent)
    chips_row = QHBoxLayout()
    chips_row.setContentsMargins(10, 8, 10, 0)
    chips_row.setSpacing(6)
    chips_row.addWidget(QLabel(tr("orthanc.period_label"), parent))
    for button in buttons.values():
        chips_row.addWidget(button)
    chips_row.addStretch(1)
    select_all_btn = QPushButton(tr("orthanc.select_all"), parent)
    select_all_btn.clicked.connect(on_select_all)
    clear_selection_btn = QPushButton(tr("orthanc.clear_selection"), parent)
    clear_selection_btn.clicked.connect(on_clear_selection)
    for bulk in (select_all_btn, clear_selection_btn):
        chips_row.addWidget(bulk)
    # Built last on purpose: siblings join the focus chain in creation order, so
    # the selector lands right after the bulk actions (configure_pacs_tab_order
    # then links it to the chips) instead of between them and the row.
    picker = OrthancDatePicker(parent)
    picker.setVisible(False)
    block = QVBoxLayout()
    block.setContentsMargins(0, 0, 0, 0)
    block.setSpacing(0)
    block.addLayout(chips_row)
    block.addLayout(create_picker_row(picker))
    return block, buttons, picker, group, select_all_btn, clear_selection_btn


def build_date_picker_qss(
    *,
    bg_control: str,
    border: str,
    accent: str,
    accent_text: str,
    text_dim: str,
) -> str:
    """Dialog-scoped rules for the selector (the dialog's sheet splices them in)."""
    return f"""
            QWidget#orthancDatePicker QLabel {{
                color: {text_dim};
            }}
            QSpinBox#datePickerDay, QSpinBox#datePickerMonth, QSpinBox#datePickerYear {{
                background: {bg_control};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 2px 20px 2px 8px;
                min-height: 18px;
            }}
            QSpinBox#datePickerDay:focus, QSpinBox#datePickerMonth:focus, QSpinBox#datePickerYear:focus {{
                border-color: {accent};
            }}
            /* The picker's generic QLabel rule above carries the ancestor id,
               so it outranks a bare QLabel#id rule: repeat the ancestor. */
            QWidget#orthancDatePicker QLabel#datePickerPreview {{
                color: {accent_text};
                font-weight: bold;
                padding-left: 4px;
            }}"""


class OrthancPeriodFilter(QObject):
    """Which studies the period row lets through, and when to ask the server.

    ``changed`` fires whenever the visible set must be recomputed (a chip was
    clicked, the picker was spun); ``reload_requested`` fires when the user
    confirmed an exact day with Enter and the query must be repeated.
    """

    changed = Signal()
    reload_requested = Signal()

    def __init__(
        self,
        chips: Mapping[int, QPushButton],
        picker: OrthancDatePicker,
        group: QButtonGroup | None = None,
        parent: QObject | None = None,
        *,
        feed: _FeedFn | None = None,
        reload: Callable[[], None] | None = None,
        client: Callable[[], object] | None = None,
        now: _NowFn | None = None,
    ) -> None:
        super().__init__(parent)
        self._chips = dict(chips)
        self._picker = picker
        self._group = group
        self._feed = feed
        self._reload = reload
        self._client = client
        self._now = now or datetime.now
        if group is not None:
            group.buttonClicked.connect(lambda _button: self._on_chip_clicked())
        picker.date_changed.connect(lambda _value: self._on_picker_edited())
        picker.activated.connect(lambda _value: self._on_picker_activated())
        self.reload_requested.connect(self.reload_studies)

    # ── state ───────────────────────────────────────────────────────
    def days(self) -> int:
        """Lookback window in days; ``0`` for «Все», ``EXACT_DATE_CHIP`` for a day."""
        for days, button in self._chips.items():
            if button.isChecked():
                return days
        return 0

    def is_exact_day(self) -> bool:
        return self.days() == EXACT_DATE_CHIP

    def exact_date(self) -> date | None:
        """The chosen day — only while the «date» chip is the active one."""
        return self._picker.selected_date() if self.is_exact_day() else None

    def exact_date_value(self) -> str | None:
        """The chosen day as DICOM ``YYYYMMDD``, or ``None`` for a preset window."""
        chosen = self.exact_date()
        return chosen.strftime("%Y%m%d") if chosen is not None else None

    def feed_studies(self, studies: list[object], error: str | None = None) -> None:
        """Hand studies to the list as if the background query had returned them."""
        if self._feed is not None:
            self._feed(studies, error)

    def reload_studies(self) -> None:
        """Run the server query again (the row is re-filtered from the result)."""
        if self._reload is not None:
            self._reload()

    def query_client(self) -> object:
        """The client the loader asks (the raw DICOMweb one, not the adapter)."""
        return self._client() if self._client is not None else None

    def picker_widget(self) -> OrthancDatePicker:
        """The day/month/year selector this filter drives."""
        return self._picker

    def picker_focus_chain(self) -> list[str]:
        """Object names of the selector components in Tab order."""
        return [widget.objectName() for widget in self._picker.focus_chain()]

    def select_days(self, days: int) -> None:
        """Click the chip for ``days`` — the public way in for callers and tests."""
        self._chips[days].click()

    def select_exact_date(self, day: date) -> None:
        """Choose the «дата» chip and set the picker to ``day`` in one step.

        ``set_date`` is silent by design (it is also used to restore state), so
        the filter pass is requested here — the chip click alone filtered with
        the picker's *previous* day and could leave the wanted study hidden.
        """
        self._chips[EXACT_DATE_CHIP].click()
        self._picker.set_date(day)
        self.changed.emit()

    def set_component(self, component: str, value: int) -> None:
        """Spin one picker component in place: ``"day"``, ``"month"``, ``"year"``."""
        self._picker.component(component).setValue(value)

    def submit(self) -> None:
        """Confirm the chosen day the way Enter / «Применить» does (re-queries)."""
        self._picker.activated.emit(self._picker.selected_date())

    # ── row predicate ───────────────────────────────────────────────
    def shows(self, raw_date: object) -> bool:
        """Does a study dated ``raw_date`` (DICOM ``YYYYMMDD``) survive the period?

        An unparsable date is shown rather than hidden: the period must not make
        a study unreachable because its metadata is odd, and the row already
        reports the problem in its own way.
        """
        mode = self.days()
        exact = self.exact_date()
        if mode <= 0 and exact is None:
            return True
        try:
            study_date = datetime.strptime(str(raw_date or "")[:8], "%Y%m%d")
        except ValueError:
            return True
        if mode > 0:
            return study_date >= self._now() - timedelta(days=mode)
        return study_date.date() == exact

    # ── reactions ───────────────────────────────────────────────────
    def _on_chip_clicked(self) -> None:
        self._sync_picker_visibility()
        if self.is_exact_day():
            # The chip was chosen for the picker: put the caret where the user
            # is about to type instead of leaving it on the chip.
            self._picker.setFocus()
        self.changed.emit()

    def _on_picker_edited(self) -> None:
        if self.is_exact_day():
            self.changed.emit()

    def _on_picker_activated(self) -> None:
        if self.is_exact_day():
            self.changed.emit()
            self.reload_requested.emit()

    def _sync_picker_visibility(self) -> None:
        # The picker is only meaningful for the exact-date chip; hiding it
        # keeps the toolbar as compact as it was for the preset windows.
        self._picker.setVisible(self.is_exact_day())


__all__ = [
    "EXACT_DATE_CHIP",
    "PERIOD_CHIPS",
    "OrthancPeriodFilter",
    "build_date_picker_qss",
    "build_period_block",
    "create_period_chips",
    "create_picker_row",
]
