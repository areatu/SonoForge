"""QH-1a.2 GUI tests: an open comparison pair owns its sources across tab close.

These exercise the TabCoordinator guard that keeps a source still shown in the
comparison window from being purged when its tab is closed (spec §5.1 QH-1a Э10:
«Закрытие вкладки … не удаляет источник, ещё используемый открытой comparison
pair»). The comparison session itself is a lightweight fake; the production code
under test (TabCoordinator._comparison_owns_tab_source / close_inactive) is real.

Marked gui because importing tab_coordinator pulls in PySide6.QtWidgets.
"""

import pytest
from types import SimpleNamespace

from echo_personal_tool.application.tab_session import (
    TAB_ORIGIN_EMPTY,
    TabSessionManager,
)
from echo_personal_tool.domain.models.multiview import MultiViewSession, PaneId
from echo_personal_tool.presentation.tab_coordinator import TabCoordinator

pytestmark = pytest.mark.gui


def _fake_window(comparing_study_uid=None):
    session = MultiViewSession()
    if comparing_study_uid is not None:
        session.pane(PaneId.LEFT).study_uid = comparing_study_uid
        session.pane(PaneId.LEFT).instance = SimpleNamespace(sop_instance_uid="SOP_X")
    comparison = SimpleNamespace(session=SimpleNamespace(session=session))
    purged = []
    window = SimpleNamespace(
        _comparison=comparison,
        _tab_strip=SimpleNamespace(set_tabs=lambda *a, **k: None),
        _queue_cache_purge=lambda sid: purged.append(sid),
        _process_pending_cache_purges=lambda: None,
    )
    window._purged = purged
    return window


def _open_tab(manager: TabSessionManager, study_uid: str) -> str:
    manager.open_tab(origin=TAB_ORIGIN_EMPTY, activate=True, studies=[SimpleNamespace(study_uid=study_uid)])
    return manager.active_tab_id


def test_comparison_owns_tab_source_detects_reference(qapp):
    window = _fake_window(comparing_study_uid="STUDY_A")
    coord = TabCoordinator(window)
    assert coord._comparison_owns_tab_source(SimpleNamespace(studies=[SimpleNamespace(study_uid="STUDY_A")])) is True
    assert coord._comparison_owns_tab_source(SimpleNamespace(studies=[SimpleNamespace(study_uid="STUDY_B")])) is False


def test_close_inactive_skips_purge_when_comparison_owns_source(qapp):
    window = _fake_window(comparing_study_uid="STUDY_A")
    manager = TabSessionManager()
    tab_id = _open_tab(manager, "STUDY_A")
    TabCoordinator(window, manager=manager).close_inactive(tab_id)
    assert window._purged == []  # skipped: comparison still references STUDY_A


def test_close_inactive_purges_when_comparison_does_not_own_source(qapp):
    window = _fake_window(comparing_study_uid="STUDY_A")
    manager = TabSessionManager()
    tab_id = _open_tab(manager, "STUDY_B")  # not referenced by the comparison pair
    TabCoordinator(window, manager=manager).close_inactive(tab_id)
    assert len(window._purged) == 1  # purge ran because no comparison owns STUDY_B
