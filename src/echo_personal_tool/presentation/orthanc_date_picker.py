"""Day / month / year selector for the PACS study browser's period row.

The loader filters studies **client-side** (the DICOMweb/DIMSE query takes a
single ``study_date``, not a range), so the only thing a period chip does is
decide which already-loaded rows stay visible.  The preset chips (1/7/30/90
days) answer «за последнюю неделю»; a clinician chasing one specific
examination needs «покажи 12.03.2024» instead, which is a different question.

Three spin boxes beat :class:`QCalendarWidget` here on purpose:

* the rest of the dialog is a dense toolbar — a calendar popup would be a
  300×260 panel dropping out of a 26 px chip row;
* a date that is *known* is typed, not hunted for: «12», «03», «2024» is three
  keystrokes, and the arrow keys walk the components;
* the widget is testable without modal event loops.

Wheel scrolling is deliberately ignored: the selector sits directly under the
period chips and above the study list, so a scroll gesture aimed at the list
would otherwise rewind the year under the user's hand.

The locale supplies both the month names and the day/month order
(``orthanc.date_picker_month_1..12``, ``orthanc.date_picker_order``), because
«12.03.2024» and «03/12/2024» mean different days.
"""

from __future__ import annotations

import calendar
from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QWidget

from echo_personal_tool.application.localization import tr

#: Ascending order of the three components; ``DMY`` is the clinical default.
_ORDER_DMY = "DMY"
_ORDER_MDY = "MDY"


def _date_order() -> str:
    """``"DMY"`` or ``"MDY"`` from the locale, ``DMY`` for anything unknown."""
    raw = tr("orthanc.date_picker_order").strip().upper()
    return _ORDER_MDY if raw == _ORDER_MDY else _ORDER_DMY


def month_name(month: int) -> str:
    """Localised full month name (January = 1); the number if untranslated."""
    if not 1 <= month <= 12:
        return str(month)
    key = f"orthanc.date_picker_month_{month}"
    value = tr(key)
    return str(month) if value == key else value


def format_picker_date(value: date) -> str:
    """The date in the locale's component order, e.g. ``12.03.2024``."""
    if _date_order() == _ORDER_MDY:
        return f"{value.month:02d}/{value.day:02d}/{value.year}"
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


class _PaddedSpinBox(QSpinBox):
    """A spin box that always shows two digits («03», not «3»).

    The components sit next to a «12.03.2024» preview; an unpadded «3 · март»
    reads like a different field from the date it produces.
    """

    def __init__(self, parent: QWidget | None = None, *, digits: int = 2) -> None:
        super().__init__(parent)
        self._digits = digits

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        """Ignore the wheel: the study list under the row keeps the gesture.

        A spin box under the cursor would otherwise change the date while the
        user scrolls the list, and the filter would re-query on every notch.
        """
        event.ignore()

    def textFromValue(self, value: int) -> str:  # noqa: N802 - Qt override
        return str(int(value)).zfill(self._digits)

    def valueFromText(self, text: str) -> int:  # noqa: N802 - Qt override
        digits = "".join(char for char in text if char.isdigit())
        return int(digits) if digits else self.minimum()


