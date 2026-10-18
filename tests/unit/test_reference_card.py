"""Tests for the image-free S2 reference card."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_norm_formatting():
    from echo_personal_tool.domain.services.reference_data_store import NormRange
    from echo_personal_tool.presentation.reference_card import ReferenceCard

    assert ReferenceCard._format_range(NormRange(36, 51)) == "36–51"
    assert ReferenceCard._format_range(NormRange(low=67)) == "≥67"
    assert ReferenceCard._format_range(NormRange(high=10)) == "≤10"
    assert ReferenceCard._format_range(None) == ""


def test_missing_parameter_card_is_safe():
    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
    from echo_personal_tool.presentation.reference_card import ReferenceCard

    card = ReferenceCard(ReferenceDataStore(), "not.present", 12.0)
    assert card.parameter is None
    from PySide6.QtWidgets import QLabel

    assert card.findChildren(QLabel)
    card.close()


def test_card_does_not_embed_images_and_open_action_emits_parameter():
    from PySide6.QtWidgets import QLabel, QPushButton

    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
    from echo_personal_tool.presentation.reference_card import ReferenceCard

    store = ReferenceDataStore()
    store.load()
    # Pick a known parameter present in the packaged reference data.
    param_id = next(iter(store._param_index))
    card = ReferenceCard(store, param_id, 42, sex="female")
    assert card.parameter is not None
    assert not card.findChildren(QLabel, "referenceImage")
    opened: list[str] = []
    card.open_reference_requested.connect(opened.append)
    button = next(b for b in card.findChildren(QPushButton) if b.text())
    from unittest.mock import patch

    with patch("echo_personal_tool.presentation.ase_reference_dialog.show_ase_reference_dialog") as show:
        button.click()
    assert opened == [param_id]
    show.assert_called_once_with(card.window(), param_id=param_id)
    card.close()
