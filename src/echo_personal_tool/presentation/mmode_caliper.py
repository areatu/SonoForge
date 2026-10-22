from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from echo_personal_tool.domain.models.mmode import MModeCaliperMeasurement


class MModeCaliperTool(QWidget):
    measurement_added = Signal(object)

    def __init__(
        self,
        depth_mm_per_pixel: float | None = None,
        time_ms_per_pixel: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._depth_mm_per_pixel = depth_mm_per_pixel
        self._time_ms_per_pixel = time_ms_per_pixel
        self._active_mode: str | None = None
        self._first_click: tuple[float, float] | None = None
        self.measurements: list[MModeCaliperMeasurement] = []

    def start_distance_caliper(self) -> None:
        self._active_mode = "distance"
        self._first_click = None

    def start_time_caliper(self) -> None:
        self._active_mode = "time"
        self._first_click = None

    def on_click(self, x: float, y: float) -> None:
        if self._active_mode is None:
            return
        if self._first_click is None:
            self._first_click = (x, y)
            return
        cal = MModeCaliperMeasurement(
            kind=self._active_mode,
            start=self._first_click,
            end=(x, y),
        )
        if cal.kind == "distance" and self._depth_mm_per_pixel is not None:
            dist_px = abs(y - self._first_click[1])
            cal = MModeCaliperMeasurement(
                kind="distance",
                start=self._first_click,
                end=(x, y),
                value_mm=dist_px * self._depth_mm_per_pixel,
            )
        elif cal.kind == "time" and self._time_ms_per_pixel is not None:
            time_px = abs(x - self._first_click[0])
            cal = MModeCaliperMeasurement(
                kind="time",
                start=self._first_click,
                end=(x, y),
                value_ms=time_px * self._time_ms_per_pixel,
            )
        self.measurements.append(cal)
        self._first_click = None
        self._active_mode = None
        self.measurement_added.emit(cal)

    def clear(self) -> None:
        self.measurements.clear()
        self._first_click = None
        self._active_mode = None
