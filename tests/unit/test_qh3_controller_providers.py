"""QH-3 bridge removal: `_controller_ref` replaced by three narrow providers.

Before this slice, ``MainWindow`` and ``PresenterView`` poked an untyped
``viewer._controller_ref = controller`` attribute directly onto
``ViewerWidget`` — a bare ``AppController`` reference discovered through
``hasattr`` guards by four private ``ViewerWidget`` methods that actually
needed exactly three narrow things from it: the ROI of the last automatic
segmentation, the temporal fusion result, and the LA AI-assist
request/response pair (``docs/reviews/2026-11-06-qh3-magnifier-owner-ru.md``
item 1).

This is slice 1 of issue #420: the bridge is gone. ``ViewerWidget`` now
exposes three explicit setters — ``set_last_segment_roi_provider``,
``set_fusion_result_provider``, ``set_la_assist_provider`` — and
``MainWindow``/``PresenterView`` call them once at construction instead of
assigning a private attribute. The tests below characterize that each
provider is independently wireable, defaults to an inert no-op when unset,
and that the LA-assist signal connection keeps its original "connect lazily,
once" timing.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from echo_personal_tool.presentation.viewer_widget import ViewerWidget


@pytest.mark.gui
class TestControllerRefRemoved:
    def test_viewer_has_no_bare_controller_reference(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        assert not hasattr(w, "_controller_ref"), "the untyped controller bridge must be gone"


@pytest.mark.gui
class TestLastSegmentRoiProvider:
    def test_defaults_to_none_without_a_provider(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        assert w.contract.get_last_segment_roi() is None

    def test_forwards_to_the_wired_provider(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        w.set_last_segment_roi_provider(lambda: (1.0, 2.0, 3.0, 4.0))

        assert w.contract.get_last_segment_roi() == (1.0, 2.0, 3.0, 4.0)

    def test_clearing_the_provider_restores_none(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        w.set_last_segment_roi_provider(lambda: (1.0, 2.0, 3.0, 4.0))

        w.set_last_segment_roi_provider(None)

        assert w.contract.get_last_segment_roi() is None


@pytest.mark.gui
class TestFusionResultProvider:
    def test_defaults_to_none_without_a_provider(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        assert w.contract.get_fusion_result() is None

    def test_forwards_to_the_wired_provider(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        sentinel = object()

        w.set_fusion_result_provider(lambda: sentinel)

        assert w.contract.get_fusion_result() is sentinel


@pytest.mark.gui
class TestLaAssistProvider:
    def test_request_is_a_noop_without_a_provider(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        # Must not raise even though nothing was wired, and must not flip the
        # "connected" latch (there is no signal to connect to).
        w._request_la_assist_for_manual(septal=(0.0, 0.0), lateral=(1.0, 0.0), apex=(0.5, 1.0), frame_index=3)

        assert w._la_assist_connected is False

    def test_request_is_forwarded_with_the_manual_contour_landmarks(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        calls = []

        class _FakeSignal:
            def __init__(self):
                self.connected = []

            def connect(self, slot):
                self.connected.append(slot)

        signal = _FakeSignal()
        w.set_la_assist_provider(lambda **kwargs: calls.append(kwargs), signal)

        w._request_la_assist_for_manual(septal=(0.0, 0.0), lateral=(1.0, 0.0), apex=(0.5, 1.0), frame_index=3)

        assert calls == [
            {
                "frame_index": 3,
                "user_septal": (0.0, 0.0),
                "user_lateral": (1.0, 0.0),
                "user_apex": (0.5, 1.0),
            }
        ]
        assert signal.connected == [w._on_la_assist_contour_ready]

    def test_the_ready_signal_is_connected_only_once(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)

        class _FakeSignal:
            def __init__(self):
                self.connected = []

            def connect(self, slot):
                self.connected.append(slot)

        signal = _FakeSignal()
        w.set_la_assist_provider(lambda **_kwargs: None, signal)

        w._request_la_assist_for_manual(septal=(0.0, 0.0), lateral=(1.0, 0.0), apex=(0.5, 1.0), frame_index=0)
        w._request_la_assist_for_manual(septal=(0.0, 0.0), lateral=(1.0, 0.0), apex=(0.5, 1.0), frame_index=1)

        assert len(signal.connected) == 1, "connecting twice would double-fire the slot"

    def test_rewiring_the_provider_reconnects_to_the_new_signal(self, qtbot) -> None:
        """Re-wiring (e.g. a fresh controller) must not stay latched to a stale signal."""
        w = ViewerWidget()
        qtbot.addWidget(w)

        class _FakeSignal:
            def __init__(self):
                self.connected = []

            def connect(self, slot):
                self.connected.append(slot)

        first_signal = _FakeSignal()
        second_signal = _FakeSignal()
        w.set_la_assist_provider(lambda **_kwargs: None, first_signal)
        w._request_la_assist_for_manual(septal=(0.0, 0.0), lateral=(1.0, 0.0), apex=(0.5, 1.0), frame_index=0)
        assert len(first_signal.connected) == 1

        w.set_la_assist_provider(lambda **_kwargs: None, second_signal)
        w._request_la_assist_for_manual(septal=(0.0, 0.0), lateral=(1.0, 0.0), apex=(0.5, 1.0), frame_index=1)

        assert len(second_signal.connected) == 1

    def test_finish_manual_contour_triggers_assist_only_for_la_a4c_es(self, qtbot) -> None:
        """End-to-end: the manual-contour completion path reaches the provider."""
        w = ViewerWidget()
        qtbot.addWidget(w)
        calls = []
        w.set_la_assist_provider(lambda **kwargs: calls.append(kwargs), None)

        w.contract.active_mitral_annulus = ((80.0, 180.0), (140.0, 180.0))
        w.contract.active_contour_phase = "ES"
        w.contract.active_contour_view = "A4C"
        w.contract.active_contour_chamber = "LA"

        assert w._finish_manual_contour(apex=(112.0, 40.0)) is True
        assert len(calls) == 1

    def test_finish_manual_contour_skips_assist_for_other_chambers(self, qtbot) -> None:
        w = ViewerWidget()
        qtbot.addWidget(w)
        calls = []
        w.set_la_assist_provider(lambda **kwargs: calls.append(kwargs), None)

        w.contract.active_mitral_annulus = ((80.0, 180.0), (140.0, 180.0))
        w.contract.active_contour_phase = "ES"
        w.contract.active_contour_view = "A4C"
        w.contract.active_contour_chamber = "LV"

        assert w._finish_manual_contour(apex=(112.0, 40.0)) is True
        assert calls == []
