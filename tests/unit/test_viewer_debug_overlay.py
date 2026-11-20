"""#619: the debug overlay has one owner — ``DebugOverlayController``.

``ViewerWidget`` used to keep the visibility flag, the monospace label and the
ROI rectangle as its own attributes and drive them from three methods.  The
characterisation below pins the extracted arrangement:

* the viewer exposes ``debug_overlay`` and keeps no overlay state of its own;
* the public facade (``toggle_debug_overlay`` / ``is_debug_overlay_visible`` /
  ``debug_overlay_text``) is a thin forward to the owner;
* the ROI rectangle is drawn only while the overlay is visible and is removed
  on toggle-off and on ``dispose()``;
* ``ViewerContract`` forwards the three legacy private names to the owner.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QWidget

from echo_personal_tool.presentation.viewer.debug_overlay import DebugOverlayController
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

pytestmark = pytest.mark.gui


def _controller(qtbot, roi=None) -> DebugOverlayController:
    host = QWidget()
    qtbot.addWidget(host)
    graphics = SimpleNamespace(
        geometry=lambda: SimpleNamespace(width=lambda: 400, height=lambda: 300, x=lambda: 0, y=lambda: 0),
        devicePixelRatioF=lambda: 1.0,
    )
    controller = DebugOverlayController(
        parent=host,
        view=_FakeView(),
        frame_provider=lambda: np.zeros((80, 60), dtype=np.uint8),
        state_provider=lambda: SimpleNamespace(instance=None),
        graphics_provider=lambda: graphics,
        roi_provider=lambda: roi,
    )
    return controller


class _FakeView:
    def __init__(self) -> None:
        self.items: list[object] = []

    def addItem(self, item) -> None:
        self.items.append(item)

    def removeItem(self, item) -> None:
        if item in self.items:
            self.items.remove(item)


@pytest.mark.gui
class TestDebugOverlayOwner:
    def test_toggle_flips_visibility_and_label(self, qtbot) -> None:
        controller = _controller(qtbot)
        assert controller.is_visible() is False
        assert controller.text() == ""
        assert controller.label.isHidden()

        assert controller.toggle() is True
        assert controller.is_visible() is True
        assert not controller.label.isHidden()
        text = controller.text()
        assert "Native: 60x80" in text
        assert "Viewport: 400x300" in text
        assert "DPR:" in text

        assert controller.toggle() is False
        assert controller.is_visible() is False
        assert controller.text() == ""
        assert controller.label.isHidden()

    def test_update_is_a_no_op_while_hidden(self, qtbot) -> None:
        controller = _controller(qtbot)
        controller.update()
        assert controller.label.text() == ""
        assert controller.is_visible() is False

    def test_roi_rect_drawn_only_while_visible(self, qtbot) -> None:
        controller = _controller(qtbot, roi=(1.0, 2.0, 30.0, 40.0))
        controller.toggle()
        assert controller.roi_item is not None
        assert "ROI: 1,2-30,40" in controller.text()

        controller.toggle()
        assert controller.roi_item is None

    def test_dispose_hides_label_and_clears_roi(self, qtbot) -> None:
        controller = _controller(qtbot, roi=(0.0, 0.0, 5.0, 5.0))
        controller.toggle()
        assert controller.roi_item is not None
        controller.dispose()
        controller.dispose()  # idempotent
        assert controller.is_visible() is False
        assert controller.label.isHidden()
        assert controller.roi_item is None


@pytest.mark.gui
class TestViewerFacade:
    def test_viewer_delegates_to_the_owner(self, qtbot) -> None:
        viewer = ViewerWidget()
        qtbot.addWidget(viewer)
        assert viewer.debug_overlay is not None
        assert "DebugOverlayController" in viewer.qh3_controller_inventory()

        assert viewer.is_debug_overlay_visible is False
        assert viewer.debug_overlay_text() == ""
        viewer.toggle_debug_overlay()
        assert viewer.is_debug_overlay_visible is True
        assert "Viewport:" in viewer.debug_overlay_text()
        viewer.toggle_debug_overlay()
        assert viewer.is_debug_overlay_visible is False
        assert viewer.debug_overlay_text() == ""

    def test_contract_forwards_the_legacy_names(self, qtbot) -> None:
        viewer = ViewerWidget()
        qtbot.addWidget(viewer)
        contract = viewer.contract
        assert contract.debug_overlay_visible is False
        assert contract.debug_overlay_label is viewer.debug_overlay.label
        assert contract.debug_roi_item is None
        viewer.toggle_debug_overlay()
        assert contract.debug_overlay_visible is True
        assert not contract.debug_overlay_label.isHidden()
        viewer.toggle_debug_overlay()
        assert contract.debug_overlay_visible is False
