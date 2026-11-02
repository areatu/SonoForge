"""Wheel scrolling must not edit the control that happens to be hovered.

Closed combo boxes opt out through the Qt style hint, so no Python event filter
is involved.  Numeric fields use a *widget-local* filter installed by their own
panel.  Application-wide Python event filters are deliberately avoided: with
QtWebEngine they can force Shiboken to wrap internal no-RTTI compositor objects
and crash before the filter body runs (Debian core dumps, 2026-10-27/29).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractSpinBox, QProxyStyle, QStyle, QWidget


class ScrollSafeStyle(QProxyStyle):
    """Fusion metrics with closed-combo wheel selection disabled."""

    def styleHint(self, hint, option=None, widget=None, return_data=None):  # noqa: N802
        if hint == QStyle.StyleHint.SH_ComboBox_AllowWheelScrolling:
            return 0
        return super().styleHint(hint, option, widget, return_data)


class SpinBoxWheelGuard(QObject):
    """Ignore wheel notches on an unfocused numeric field.

    The filter is parented to the field and installed only on that field.  It
    never observes QApplication traffic, and therefore never sees QtWebEngine's
    internal render-widget delegates.
    """

    def __init__(self, field: QAbstractSpinBox) -> None:
        super().__init__(field)
        self._field = field
        field.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self._field and event.type() == QEvent.Type.Wheel and not self._field.hasFocus():
            assert isinstance(event, QWheelEvent)
            event.ignore()
            return True
        return super().eventFilter(obj, event)


def protect_spinbox(field: QAbstractSpinBox) -> SpinBoxWheelGuard:
    """Install the local wheel guard once and keep the existing API ergonomic."""
    existing = getattr(field, "_sonoforge_wheel_guard", None)
    if isinstance(existing, SpinBoxWheelGuard):
        return existing
    guard = SpinBoxWheelGuard(field)
    field._sonoforge_wheel_guard = guard
    return guard


def protect_spinboxes(root: QWidget) -> None:
    """Guard the numeric fields of one panel/dialog, never the application."""
    for field in root.findChildren(QAbstractSpinBox):
        protect_spinbox(field)
