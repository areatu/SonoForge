"""Unit tests for constructor/preview/reference_preview."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


class TestReferencePreviewWindow:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel
        from echo_personal_tool.constructor.preview.reference_preview import (
            ReferencePreviewWindow,
        )

        model = ReferenceModel()
        window = ReferencePreviewWindow(model)
        qtbot.addWidget(window)
        assert window.windowTitle() == "Preview — Справочник"

    def test_render_empty(self, qtbot) -> None:
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel
        from echo_personal_tool.constructor.preview.reference_preview import (
            ReferencePreviewWindow,
        )

        model = ReferenceModel()
        window = ReferencePreviewWindow(model)
        qtbot.addWidget(window)
        # Should not crash
        assert window._browser is not None

    def test_format_norm_none(self, qtbot) -> None:
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel
        from echo_personal_tool.constructor.preview.reference_preview import (
            ReferencePreviewWindow,
        )

        model = ReferenceModel()
        window = ReferencePreviewWindow(model)
        qtbot.addWidget(window)
        result = window._format_norm(None)
        assert "—" in result

    def test_format_norm_with_range(self, qtbot) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            NormRangeModel,
            ReferenceModel,
        )
        from echo_personal_tool.constructor.preview.reference_preview import (
            ReferencePreviewWindow,
        )

        model = ReferenceModel()
        window = ReferencePreviewWindow(model)
        qtbot.addWidget(window)
        norm = NormRangeModel(low=60.0, high=100.0)
        result = window._format_norm(norm)
        assert "60.0" in result
        assert "100.0" in result

    def test_format_norm_low_only(self, qtbot) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            NormRangeModel,
            ReferenceModel,
        )
        from echo_personal_tool.constructor.preview.reference_preview import (
            ReferencePreviewWindow,
        )

        model = ReferenceModel()
        window = ReferencePreviewWindow(model)
        qtbot.addWidget(window)
        norm = NormRangeModel(low=50.0)
        result = window._format_norm(norm)
        assert ">=50.0" in result

    def test_format_norm_high_only(self, qtbot) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            NormRangeModel,
            ReferenceModel,
        )
        from echo_personal_tool.constructor.preview.reference_preview import (
            ReferencePreviewWindow,
        )

        model = ReferenceModel()
        window = ReferencePreviewWindow(model)
        qtbot.addWidget(window)
        norm = NormRangeModel(high=120.0)
        result = window._format_norm(norm)
        assert "<=120.0" in result

    def test_format_norm_empty(self, qtbot) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            NormRangeModel,
            ReferenceModel,
        )
        from echo_personal_tool.constructor.preview.reference_preview import (
            ReferencePreviewWindow,
        )

        model = ReferenceModel()
        window = ReferencePreviewWindow(model)
        qtbot.addWidget(window)
        norm = NormRangeModel()
        result = window._format_norm(norm)
        assert "—" in result
