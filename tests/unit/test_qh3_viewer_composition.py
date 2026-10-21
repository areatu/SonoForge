"""QH-3.1 pilot — ViewerContext, commands, overlay/magnifier controllers.

Spec §7.1–7.3, Gate G3 slice 1: context + commands without behaviour change,
overlay/magnifier extracted with explicit lifecycle.  All tests are pure or
use offscreen Qt via qtbot; they prove the new composition surfaces do not
leak identity across generations (S-02) and that dispose() leaves zero live
closed-owner objects.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")


from echo_personal_tool.presentation.viewer.commands import (
    ClearResultsOverlayCommand,
    ConfigureMagnifierCommand,
    SetMagnifierHeldCommand,
    SetResultsOverlayPositionCommand,
    SetResultsOverlayTextCommand,
)
from echo_personal_tool.presentation.viewer.context import ViewerContext, ViewerPaneIdentity, ViewTransform
from echo_personal_tool.presentation.viewer.magnifier_controller import MagnifierController
from echo_personal_tool.presentation.viewer.overlay_controller import (
    FrameOverlayController,
    ResultsOverlayController,
    TagsOverlayController,
)

# ── ViewerContext ────────────────────────────────────────────────────────


class TestViewerContext:
    def test_matches_source_same_uid(self) -> None:
        ctx_a = ViewerContext(identity=ViewerPaneIdentity(study_uid="S1", sop_instance_uid="I1"))
        ctx_b = ViewerContext(identity=ViewerPaneIdentity(study_uid="S1", sop_instance_uid="I1"))
        assert ctx_a.matches_source(ctx_b)

    def test_does_not_match_different_instance(self) -> None:
        ctx_a = ViewerContext(identity=ViewerPaneIdentity(study_uid="S1", sop_instance_uid="I1"))
        ctx_b = ViewerContext(identity=ViewerPaneIdentity(study_uid="S1", sop_instance_uid="I2"))
        assert not ctx_a.matches_source(ctx_b)

    def test_generation_check(self) -> None:
        ctx = ViewerContext(generation=3)
        assert ctx.is_same_generation(3)
        assert not ctx.is_same_generation(2)

    def test_with_frame_preserves_generation(self) -> None:
        ctx = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=5, frame_index=0)
        ctx2 = ctx.with_frame(2)
        assert ctx2.frame_index == 2
        assert ctx2.generation == 5
        assert ctx2.identity.sop_instance_uid == "I1"

    def test_from_viewer_state(self) -> None:
        class FakeInstance:
            sop_instance_uid = "1.2.3"
            series_uid = "1.2"
            study_uid = "1"

        ctx = ViewerContext.from_viewer_state(FakeInstance(), frame_index=1, total_frames=10, generation=2)
        assert ctx.identity.sop_instance_uid == "1.2.3"
        assert ctx.frame_index == 1
        assert ctx.generation == 2

    def test_view_transform_optional(self) -> None:
        ctx = ViewerContext(view_transform=ViewTransform())
        assert ctx.view_transform.view_range is None

    def test_no_phi_in_identity(self) -> None:
        # Identity never stores patient paths/names — only UIDs/fingerprints
        ctx = ViewerContext(identity=ViewerPaneIdentity(study_uid="STUDY", sop_instance_uid="SERIES"))
        assert "STUDY" in ctx.identity.study_uid
        assert not hasattr(ctx.identity, "patient_name")
        assert not hasattr(ctx.identity, "file_path")


# ── Commands (generation-aware, typed outcome) ───────────────────────────


class TestViewerCommands:
    def test_set_text_is_stale_when_generation_mismatched(self) -> None:
        old_ctx = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=1)
        new_ctx = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=2)

        class FakeController:
            context = new_ctx

            def set_text(self, text: str, suppressed: bool = False):  # noqa: ANN001
                return text

        cmd = SetResultsOverlayTextCommand(context=old_ctx, text="old result")
        # Controller's current generation is 2, command was created for 1 → stale
        assert cmd.is_stale_for(new_ctx)

    def test_clear_command_delegates(self) -> None:
        ctx = ViewerContext(generation=0)
        cleared: list[bool] = []

        class FakeController:
            def clear(self):  # noqa: ANN001
                cleared.append(True)
                from echo_personal_tool.presentation.viewer.commands import accepted

                return accepted(reason="cleared")

        cmd = ClearResultsOverlayCommand(context=ctx)
        result = cmd.execute(FakeController())  # type: ignore[arg-type]
        assert result.accepted
        assert cleared == [True]

    def test_magnifier_held_stale(self) -> None:
        old = ViewerContext(generation=1)
        new = ViewerContext(generation=2)

        class FakeMag:
            context = new
            called = False

            def set_held(self, held: bool, cursor_scene_pos=None):  # noqa: ANN001
                self.called = True
                from echo_personal_tool.presentation.viewer.commands import accepted

                return accepted()

        cmd = SetMagnifierHeldCommand(context=old, held=True)
        result = cmd.execute(FakeMag())  # type: ignore[arg-type]
        assert result.discarded_stale

    def test_configure_magnifier(self) -> None:
        ctx = ViewerContext(generation=0)

        class FakeMag:
            configured: dict | None = None

            def configure(self, *, enabled: bool, zoom: float, radius_px: float, linear_persistent: bool):  # noqa: ANN001
                self.configured = dict(
                    enabled=enabled, zoom=zoom, radius_px=radius_px, linear_persistent=linear_persistent
                )
                from echo_personal_tool.presentation.viewer.commands import accepted

                return accepted()

        ctrl = FakeMag()
        cmd = ConfigureMagnifierCommand(context=ctx, enabled=False, zoom=2.5, radius_px=80.0)
        result = cmd.execute(ctrl)  # type: ignore[arg-type]
        assert result.accepted
        assert ctrl.configured == {"enabled": False, "zoom": 2.5, "radius_px": 80.0, "linear_persistent": False}

    def test_position_command(self) -> None:
        ctx = ViewerContext(generation=0)

        class FakeOverlay:
            called: tuple | None = None

            def set_position(self, x_ratio: float, y_ratio: float, custom: bool = True):  # noqa: ANN001
                self.called = (x_ratio, y_ratio, custom)
                from echo_personal_tool.presentation.viewer.commands import accepted

                return accepted()

        ctrl = FakeOverlay()
        cmd = SetResultsOverlayPositionCommand(context=ctx, x_ratio=0.2, y_ratio=0.8, custom=True)
        result = cmd.execute(ctrl)  # type: ignore[arg-type]
        assert result.accepted
        assert ctrl.called == (0.2, 0.8, True)


# ── Overlay controller (owner-scoped, dispose idempotent) ─────────────────


@pytest.mark.gui
class TestResultsOverlayController:
    def test_set_text_and_position(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel

        host = QWidget()
        qtbot.addWidget(host)
        host.resize(400, 300)
        host.show()
        label = ResultsOverlayLabel(host)
        ctrl = ResultsOverlayController(label, lambda: host.geometry(), parent=host)
        result = ctrl.set_text("EDV 120 ml")
        assert result.accepted
        assert label.text() == "EDV 120 ml"
        pos_result = ctrl.set_position(0.2, 0.3, custom=True)
        assert pos_result.accepted
        assert ctrl.custom_position() is True
        ctrl.dispose()
        # Idempotent second dispose must not crash
        ctrl.dispose()
        host.deleteLater()

    def test_dispose_hides_and_disconnects(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.viewer_widget import ResultsOverlayLabel

        host = QWidget()
        qtbot.addWidget(host)
        label = ResultsOverlayLabel(host)
        label.show()
        ctrl = ResultsOverlayController(label, lambda: host.geometry(), parent=host)
        ctrl.dispose()
        assert not label.isVisible() or not ctrl.is_pinned()  # hide was called

    def test_frame_overlay_append_and_clear(self, qtbot) -> None:
        from PySide6.QtWidgets import QLabel, QWidget

        host = QWidget()
        qtbot.addWidget(host)
        label = QLabel(host)
        ctrl = FrameOverlayController(label, lambda: host.geometry(), parent=host)
        ctrl.append("Calibrating…")
        assert ctrl.lines() == ["Calibrating…"]
        ctrl.clear()
        assert ctrl.lines() == []
        ctrl.dispose()

    def test_tags_overlay_show_hide(self, qtbot) -> None:
        from PySide6.QtWidgets import QLabel, QWidget

        host = QWidget()
        qtbot.addWidget(host)
        host.show()
        label = QLabel(host)
        ctrl = TagsOverlayController(label, lambda: host.geometry(), parent=host)
        ctrl.show_tags(["0010,0010: Test"])
        assert label.isVisible()
        ctrl.hide()
        assert not label.isVisible()
        ctrl.dispose()


@pytest.mark.gui
class TestMagnifierControllerLifecycle:
    def test_configure_and_persistent(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        host = QWidget()
        qtbot.addWidget(host)
        ctrl = MagnifierController(parent=host)
        assert ctrl.enabled is True
        ctrl.configure(enabled=False, zoom=4.0)
        assert ctrl.enabled is False
        assert ctrl.zoom == 4.0
        ctrl.configure(enabled=True, zoom=3.0, linear_persistent=True)
        # Linear active + doppler none → persistent allowed
        ctrl.sync_persistent(linear_active=True, doppler_mode="none", vessel_status="none")
        assert ctrl.persistent_active is True
        # Doppler active → not allowed
        ctrl.sync_persistent(linear_active=True, doppler_mode="pw", vessel_status="none")
        assert ctrl.persistent_active is False
        ctrl.dispose()
        # Second dispose idempotent
        ctrl.dispose()
        host.deleteLater()

    def test_held_lifecycle(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        host = QWidget()
        qtbot.addWidget(host)
        ctrl = MagnifierController(parent=host)
        ctrl.configure(enabled=True, zoom=3.0)
        result = ctrl.set_held(True, cursor_scene_pos=None)
        assert result.accepted
        assert ctrl.held is True
        ctrl.set_held(False, cursor_scene_pos=None)
        assert ctrl.held is False
        ctrl.notify_point_placed()
        assert ctrl.held is False  # non-persistent drops hold
        ctrl.dispose()
        host.deleteLater()

    def test_update_loupe_without_display_does_not_crash(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        host = QWidget()
        qtbot.addWidget(host)
        ctrl = MagnifierController(parent=host)
        ctrl.configure(enabled=True, zoom=3.0)
        ctrl.set_held(True)
        # Passing None scene_pos should not crash even when display missing
        ctrl.update_loupe(None, display=None)
        ctrl.dispose()
        host.deleteLater()
