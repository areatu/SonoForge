"""Switching the comparison gallery does not replace the main viewer."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from echo_personal_tool.application.tab_session import TAB_ORIGIN_FOLDER, TabSessionManager
from echo_personal_tool.domain.models.metadata import StudyMetadata
from echo_personal_tool.presentation.tab_coordinator import TabCoordinator


def test_gallery_only_switch_preserves_controller_until_comparison_ends():
    tabs = TabSessionManager()
    first = tabs.open_tab(
        origin=TAB_ORIGIN_FOLDER,
        root="/first",
        studies=[
            StudyMetadata(study_uid="first", study_datetime=datetime(2026, 1, 1), series=()),
        ],
    )
    second = tabs.open_tab(
        origin=TAB_ORIGIN_FOLDER,
        root="/second",
        studies=[
            StudyMetadata(study_uid="second", study_datetime=datetime(2026, 1, 2), series=()),
        ],
        activate=False,
    )
    gallery = SimpleNamespace(populate=Mock(), request_visible_previews=Mock())
    host = SimpleNamespace(_multiview_mode=True, _gallery=gallery, _tab_flush_or_block=Mock(return_value=True))
    coordinator = TabCoordinator(host, manager=tabs)
    coordinator.park_active = Mock()
    coordinator.refresh_strip = Mock()
    coordinator.load_content = Mock()

    assert coordinator.switch_to(second.tab_id)
    assert tabs.active_tab_id == second.tab_id
    assert coordinator.comparison_origin_tab_id == first.tab_id
    coordinator.park_active.assert_called_once()
    coordinator.load_content.assert_not_called()
    gallery.populate.assert_called_once_with(second.studies)
    gallery.request_visible_previews.assert_called_once()

    coordinator.finish_comparison_browsing()
    coordinator.load_content.assert_called_once_with(second)
    assert coordinator.comparison_origin_tab_id is None
