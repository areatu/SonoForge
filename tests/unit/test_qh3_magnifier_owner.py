"""QH-3 (#420): the magnifier has one owner — its controller.

The QH-3 pilot left a second copy of the magnifier settings
(enabled/zoom/radius/linear-persistent, held/persistent flags, reduce-motion)
and a second implementation of the lens geometry inside ``ViewerWidget``.
The two copies could drift apart, and nothing tested which one the loupe
actually used.

The characterisation below pins the arrangement that replaces it:

* the viewer exposes ``magnifier_controller`` and keeps **no** magnifier state;
* user preferences reach the loupe through one ``configure()`` call on the owner;
* pointer/key routing calls the owner with the display buffer and the view
  mapping instead of recomputing geometry in the widget;
* the persistent-loupe predicate (linear B/M only) is the owner's;
* switching the magnifier off hides an already visible lens.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QPointF

from echo_personal_tool.application.user_preferences import default_user_preferences
from echo_personal_tool.presentation.viewer.magnifier_controller import MagnifierController
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

# Every attribute that duplicated controller state before this slice.
_DUPLICATED_STATE = (
    "_magnifier_enabled",
    "_magnifier_zoom",
    "_magnifier_radius_px",
    "_magnifier_held",
    "_magnifier_linear_persistent",
    "_magnifier_persistent_active",
    "_magnifier_lens",
    "_reduce_motion",
)


def _viewer(qtbot) -> ViewerWidget:
    import numpy as np

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((80, 80), dtype=np.uint8))
    viewer.show()
    return viewer


@pytest.mark.gui
class TestMagnifierSingleOwner:
    def test_the_viewer_holds_no_second_copy_of_the_magnifier_state(self, qtbot) -> None:
        viewer = _viewer(qtbot)

        for name in _DUPLICATED_STATE:
            assert not hasattr(viewer, name), f"{name} would be a second source of truth"

        owner = viewer.magnifier_controller
        assert isinstance(owner, MagnifierController)
        assert owner is viewer.magnifier_controller, "the owner must be stable, not rebuilt per access"

    def test_preferences_reach_the_loupe_through_one_configure_call(self, qtbot) -> None:
        viewer = _viewer(qtbot)
        owner = viewer.magnifier_controller
        preferences = replace(
            default_user_preferences(),
            magnifier_enabled=True,
            magnifier_zoom=4.0,
            magnifier_radius_px=90,
            magnifier_linear_persistent=True,
            reduce_motion=True,
        )

        viewer.apply_user_preferences(preferences)

        assert (owner.enabled, owner.zoom, owner.radius_px, owner.linear_persistent) == (True, 4.0, 90.0, True)

    def test_switching_the_magnifier_off_hides_a_visible_lens(self, qtbot) -> None:
        viewer = _viewer(qtbot)
        owner = viewer.magnifier_controller
        owner.set_held(True, cursor_scene_pos=QPointF(10.0, 10.0))
        assert owner.lens is not None and owner.lens.isVisible()

        viewer.apply_user_preferences(replace(default_user_preferences(), magnifier_enabled=False))

        assert owner.enabled is False
        assert owner.lens is not None and owner.lens.isVisible() is False

    def test_zoom_is_clamped_by_the_owner(self, qtbot) -> None:
        viewer = _viewer(qtbot)

        viewer.magnifier_controller.configure(zoom=99.0)

        assert viewer.magnifier_controller.zoom == 6.0

    def test_scene_mouse_routing_calls_the_owner_with_display_and_mapping(self, qtbot, monkeypatch) -> None:
        viewer = _viewer(qtbot)
        owner = viewer.magnifier_controller
        calls: list[tuple[object, object, object]] = []

        def fake_update_loupe(_self, scene_pos, *, display=None, view_mapping=None):  # noqa: ANN001
            calls.append((scene_pos, display, view_mapping))

        monkeypatch.setattr(MagnifierController, "update_loupe", fake_update_loupe)

        viewer._on_scene_mouse_moved(QPointF(12.0, 12.0))

        assert calls == [(QPointF(12.0, 12.0), viewer._image_item.image, viewer._view.mapSceneToView)]
        assert owner.lens is None  # the fake never builds a lens

    def test_hold_and_release_move_only_the_owner_state(self, qtbot) -> None:
        viewer = _viewer(qtbot)
        owner = viewer.magnifier_controller

        owner.set_held(True, cursor_scene_pos=QPointF(9.0, 9.0))
        assert owner.held is True
        assert owner.lens is not None and owner.lens.isVisible()

        owner.set_held(False)
        assert owner.held is False
        # Release hides the loupe with the ordinary (animated) hide.
        qtbot.waitUntil(lambda: owner.lens is not None and owner.lens.isVisible() is False, timeout=2000)

    def test_persistent_loupe_predicate_belongs_to_the_owner(self, qtbot) -> None:
        viewer = _viewer(qtbot)
        owner = viewer.magnifier_controller
        owner.configure(linear_persistent=True)

        owner.sync_persistent(True, doppler_mode="peak")
        assert owner.persistent_active is False

        owner.sync_persistent(True, doppler_mode="none", vessel_status="none")
        assert owner.persistent_active is True

        owner.configure(linear_persistent=False)
        owner.sync_persistent(True)
        assert owner.persistent_active is False

    def test_dispose_drops_the_lens_and_the_transient_flags(self, qtbot) -> None:
        viewer = _viewer(qtbot)
        owner = viewer.magnifier_controller
        owner.configure(linear_persistent=True)
        owner.sync_persistent(True)
        assert owner.lens is not None

        owner.dispose()
        owner.dispose()  # idempotent, no RuntimeWarning

        assert owner.lens is None
        assert owner.held is False
        assert owner.persistent_active is False
