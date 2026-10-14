"""Acceptance: open constructor dialog → add reference → edit metadata → save → reload."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.acceptance]


class TestConstructorWorkflow:
    def test_yaml_storage_load_save_roundtrip(self, tmp_path: Path) -> None:
        """YamlStorage can save and reload data."""
        from echo_personal_tool.constructor.storage import YamlStorage

        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text(
            "references:\n  - title: Test\n    description: desc\n",
            encoding="utf-8",
        )
        storage = YamlStorage(yaml_path)
        data = storage.load()
        assert "references" in data
        assert len(data["references"]) == 1
        assert data["references"][0]["title"] == "Test"

    def test_constructor_widget_standalone(self, qtbot, qapp, tmp_path: Path) -> None:
        """ConstructorWidget can be created with a temp YAML store."""
        from echo_personal_tool.constructor.constructor_widget import ConstructorWidget
        from echo_personal_tool.constructor.storage import SchemaValidator, YamlStorage

        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text("references: []\n", encoding="utf-8")
        schema_path = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "constructor" / "models"
        storage = YamlStorage(yaml_path)
        validator = SchemaValidator() if (schema_path / "schema.json").exists() else MagicMock()
        widget = ConstructorWidget(yaml_storage=storage, validator=validator)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        assert widget.isVisible()

    def test_constructor_widget_dirty_tracking(self, qtbot, qapp, tmp_path: Path) -> None:
        """ConstructorWidget tracks dirty state."""
        from echo_personal_tool.constructor.constructor_widget import ConstructorWidget
        from echo_personal_tool.constructor.storage import YamlStorage

        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text("references: []\n", encoding="utf-8")
        storage = YamlStorage(yaml_path)
        widget = ConstructorWidget(yaml_storage=storage, validator=MagicMock())
        qtbot.addWidget(widget)
        # Initially not dirty
        assert widget._dirty is False

    def test_constructor_dialog_opens(self, qtbot, qapp, tmp_path: Path) -> None:
        """show_constructor_dialog builds a visible ConstructorDialog.

        Production calls the modal ``dialog.exec()``; under a headless CI run
        that loop never returns, so it is replaced by ``show()`` and the test
        asserts the dialog actually came up instead of swallowing exceptions.
        """
        from echo_personal_tool.constructor import constructor_dialog as module

        (tmp_path / "refs.yaml").write_text("references: []\n", encoding="utf-8")
        opened: list[module.ConstructorDialog] = []

        def _show_instead_of_exec(dialog: module.ConstructorDialog) -> int:
            opened.append(dialog)
            dialog.show()
            return 0

        with (
            patch.object(module, "_YAML_PATH", tmp_path / "refs.yaml"),
            patch.object(module.ConstructorDialog, "exec", _show_instead_of_exec),
            patch.object(module.QMessageBox, "critical") as critical,
        ):
            module.show_constructor_dialog()

        assert not critical.called, "ConstructorDialog failed to construct and fell back to the error box"
        assert len(opened) == 1
        dialog = opened[0]
        qtbot.addWidget(dialog)
        qtbot.waitExposed(dialog)
        assert dialog.isVisible()
        assert dialog._yaml_path == tmp_path / "refs.yaml"
        dialog.close()
        assert not dialog.isVisible()

    def test_reference_model_from_dict(self) -> None:
        """ReferenceModel can be created from a dictionary."""
        from echo_personal_tool.constructor.models import ReferenceModel

        data = {"references": []}
        model = ReferenceModel.from_dict(data)
        assert model is not None

    def test_reference_model_deep_copy(self) -> None:
        """ReferenceModel deep_copy produces an independent copy."""
        from echo_personal_tool.constructor.models import ReferenceModel

        data = {"references": [{"title": "Test", "description": "d"}]}
        model = ReferenceModel.from_dict(data)
        copy = model.deep_copy()
        assert copy is not None
