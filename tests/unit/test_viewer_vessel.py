"""Tests for viewer vessel measurement integration."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


def _viewer():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    return ViewerWidget()


def test_is_vessel_available_without_calibration():
    viewer = _viewer()
    assert viewer.is_vessel_available() is False


def test_vessel_mode_requires_frame():
    viewer = _viewer()
    assert viewer.start_vessel_psv() is False
    assert not hasattr(viewer, "start_vessel_edv")
