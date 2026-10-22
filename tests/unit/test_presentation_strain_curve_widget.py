"""Unit tests for presentation/strain_curve_widget.py."""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def widget():
    from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

    return StrainCurveWidget()


class TestStrainCurveWidgetConstruction:
    def test_creates_with_plot(self, widget):
        assert widget._plot is not None
        assert widget._gls_label is not None
        assert widget._longitudinal_curve is not None
        assert widget._radial_curve is not None
        assert widget._zero_line is not None
        assert widget._ed_line is None
        assert widget._es_line is None

    def test_initial_gls_text(self, widget):
        assert widget._gls_label.text() == "GLS: --"


class TestSetStrainData:
    def test_empty_data_clears(self, widget):
        widget.set_strain_data(np.array([]), np.array([]))
        # Should call clear internally
        assert widget._gls_label.text() == "GLS: --"

    def test_valid_data_sets_curves(self, widget):
        long = np.array([0.0, -5.0, -10.0, -8.0])
        radial = np.array([0.0, 3.0, 6.0, 4.0])
        widget.set_strain_data(long, radial, ed_index=0, es_index=2)
        assert widget._ed_line is not None
        assert widget._es_line is not None

    def test_window_filtering(self, widget):
        long = np.array([0.0, -5.0, -10.0, -8.0, -3.0])
        radial = np.array([0.0, 3.0, 6.0, 4.0, 1.0])
        widget.set_strain_data(long, radial, ed_index=1, es_index=3, window_start=1, window_end=3)
        assert widget._ed_line is not None
        assert widget._es_line is not None

    def test_replaces_old_ed_es_lines(self, widget):
        long = np.array([0.0, -5.0, -10.0])
        radial = np.array([0.0, 3.0, 6.0])
        widget.set_strain_data(long, radial, ed_index=0, es_index=2)
        first_ed = widget._ed_line
        widget.set_strain_data(long, radial, ed_index=1, es_index=1)
        assert widget._ed_line is not first_ed


class TestSetGlsValue:
    def test_sets_formatted_value(self, widget):
        widget.set_gls_value(-18.5)
        assert widget._gls_label.text() == "GLS: -18.5%"

    def test_zero_gls(self, widget):
        widget.set_gls_value(0.0)
        assert widget._gls_label.text() == "GLS: 0.0%"

    def test_positive_gls(self, widget):
        widget.set_gls_value(5.2)
        assert widget._gls_label.text() == "GLS: 5.2%"


class TestClear:
    def test_clears_curves_and_labels(self, widget):
        long = np.array([0.0, -5.0, -10.0])
        radial = np.array([0.0, 3.0, 6.0])
        widget.set_strain_data(long, radial, ed_index=0, es_index=2)
        widget.set_gls_value(-15.0)

        widget.clear()

        assert widget._gls_label.text() == "GLS: --"
        assert widget._ed_line is None
        assert widget._es_line is None

    def test_clear_when_nothing_set(self, widget):
        widget.clear()
        assert widget._gls_label.text() == "GLS: --"
        assert widget._ed_line is None
        assert widget._es_line is None

    def test_clear_only_ed_line(self, widget):
        long = np.array([0.0, -5.0, -10.0])
        radial = np.array([0.0, 3.0, 6.0])
        widget.set_strain_data(long, radial, ed_index=0, es_index=2)
        # Manually remove es_line to test partial state
        widget._es_line = None
        widget.clear()
        assert widget._ed_line is None
