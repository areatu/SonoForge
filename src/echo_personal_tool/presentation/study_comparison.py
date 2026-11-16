"""Window action: compare the current study with an explicitly chosen one (issue 562).

The picker lists the studies already open in tabs, checks the pair's identity
and hands the choice to :class:`ComparisonCoordinator`.  The action never
scans the disk and never registers two studies automatically; automatic
registration and 3D are outside this scope by design.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.study_comparison import comparison_candidates
from echo_personal_tool.presentation.study_comparison_dialog import ask_comparison_candidate


def open_previous_study_comparison(window: Any) -> bool:
    """Ask for the other open study and start the comparison.

    Returns True only when the pair was opened.  Missing prerequisites are
    explained in a modal message instead of silently opening an empty pane.
    """
    comparison = window._comparison
    current = comparison.current_identity()
    if current is None:
        QMessageBox.information(window, tr("comparison.title"), tr("comparison.status.no_current"))
        return False
    tabs = window._tab_coordinator.tabs.tabs
    candidates = comparison_candidates(
        tabs,
        active_tab_id=window._tab_coordinator.tabs.active_tab_id,
        current_study_uid=current.study_uid,
    )
    if not candidates:
        QMessageBox.information(window, tr("comparison.title"), tr("comparison.empty"))
        return False
    candidate = ask_comparison_candidate(window, current=current, candidates=candidates)
    if candidate is None:
        return False
    measurements = None
    tab = window._tab_coordinator.tabs.get(candidate.tab_id)
    if tab is not None:
        measurements = tab.clinical_memory.studies.get(candidate.identity.study_uid)
    return bool(comparison.start_previous(candidate.identity, candidate.instance, measurements=measurements))