class OrthancDatePicker(QWidget):
    """Three spin boxes (day / month / year) plus a live «12.03.2024» preview."""

    date_changed = Signal(object)  # datetime.date
    activated = Signal(object)  # datetime.date — Enter or «Применить»

    def __init__(self, parent: QWidget | None = None, *, initial: date | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("orthancDatePicker")
        today = date.today()
        start = initial or today
        # A future date hides every study, so the year range stops at today:
        # the period row lives inside the loader, where «сегодня» is the latest
        # possible examination.
        self._min_year = 1900
        self._max_year = today.year

        self._day = _PaddedSpinBox(self)
        self._day.setObjectName("datePickerDay")
        self._day.setRange(1, 31)
        self._day.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._day.setToolTip(tr("orthanc.date_picker_day_tooltip"))

        self._month = _PaddedSpinBox(self)
        self._month.setObjectName("datePickerMonth")
        self._month.setRange(1, 12)
        self._month.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._month.setToolTip(tr("orthanc.date_picker_month_tooltip"))

        self._year = _PaddedSpinBox(self, digits=4)
        self._year.setObjectName("datePickerYear")
        self._year.setRange(self._min_year, self._max_year)
        self._year.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._year.setToolTip(tr("orthanc.date_picker_year_tooltip"))

        self._preview = QLabel(self)
        self._preview.setObjectName("datePickerPreview")
        self._preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._preview.setToolTip(tr("orthanc.date_picker_preview_tooltip"))

        for spin in (self._day, self._month, self._year):
            spin.setKeyboardTracking(False)
            spin.setAccelerated(True)
            spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            spin.valueChanged.connect(self._on_component_changed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._labels: dict[str, QLabel] = {}
        for index, component in enumerate(("day", "month", "year")):
            if index:
                layout.addSpacing(8)  # a visible gap between the three groups
            label = QLabel(self)
            label.setObjectName(f"datePickerLabel{component.capitalize()}")
            self._labels[component] = label
            spin = getattr(self, f"_{component}")
            layout.addWidget(label)
            layout.addWidget(spin)
        layout.addSpacing(6)
        layout.addWidget(self._preview)

        self.reload_text()
        self.set_date(start)

    # ── text / locale ───────────────────────────────────────────────
    def reload_text(self) -> None:
        """Re-read every caption from the active locale (also after a switch)."""
        self._labels["day"].setText(tr("orthanc.date_picker_day"))
        self._labels["month"].setText(tr("orthanc.date_picker_month"))
        self._labels["year"].setText(tr("orthanc.date_picker_year"))
        self._update_month_suffix()
        self._fit_widths()
        self._refresh_preview()

    def _fit_widths(self) -> None:
        """Widen the components to their widest *content*, not their widest value.

        A month spin box carries a suffix («11 · ноябрь»), so the default
        ``sizeHint`` — computed from the two-digit range — clipped it and the
        month name overlapped the arrows.  The width is taken from the longest
        localised month name so the row does not jump when the month changes.
        """
        metrics = self._day.fontMetrics()
        longest_month = max((month_name(index) for index in range(1, 13)), key=len, default="")
        self._day.setFixedWidth(metrics.horizontalAdvance("00") + 34)
        self._month.setFixedWidth(metrics.horizontalAdvance(f"00 · {longest_month}") + 34)
        self._year.setFixedWidth(metrics.horizontalAdvance("0000") + 34)

    def _update_month_suffix(self) -> None:
        """Speak the month in words next to the number («03 — март»)."""
        self._month.setSuffix(f" · {month_name(self._month.value())}")

    # ── state ───────────────────────────────────────────────────────
    def preview_text(self) -> str:
        """The «12.03.2024» caption the picker shows next to the components."""
        return self._preview.text()

    def label_text(self, name: str) -> str:
        """Caption above one component (``"day"``, ``"month"``, ``"year"``)."""
        return self._labels[name].text()

    def component(self, name: str) -> QSpinBox:
        """The spin box for ``"day"``, ``"month"`` or ``"year"`` (locale order is separate)."""
        return {"day": self._day, "month": self._month, "year": self._year}[name]

    def selected_date(self) -> date:
        """The selected date, clamped to the last day of the chosen month."""
        year = max(self._min_year, min(self._year.value(), self._max_year))
        month = max(1, min(self._month.value(), 12))
        last_day = calendar.monthrange(year, month)[1]
        day = max(1, min(self._day.value(), last_day))
        return date(year, month, day)

    def set_date(self, value: date) -> None:
        """Show ``value`` without emitting :attr:`date_changed` twice."""
        blocked = [spin.blockSignals(True) for spin in (self._day, self._month, self._year)]
        try:
            self._year.setValue(max(self._min_year, min(value.year, self._max_year)))
            self._month.setValue(max(1, min(value.month, 12)))
            self._day.setMaximum(calendar.monthrange(self._year.value(), self._month.value())[1])
            self._day.setValue(max(1, min(value.day, self._day.maximum())))
            self._update_month_suffix()
        finally:
            for spin, was_blocked in zip((self._day, self._month, self._year), blocked):
                spin.blockSignals(was_blocked)
        self._refresh_preview()

    def _on_component_changed(self, _value: int) -> None:
        # February 30 does not exist: shrink the day range *before* the value
        # is read back, otherwise the picker would report a date it cannot show.
        year = max(self._min_year, min(self._year.value(), self._max_year))
        month = max(1, min(self._month.value(), 12))
        last_day = calendar.monthrange(year, month)[1]
        day_was_blocked = self._day.blockSignals(True)
        self._day.setMaximum(last_day)
        self._day.blockSignals(day_was_blocked)
        if self._month.value() != month:
            month_was_blocked = self._month.blockSignals(True)
            self._month.setValue(month)
            self._month.blockSignals(month_was_blocked)
        self._update_month_suffix()
        self._refresh_preview()
        self.date_changed.emit(self.selected_date())

    def _refresh_preview(self) -> None:
        self._preview.setText(format_picker_date(self.selected_date()))

    # ── keyboard ────────────────────────────────────────────────────
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.emit(self.selected_date())
            event.accept()
            return
        super().keyPressEvent(event)

    def focus_chain(self) -> tuple[QWidget, QWidget, QWidget]:
        """Components in visual (locale) order, for the dialog's Tab chain."""
        if _date_order() == _ORDER_MDY:
            return (self._month, self._day, self._year)
        return (self._day, self._month, self._year)


def qdate_to_date(value: QDate) -> date:
    """Small helper kept for callers that start from a ``QDate``."""
    return date(value.year(), value.month(), value.day())


__all__ = [
    "OrthancDatePicker",
    "format_picker_date",
    "month_name",
    "qdate_to_date",
]
