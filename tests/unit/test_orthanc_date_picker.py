"""Tests for the PACS loader's arbitrary-date picker (item «произвольная дата»).

Two layers:

* :class:`TestOrthancDatePicker` — the widget on its own: month lengths, the
  locale day/month order, the padded text and the wheel guard.
* :class:`TestDialogDateFilter` — the wiring inside
  :class:`OrthancStudyDialog`: the «Дата» chip reveals the picker, an exact day
  hides every other row, and the day travels to the server query.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QDate, QPoint, Qt, QTimer
from PySide6.QtGui import QWheelEvent

from echo_personal_tool.domain.models.orthanc import StudyInfo
from echo_personal_tool.infrastructure.i18n import set_language
from echo_personal_tool.presentation import orthanc_study_dialog as orthanc_dialog
from echo_personal_tool.presentation.orthanc_date_picker import (
    OrthancDatePicker,
    format_picker_date,
    month_name,
    qdate_to_date,
)

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ── the widget ──────────────────────────────────────────────────────


class TestOrthancDatePicker:
    def test_starts_on_the_given_day(self):
        picker = OrthancDatePicker(initial=date(2024, 3, 12))
        assert picker.date() == date(2024, 3, 12)
        assert picker._preview.text() == "12.03.2024"

    def test_month_names_are_localised(self):
        set_language("ru")
        assert month_name(1) == "январь"
        assert month_name(12) == "декабрь"
        set_language("en")
        assert month_name(3) == "March"

    def test_unknown_month_name_falls_back_to_the_number(self):
        assert month_name(0) == "0"
        assert month_name(13) == "13"

    def test_day_month_order_follows_the_locale(self):
        """«12.03.2024» and «03/12/2024» are different days: the locale decides."""
        set_language("ru")
        assert format_picker_date(date(2024, 3, 12)) == "12.03.2024"
        set_language("en")
        assert format_picker_date(date(2024, 3, 12)) == "03/12/2024"

    def test_components_are_padded(self):
        picker = OrthancDatePicker(initial=date(2024, 9, 3))
        assert picker._day.text() == "03"
        assert picker._month.text().startswith("09")
        assert picker._year.text() == "2024"

    def test_day_range_shrinks_for_short_months(self):
        picker = OrthancDatePicker(initial=date(2024, 1, 31))
        assert picker._day.maximum() == 31
        picker._month.setValue(2)  # 2024 is a leap year
        assert picker._day.maximum() == 29
        assert picker.date() == date(2024, 2, 29)
        picker._year.setValue(2023)
        assert picker._day.maximum() == 28
        assert picker.date() == date(2023, 2, 28)

    def test_every_month_of_a_leap_year_round_trips(self):
        picker = OrthancDatePicker()
        for month in range(1, 13):
            for day in (1, calendar.monthrange(2024, month)[1]):
                picker.set_date(date(2024, month, day))
                assert picker.date() == date(2024, month, day)

    def test_year_is_bounded_by_today(self):
        """A future examination cannot exist, so the year stops at this one."""
        picker = OrthancDatePicker()
        assert picker._year.maximum() == date.today().year
        picker.set_date(date(2999, 5, 5))
        assert picker.date().year == date.today().year

    def test_set_date_does_not_emit(self):
        picker = OrthancDatePicker(initial=date(2024, 1, 1))
        seen: list[date] = []
        picker.date_changed.connect(seen.append)
        picker.set_date(date(2024, 6, 15))
        assert seen == []
        assert picker.date() == date(2024, 6, 15)

    def test_spinning_emits_the_new_date(self):
        picker = OrthancDatePicker(initial=date(2024, 1, 1))
        seen: list[date] = []
        picker.date_changed.connect(seen.append)
        picker._month.setValue(4)
        assert seen == [date(2024, 4, 1)]

    def test_enter_activates(self):
        from PySide6.QtGui import QKeyEvent

        picker = OrthancDatePicker(initial=date(2024, 3, 12))
        seen: list[date] = []
        picker.activated.connect(seen.append)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        picker.keyPressEvent(event)
        assert seen == [date(2024, 3, 12)]

    def test_wheel_is_ignored(self):
        """The study list under the toolbar keeps the scroll gesture."""
        picker = OrthancDatePicker(initial=date(2024, 3, 12))
        event = QWheelEvent(
            QPoint(5, 5),
            picker.mapToGlobal(QPoint(5, 5)),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        picker._day.wheelEvent(event)
        assert not event.isAccepted()
        assert picker.date() == date(2024, 3, 12)

    def test_focus_chain_follows_the_locale(self):
        set_language("ru")
        ru = OrthancDatePicker()
        assert [w.objectName() for w in ru.focus_chain()] == [
            "datePickerDay",
            "datePickerMonth",
            "datePickerYear",
        ]
        set_language("en")
        en = OrthancDatePicker()
        assert [w.objectName() for w in en.focus_chain()] == [
            "datePickerMonth",
            "datePickerDay",
            "datePickerYear",
        ]

    def test_reload_text_switches_every_caption(self):
        picker = OrthancDatePicker()
        set_language("ru")
        picker.reload_text()
        assert picker._labels["day"].text() == "День"
        assert "ноябрь" in picker._month.suffix() or "·" in picker._month.suffix()
        set_language("en")
        picker.reload_text()
        assert picker._labels["day"].text() == "Day"

    def test_month_width_fits_the_longest_month_name(self):
        """The suffix is part of the box: a clipped «сентябрь» looked like a bug."""
        set_language("ru")
        picker = OrthancDatePicker()
        metrics = picker._month.fontMetrics()
        longest = max(month_name(index) for index in range(1, 13))
        assert picker._month.minimumWidth() >= metrics.horizontalAdvance(f"00 · {longest}")

    def test_qdate_helper(self):
        assert qdate_to_date(QDate(2024, 3, 12)) == date(2024, 3, 12)


# ── dialog wiring ───────────────────────────────────────────────────


def _study(uid: str, day: str) -> StudyInfo:
    return StudyInfo(
        study_uid=uid,
        patient_name="IVANOV^IVAN",
        patient_id="1",
        study_date=day,
        study_description="Echo",
        series_count=1,
        modalities_in_study="US",
        instances_count=10,
    )


@pytest.fixture()
def dialog():
    from PySide6.QtWidgets import QApplication

    from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog

    QApplication.instance() or QApplication([])
    client = MagicMock()
    client.ping.return_value = True
    client.query_studies.return_value = []
    cache = MagicMock()
    cache.create_session.return_value = "session"
    cache.session_path.return_value = MagicMock(exists=MagicMock(return_value=True))
    set_language("ru")
    with patch.object(OrthancStudyDialog, "_init_network"), patch.object(QTimer, "singleShot"):
        dlg = OrthancStudyDialog(client, cache)
    dlg._force_close_timer.stop()
    yield dlg
    dlg.blockSignals(True)
    for child in dlg.findChildren(QTimer):
        child.stop()
        child.blockSignals(True)


def _calendar_days_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


class TestDialogDateFilter:
    def test_picker_is_hidden_until_the_date_chip(self, dialog):
        assert not dialog._date_picker.isVisible()
        dialog.show()
        dialog._period_buttons[-1].click()
        assert dialog._date_picker.isVisible()
        assert dialog._date_filter_days() == -1
        dialog._period_buttons[0].click()
        assert not dialog._date_picker.isVisible()

    def test_exact_day_keeps_only_that_day(self, dialog):
        dialog._on_studies_loaded(
            [
                _study("a", "20240312"),
                _study("b", "20240313"),
                _study("c", "20240301"),
            ],
            None,
        )
        dialog._date_picker.set_date(date(2024, 3, 12))
        dialog._period_buttons[-1].click()
        hidden = {
            dialog._studies_list.topLevelItem(i).data(
                0, Qt.ItemDataRole.UserRole + 6
            ): dialog._studies_list.topLevelItem(i).isHidden()
            for i in range(dialog._studies_list.topLevelItemCount())
        }
        assert hidden == {"a": False, "b": True, "c": True}

    def test_spinning_the_picker_refilters_without_a_query(self, dialog):
        dialog._on_studies_loaded([_study("a", "20240312")], None)
        dialog._period_buttons[-1].click()
        dialog._date_picker.set_date(date(2024, 3, 1))
        with patch.object(dialog, "_load_studies_async") as reloaded:
            dialog._date_picker._day.setValue(12)
        assert not reloaded.called
        assert not dialog._studies_list.topLevelItem(0).isHidden()

    def test_enter_repeats_the_server_query(self, dialog):
        """The wanted day may simply not be among the loaded rows."""
        dialog._period_buttons[-1].click()
        dialog._date_picker.set_date(date(2024, 3, 12))
        with patch.object(dialog, "_load_studies_async") as reloaded:
            dialog._date_picker.activated.emit(date(2024, 3, 12))
        assert reloaded.called

    def _query_kwargs(self, dialog) -> dict:
        """Run the real query callable and report what it asked the server for.

        The query body is captured, not executed: ``QThreadPool`` is a stub, so
        nothing runs in a thread, and the arguments stay exactly the ones the
        dialog built.
        """
        captured: dict = {}
        real_worker = orthanc_dialog._StudyQueryWorker

        def _factory(query_fn, signals):
            captured["query_fn"] = query_fn
            return real_worker(query_fn, signals)

        with (
            patch.object(dialog, "_is_alive", return_value=True),
            patch.object(dialog, "_query_source_available", return_value=True),
            patch.object(orthanc_dialog, "_StudyQueryWorker", side_effect=_factory),
            patch.object(orthanc_dialog.QThreadPool, "globalInstance") as pool,
        ):
            pool.return_value = MagicMock()
            dialog._load_studies_async()
        query_fn = captured["query_fn"]
        with patch.object(dialog._client, "query_studies", return_value=[]) as client_query:
            query_fn()
        _args, kwargs = client_query.call_args
        return kwargs

    def test_the_chosen_day_is_sent_to_the_server(self, dialog):
        """The wanted examination may not be among the already-loaded rows."""
        dialog._period_buttons[-1].click()
        dialog._date_picker.set_date(date(2024, 3, 12))
        assert self._query_kwargs(dialog)["study_date"] == "20240312"

    def test_preset_chips_do_not_send_a_date(self, dialog):
        dialog._period_buttons[7].click()
        assert self._query_kwargs(dialog)["study_date"] is None

    def test_the_query_goes_through_the_query_service_when_there_is_one(self, dialog):
        """The adapter path must carry the day too, not just the raw client."""
        service = MagicMock()
        service.query_studies.return_value = []
        dialog._query_service = service
        dialog._period_buttons[-1].click()
        dialog._date_picker.set_date(date(2024, 3, 12))
        captured: dict = {}
        real_worker = orthanc_dialog._StudyQueryWorker

        def _factory(query_fn, signals):
            captured["query_fn"] = query_fn
            return real_worker(query_fn, signals)

        with (
            patch.object(dialog, "_is_alive", return_value=True),
            patch.object(dialog, "_query_source_available", return_value=True),
            patch.object(orthanc_dialog, "_StudyQueryWorker", side_effect=_factory),
            patch.object(orthanc_dialog.QThreadPool, "globalInstance") as pool,
        ):
            pool.return_value = MagicMock()
            dialog._load_studies_async()
        captured["query_fn"]()
        _args, kwargs = service.query_studies.call_args
        assert kwargs["study_date"] == "20240312"

    def test_lookback_still_works_after_using_the_picker(self, dialog):
        """Switching back to a preset must not leave the exact day in force."""
        dialog._on_studies_loaded([_study("old", _calendar_days_ago(100))], None)
        dialog._period_buttons[-1].click()
        dialog._date_picker.set_date(date(2000, 1, 1))
        assert dialog._studies_list.topLevelItem(0).isHidden()
        dialog._period_buttons[30].click()
        assert dialog._studies_list.topLevelItem(0).isHidden()  # 100 days > 30
        dialog._period_buttons[0].click()
        assert not dialog._studies_list.topLevelItem(0).isHidden()

    def test_rebuilt_rows_respect_the_active_period(self, dialog):
        """A new query rebuilds every row — the period must survive that."""
        dialog.show()
        dialog._period_buttons[-1].click()
        dialog._date_picker.set_date(date(2024, 3, 12))
        dialog._on_studies_loaded([_study("a", "20240312"), _study("b", "20240101")], None)
        hidden = [
            dialog._studies_list.topLevelItem(i).isHidden() for i in range(dialog._studies_list.topLevelItemCount())
        ]
        assert hidden.count(True) == 1

    def test_picker_is_in_the_tab_chain(self, dialog):
        chain = [w.objectName() for w in dialog._date_picker.focus_chain()]
        assert chain == ["datePickerDay", "datePickerMonth", "datePickerYear"]
        # The chip row is wired first, the picker right after it.
        from echo_personal_tool.presentation.orthanc_study_delegate import configure_pacs_tab_order

        configure_pacs_tab_order(dialog)  # must not raise
