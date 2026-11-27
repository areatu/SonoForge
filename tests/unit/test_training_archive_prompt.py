"""Training-only opt-out: actual saved samples, no modal clinical confirmation."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from echo_personal_tool.presentation.training_archive_prompt import (
    TrainingArchivePrompt,
    install_training_archive_prompt,
)
from tests.unit.test_training_archive import setup_archive as setup_archive

pytestmark = pytest.mark.gui


@pytest.fixture
def prompt(qtbot, setup_archive):
    archive, capture, context, image, contour, _ = setup_archive
    viewer = QWidget()
    viewer.resize(800, 600)
    qtbot.addWidget(viewer)
    result = TrainingArchivePrompt(viewer, capture)
    viewer.show()
    capture.observe([contour], image, 2, context)
    capture.confirm(context.instance_key, 2)
    return result, archive, capture, viewer


def test_prompt_shows_and_no_excludes_training_only(prompt, qtbot):
    overlay, archive, _, viewer = prompt
    assert overlay.isVisibleTo(viewer)
    assert overlay.caption.text() == "Сохранить контур для обучения"
    assert len(archive.records()) == 1  # saved before the answer
    qtbot.mouseClick(overlay.no, Qt.MouseButton.LeftButton)
    assert not overlay.isVisible() and archive.records() == []


@pytest.mark.parametrize("answer", ["yes", "timeout"])
def test_yes_and_timeout_keep_saved_contour(prompt, qtbot, answer):
    overlay, archive, _, _ = prompt
    if answer == "yes":
        qtbot.mouseClick(overlay.yes, Qt.MouseButton.LeftButton)
    else:
        overlay.timer.start(1)
        qtbot.waitUntil(lambda: not overlay.isVisible())
    assert len(archive.records()) == 1
    assert not overlay.isVisible()


def test_disabled_collection_has_no_overlay(qtbot, monkeypatch):
    window = QWidget()
    qtbot.addWidget(window)
    window._controller = object()
    window._viewer = QWidget(window)
    monkeypatch.setattr(
        "echo_personal_tool.application.composition.services_of", lambda _: SimpleNamespace(training_archive=None)
    )
    install_training_archive_prompt(window)
    assert window.findChild(TrainingArchivePrompt) is None


def test_paused_capture_does_not_offer_contours(prompt):
    overlay, _, capture, _ = prompt
    decision = overlay.current
    overlay.accept()
    capture.set_paused(True)
    overlay.offer(decision)
    assert not overlay.isVisible()
