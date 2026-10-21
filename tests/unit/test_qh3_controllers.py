"""QH-3.2 slices — tool / contour / calibration / worker bridge.

Spec §7.1–7.3, Gate G3.  Each controller owns one family and shares the same
generation-scoped ViewerContext so S-02 isolation and S-05 no-resurrection
are one check.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation.viewer.calibration_controller import CalibrationController
from echo_personal_tool.presentation.viewer.context import ViewerContext, ViewerPaneIdentity
from echo_personal_tool.presentation.viewer.contour_controller import ContourEditingController
from echo_personal_tool.presentation.viewer.tool_controller import ToolInteractionController
from echo_personal_tool.presentation.viewer.worker_bridge import WorkerBridge


class TestToolInteractionController:
    def test_activate_and_commit(self) -> None:
        committed: list[dict] = []

        def commit_handler(kind, start, end, ctx):  # noqa: ANN001
            committed.append({"kind": kind, "start": start, "end": end})
            from echo_personal_tool.presentation.viewer.commands import accepted

            return accepted()

        ctx = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=1)
        ctrl = ToolInteractionController(commit_handler=commit_handler)  # type: ignore[arg-type]
        ctrl.set_context(ctx)
        result = ctrl.activate("distance", label="Dist3")
        assert result.accepted
        ctrl.on_press((10.0, 10.0))
        ctrl.on_move((15.0, 10.0))
        ctrl.on_release((20.0, 10.0))
        assert len(committed) == 1
        assert committed[0]["start"] == (10.0, 10.0)

    def test_generation_bump_cancels_draft(self) -> None:
        ctx1 = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=1)
        ctx2 = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I2"), generation=2)
        ctrl = ToolInteractionController()
        ctrl.set_context(ctx1)
        ctrl.activate("distance")
        ctrl.on_press((0.0, 0.0))
        assert ctrl._session.start is not None
        ctrl.set_context(ctx2)
        assert ctrl._session.start is None  # cancelled

    def test_sequence_chain(self) -> None:
        outputs: list[str] = []

        def commit_handler(kind, start, end, ctx):  # noqa: ANN001
            outputs.append(ctx.identity.sop_instance_uid + kind)
            from echo_personal_tool.presentation.viewer.commands import accepted

            return accepted()

        ctx = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=0)
        ctrl = ToolInteractionController(commit_handler=commit_handler)  # type: ignore[arg-type]
        ctrl.set_context(ctx)
        ctrl.activate("area", sequence=["A1", "A2", "A3"])
        assert ctrl._session.label == "A1" or ctrl._session.kind == "area"
        # Second activation should cancel previous
        result = ctrl.activate("distance")
        assert result.accepted
        ctrl.dispose()

    def test_cancel_idempotent(self) -> None:
        ctrl = ToolInteractionController()
        ctrl.activate("distance")
        ctrl.cancel()
        assert not ctrl._session.active
        ctrl.cancel()
        assert not ctrl._session.active
        ctrl.dispose()


class TestContourEditingController:
    def test_select_and_delete(self) -> None:
        ctrl = ContourEditingController()
        ctx = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=0)
        ctrl.set_context(ctx)
        ctrl.set_contours([object(), object(), object()])
        result = ctrl.select(1)
        assert result.accepted
        assert ctrl.selected_index == 1
        del_result = ctrl.delete_selected()
        assert del_result.accepted
        assert ctrl.selected_index is None

    def test_draft_lifecycle(self) -> None:
        ctrl = ContourEditingController()
        result = ctrl.begin_draft(chamber="LV", view="A4C")
        assert result.accepted
        ctrl.add_draft_point((0.0, 0.0))
        ctrl.add_draft_point((1.0, 0.0))
        ctrl.add_draft_point((0.5, 1.0))
        result = ctrl.commit_draft()
        assert result.accepted
        assert not ctrl._draft_active

    def test_generation_bump_cancels_draft(self) -> None:
        ctrl = ContourEditingController()
        ctx1 = ViewerContext(generation=1)
        ctx2 = ViewerContext(generation=2)
        ctrl.set_context(ctx1)
        ctrl.begin_draft(chamber="LV")
        ctrl.add_draft_point((0.0, 0.0))
        ctrl.set_context(ctx2)
        assert not ctrl._draft_active

    def test_dispose_idempotent(self) -> None:
        ctrl = ContourEditingController()
        ctrl.set_contours([object()])
        ctrl.dispose()
        ctrl.dispose()


class TestCalibrationController:
    def test_activate_and_commit_spacing(self) -> None:
        committed: list[tuple[str, object]] = []

        ctrl = CalibrationController()
        # Connect signal — the domain helper yields an isotropic (x, y) pair.
        ctrl.calibration_committed.connect(lambda k, v: committed.append((str(k), v)))
        ctx = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=0)
        ctrl.set_context(ctx)
        ctrl.activate("depth")
        result = ctrl.commit_with_distance(known_mm=50.0, pixel_length=100.0)
        assert result.accepted
        assert len(committed) == 1
        # 50 mm over 100 px → 0.5 mm/px → spacing (0.5, 0.5) per helper
        assert committed[0][1] == pytest.approx((0.5, 0.5))

    def test_reject_small_pixel_length(self) -> None:
        ctrl = CalibrationController()
        ctrl.activate("depth")
        result = ctrl.commit_with_distance(known_mm=10.0, pixel_length=0.5)
        assert not result.accepted

    def test_generation_bump_cancels(self) -> None:
        ctrl = CalibrationController()
        ctx1 = ViewerContext(generation=1)
        ctx2 = ViewerContext(generation=2)
        ctrl.set_context(ctx1)
        ctrl.activate("depth")
        assert ctrl.active
        ctrl.set_context(ctx2)
        assert not ctrl.active
        ctrl.dispose()

    def test_dispose(self) -> None:
        ctrl = CalibrationController()
        ctrl.activate("depth")
        ctrl.dispose()
        assert not ctrl.active
        ctrl.dispose()


class TestWorkerBridge:
    def test_spawn_and_deliver_current(self) -> None:
        bridge = WorkerBridge()
        ctx = ViewerContext(identity=ViewerPaneIdentity(sop_instance_uid="I1"), generation=1)
        bridge.set_context(ctx)
        token = bridge.spawn(ctx, operation="onnx")
        delivered: list[object] = []

        def handler(result):  # noqa: ANN001
            delivered.append(result)
            from echo_personal_tool.presentation.viewer.commands import accepted

            return accepted(payload=result)

        result = bridge.deliver(token, {"ok": True}, handler)
        assert result.accepted
        assert delivered == [{"ok": True}]

    def test_stale_token_discarded(self) -> None:
        bridge = WorkerBridge()
        ctx1 = ViewerContext(generation=1)
        ctx2 = ViewerContext(generation=2)
        bridge.set_context(ctx1)
        token = bridge.spawn(ctx1, operation="decode")
        # Source switched
        bridge.set_context(ctx2)

        def handler(result):  # noqa: ANN001
            from echo_personal_tool.presentation.viewer.commands import accepted

            return accepted()

        result = bridge.deliver(token, {}, handler)
        assert result.discarded_stale

    def test_cancel_all_for_generation(self) -> None:
        bridge = WorkerBridge()
        ctx1 = ViewerContext(generation=1)
        ctx2 = ViewerContext(generation=1)
        bridge.spawn(ctx1, operation="a")
        bridge.spawn(ctx2, operation="b")
        assert bridge.active_count() == 2
        removed = bridge.cancel_all_for_generation(1)
        assert removed == 2
        assert bridge.active_count() == 0
        bridge.dispose()
        assert bridge.active_count() == 0
