"""Unit tests for presentation/ge_labeled_slider.py."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestTopLabeledSliderConstruction:
    def test_creates_with_label(self):
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        w = TopLabeledSlider("Volume")
        assert w._title.text() == "Volume"
        assert w.value() == 50

    def test_custom_range(self):
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        w = TopLabeledSlider("Gain", minimum=0, maximum=200, value=100)
        assert w.value() == 100
        assert w.slider().minimum() == 0
        assert w.slider().maximum() == 200


class TestTopLabeledSliderValue:
    def test_set_value(self):
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        w = TopLabeledSlider("X")
        w.setValue(75)
        assert w.value() == 75

    def test_signal_emitted(self):
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        w = TopLabeledSlider("X")
        received = []
        w.valueChanged.connect(lambda v: received.append(v))
        w.setValue(42)
        assert received == [42]


class TestTopLabeledSliderRange:
    def test_set_range(self):
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        w = TopLabeledSlider("X")
        w.setRange(10, 200)
        assert w.slider().minimum() == 10
        assert w.slider().maximum() == 200


class TestTopLabeledSliderEnabled:
    def test_set_disabled(self):
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        w = TopLabeledSlider("X")
        w.setEnabled(False)
        assert not w.isEnabled()
        assert not w._title.isEnabled()
        assert not w._slider.isEnabled()


class TestGeLabeledSliderConstruction:
    def test_creates_with_label(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("Depth")
        assert w.value() == 50
        assert w._decrement is not None
        assert w._increment is not None

    def test_custom_range(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("Gain", minimum=0, maximum=100, value=25)
        assert w.value() == 25


class TestGeLabeledSliderValue:
    def test_set_value(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("X")
        w.setValue(80)
        assert w.value() == 80

    def test_signal_emitted(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("X")
        received = []
        w.valueChanged.connect(lambda v: received.append(v))
        w.setValue(30)
        assert received == [30]


class TestGeLabeledSliderIncrementDecrement:
    def test_increment(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("X", value=50)
        w._increment.click()
        assert w.value() == 51

    def test_decrement(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("X", value=50)
        w._decrement.click()
        assert w.value() == 49


class TestGeLabeledSliderRange:
    def test_set_range(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("X")
        w.setRange(5, 95)
        assert w.slider().minimum() == 5
        assert w.slider().maximum() == 95


class TestGeLabeledSliderEnabled:
    def test_set_disabled(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("X")
        w.setEnabled(False)
        assert not w.isEnabled()
        assert not w._slider.isEnabled()
        assert not w._decrement.isEnabled()
        assert not w._increment.isEnabled()


class TestSliderTrackPaint:
    def test_track_widget_creation(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("X")
        assert w._track is not None
        # Force paint event by calling update
        w._track.update()


class TestGeLabeledSliderResize:
    def test_resize_updates_slider_geometry(self):
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        w = GeLabeledSlider("X")
        # Simulate resize event
        from PySide6.QtGui import QResizeEvent
        from PySide6.QtCore import QSize

        event = QResizeEvent(QSize(300, 40), QSize(200, 28))
        w.resizeEvent(event)
        # Slider geometry should be updated
        assert w._slider.geometry().width() > 0
