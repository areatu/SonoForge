"""Explicit repeat selection for spectral Doppler (issue 559).

The viewer keeps every beat of one parameter; this dialog is the one place
where the operator marks a bad or extrasystolic beat as excluded.  The same
:class:`~echo_personal_tool.domain.services.doppler_repeats.RepeatStatistics`
object is used here and by the report, so the accepted rows, ``n``, mean, SD
and CV cannot disagree between the two.

The dialog offers no automatic atrial-fibrillation rule: the operator chooses
the beats and the documented method stays "mean of the last three accepted
beats".  That is deliberate — a universal rule for irregular rhythm would be a
clinical claim the measurement itself cannot support.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Protocol, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.doppler_catalog import (
    canonical_interval_label,
    canonical_peak_label,
    canonical_trace_label,
)
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.services.doppler_repeats import (
    REPORT_WINDOW,
    RepeatStatistics,
    repeat_statistics,
)
from echo_personal_tool.presentation import dark_theme

if TYPE_CHECKING:
    from collections.abc import Callable

    class _ViewerDoppler(Protocol):
        def get_measurement_dto(self) -> DopplerMeasurementDTO: ...

        def load_measurement_dto(self, dto: DopplerMeasurementDTO) -> None: ...

    class _Viewer(Protocol):
        doppler: _ViewerDoppler

    class _Controller(Protocol):
        def on_doppler_markers_changed(self, dto: DopplerMeasurementDTO) -> None: ...

    class _Host(Protocol):
        _viewer: _Viewer
        _controller: _Controller


_Marker = DopplerPeakMarker | DopplerIntervalMarker | DopplerTrace

_KIND_PEAK = "peak"
_KIND_INTERVAL = "interval"
_KIND_TRACE = "trace"

_ROLE_ROW = Qt.ItemDataRole.UserRole


def _number(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _trace_vti_cm(trace: DopplerTrace) -> float:
    from echo_personal_tool.domain.calculations.doppler_metrics import trace_vti_cm

    return trace_vti_cm(trace)


class DopplerRepeatsDialog(QDialog):
    """Accepted/excluded beats with their shared n, mean, SD and CV."""

    def __init__(
        self,
        *,
        dto: DopplerMeasurementDTO,
        apply_dto: Callable[[DopplerMeasurementDTO], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dto = dto
        self._apply_dto = apply_dto
        self._checks: dict[tuple[str, int], QTreeWidgetItem] = {}
        self._group_values: dict[tuple[str, str], tuple[float, ...]] = {}
        self._group_parents: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._updating = False
        self.setObjectName("dopplerRepeatsDialog")
        self.setWindowTitle(tr("doppler_repeats.title"))
        self.setModal(True)
        self.resize(680, 480)

        self._method = QLabel(tr("doppler_repeats.method", window=REPORT_WINDOW), self)
        self._method.setObjectName("dopplerRepeatsMethod")
        self._method.setWordWrap(True)

        self._tree = QTreeWidget(self)
        self._tree.setObjectName("dopplerRepeatsTree")
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(
            [
                tr("doppler_repeats.column_parameter"),
                tr("doppler_repeats.column_value"),
                tr("doppler_repeats.column_stats"),
            ]
        )
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)

        self._empty = QLabel(tr("doppler_repeats.empty"), self)
        self._empty.setObjectName("dopplerRepeatsEmpty")
        self._empty.setWordWrap(True)

        self._apply = QPushButton(tr("doppler_repeats.apply"), self)
        self._apply.setObjectName("dopplerRepeatsApply")
        self._apply.clicked.connect(self.apply_selection)
        self._close = QPushButton(tr("button.close"), self)
        self._close.setObjectName("dopplerRepeatsClose")
        self._close.clicked.connect(self.reject)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self._method, 1)
        actions.addWidget(self._apply)
        actions.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._tree, 1)
        layout.addWidget(self._empty)
        layout.addLayout(actions)

        self._build_rows()
        self._tree.itemChanged.connect(self._on_item_changed)
        self._apply.setEnabled(bool(self._checks))

    @property
    def rows(self) -> int:
        """Number of checked repeat rows, exposed for tests."""
        return len(self._checks)

    def statistics(self) -> tuple[RepeatStatistics, ...]:
        """Statistics of the current selection in tree order."""
        result: list[RepeatStatistics] = []
        for key, values in self._group_values.items():
            result.append(repeat_statistics(values, self._group_flags(key)))
        return tuple(result)

    def _group_flags(self, key: tuple[str, str]) -> list[bool]:
        parent = self._group_parents[key]
        flags: list[bool] = []
        for index in range(parent.childCount()):
            child = parent.child(index)
            flags.append(child is not None and child.checkState(0) == Qt.CheckState.Checked)
        return flags

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0 or item.childCount():
            return
        parent = item.parent()
        if parent is None:
            return
        key = parent.data(0, _ROLE_ROW)
        if not isinstance(key, tuple) or len(key) != 2:
            return
        self._updating = True
        try:
            parent.setText(2, self._stats_text(repeat_statistics(self._group_values[key], self._group_flags(key))))
            self._paint_row(item, item.checkState(0) == Qt.CheckState.Checked)
        finally:
            self._updating = False

    def _paint_row(self, item: QTreeWidgetItem, accepted: bool) -> None:
        item.setText(2, tr("doppler_repeats.accepted") if accepted else tr("doppler_repeats.excluded"))
        if accepted:
            for column in range(3):
                item.setData(column, Qt.ItemDataRole.ForegroundRole, None)
        else:
            disabled = QBrush(QColor(dark_theme.get_theme_tokens()["text.disabled"]))
            for column in range(3):
                item.setForeground(column, disabled)

    def _build_rows(self) -> None:
        self._tree.clear()
        self._checks.clear()
        self._group_values.clear()
        self._group_parents.clear()
        disabled = QBrush(QColor(dark_theme.get_theme_tokens()["text.disabled"]))
        groups: list[tuple[str, str, tuple[tuple[int, _Marker], ...], list[float], list[bool]]] = []

        peaks: dict[str, list[tuple[int, DopplerPeakMarker]]] = {}
        for position, peak_marker in enumerate(self._dto.peaks):
            peaks.setdefault(canonical_peak_label(peak_marker.label), []).append((position, peak_marker))
        for peak_label, peak_entries in peaks.items():
            groups.append(
                (
                    _KIND_PEAK,
                    peak_label,
                    tuple(peak_entries),
                    [abs(float(marker.velocity_cm_s)) for _, marker in peak_entries],
                    [marker.accepted for _, marker in peak_entries],
                )
            )

        intervals: dict[str, list[tuple[int, DopplerIntervalMarker]]] = {}
        for position, interval_marker in enumerate(self._dto.intervals):
            intervals.setdefault(canonical_interval_label(interval_marker.label), []).append(
                (position, interval_marker)
            )
        for interval_label, interval_entries in intervals.items():
            groups.append(
                (
                    _KIND_INTERVAL,
                    interval_label,
                    tuple(interval_entries),
                    [abs(float(marker.end_time_ms - marker.start_time_ms)) for _, marker in interval_entries],
                    [marker.accepted for _, marker in interval_entries],
                )
            )

        traces: dict[str, list[tuple[int, DopplerTrace]]] = {}
        for position, trace in enumerate(self._dto.traces):
            if len(trace.points) < 2:
                continue
            traces.setdefault(canonical_trace_label(trace.label), []).append((position, trace))
        for trace_label, trace_entries in traces.items():
            groups.append(
                (
                    _KIND_TRACE,
                    trace_label,
                    tuple(trace_entries),
                    [_trace_vti_cm(trace) for _, trace in trace_entries],
                    [trace.accepted for _, trace in trace_entries],
                )
            )

        for kind, label, entries, values, flags in groups:
            stats = repeat_statistics(values, flags)
            key = (kind, label)
            self._group_values[key] = tuple(values)
            parent = QTreeWidgetItem([label, "", self._stats_text(stats)])
            parent.setData(0, _ROLE_ROW, key)
            self._group_parents[key] = parent
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(parent)
            for offset, ((source_index, marker), value) in enumerate(zip(entries, values), start=1):
                item = QTreeWidgetItem(
                    [
                        tr("doppler_repeats.row", number=offset),
                        self._value_text(kind, value),
                        tr("doppler_repeats.accepted") if marker.accepted else tr("doppler_repeats.excluded"),
                    ]
                )
                item.setData(0, _ROLE_ROW, (kind, source_index))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if marker.accepted else Qt.CheckState.Unchecked)
                if not marker.accepted:
                    for column in range(3):
                        item.setForeground(column, disabled)
                parent.addChild(item)
                self._checks[(kind, source_index)] = item
            parent.setExpanded(True)
        self._empty.setVisible(not self._checks)
        self._tree.setVisible(bool(self._checks))

    def _stats_text(self, stats: RepeatStatistics) -> str:
        return tr(
            "doppler_repeats.group_stats",
            accepted=stats.accepted_count,
            excluded=stats.excluded_count,
            n=stats.n,
            mean=_number(stats.mean),
            sd=_number(stats.sd),
            cv=_number(stats.cv_percent, 1),
        )

    def _value_text(self, kind: str, value: float) -> str:
        if kind == _KIND_INTERVAL:
            return tr("doppler_repeats.value_ms", value=f"{value:.0f}")
        if kind == _KIND_TRACE:
            return tr("doppler_repeats.value_vti", value=f"{value:.2f}")
        return tr("doppler_repeats.value_velocity", value=f"{value:.2f}")

    def selected_dto(self) -> DopplerMeasurementDTO:
        """The same markers with the current checked state."""

        def checked(kind: str, index: int, default: bool) -> bool:
            item = self._checks.get((kind, index))
            return default if item is None else item.checkState(0) == Qt.CheckState.Checked

        return replace(
            self._dto,
            peaks=tuple(
                replace(marker, accepted=checked(_KIND_PEAK, index, marker.accepted))
                for index, marker in enumerate(self._dto.peaks)
            ),
            intervals=tuple(
                replace(marker, accepted=checked(_KIND_INTERVAL, index, marker.accepted))
                for index, marker in enumerate(self._dto.intervals)
            ),
            traces=tuple(
                replace(trace, accepted=checked(_KIND_TRACE, index, trace.accepted))
                for index, trace in enumerate(self._dto.traces)
            ),
        )

    def apply_selection(self) -> None:
        self._apply_dto(self.selected_dto())
        self.accept()


def show_doppler_repeats(window: object) -> None:
    """Open repeat selection for the current Doppler frame."""
    host = cast("_Host", window)
    dto = host._viewer.doppler.get_measurement_dto()
    if not dto.peaks and not dto.intervals and not dto.traces:
        QMessageBox.information(cast(QWidget, window), tr("doppler_repeats.title"), tr("doppler_repeats.empty_frame"))
        return

    def apply(updated: DopplerMeasurementDTO) -> None:
        host._viewer.doppler.load_measurement_dto(updated)
        host._controller.on_doppler_markers_changed(updated)

    dialog = DopplerRepeatsDialog(dto=dto, apply_dto=apply, parent=cast(QWidget, window))
    dialog.exec()
