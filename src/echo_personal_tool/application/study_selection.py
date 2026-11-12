"""Single owner of the study/series selection in the Orthanc browser.

Before this slice the selection lived in two places: the dialog's
``_selected_all``/``_selected_series`` sets *and* the ``ROLE_CHECKED`` /
``ROLE_PARTIAL`` data of the tree items.  Five write paths kept the two
representations in sync by hand, and the download plan was rebuilt from both.
The rules below are the contract that used to be implicit in the dialog:

* a study is either **whole** (all its known series) or **partial** (an
  explicit set of series, possibly empty);
* a whole study stays whole while its series list is still loading — the plan
  then carries an empty list and the dialog fetches the list before download;
* a study that is not listed (patient history, stale result) stays selected and
  is reported in :meth:`whole_studies`, but is excluded from a plan built for
  the visible result set;
* :meth:`selected_series` returns a copy: callers cannot bypass the owner.

The class is pure Python and has no Qt dependency, so the rules can be tested
without a dialog or an event loop.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence

#: ``(study_uid, series_uids)`` pair of a download plan.
DownloadEntry = tuple[str, list[str]]


class StudySelection:
    """Whole studies and explicit series, with the partial/whole rules."""

    def __init__(self) -> None:
        self._whole_studies: set[str] = set()
        self._selected_series: dict[str, set[str]] = {}

    def __bool__(self) -> bool:
        return bool(self._whole_studies or self._selected_series)

    def clear(self) -> None:
        self._whole_studies.clear()
        self._selected_series.clear()

    def whole_studies(self) -> set[str]:
        """UIDs marked as «whole study» (copy, includes off-list studies)."""
        return set(self._whole_studies)

    def is_whole(self, study_uid: str) -> bool:
        return study_uid in self._whole_studies

    def selected_series(self, study_uid: str) -> set[str]:
        """Explicitly selected series of a partial study (copy)."""
        return set(self._selected_series.get(study_uid, ()))

    def study_uids(self) -> list[str]:
        """Selected studies in a stable order: whole first, then partial."""
        return list(dict.fromkeys([*self._whole_studies, *self._selected_series]))

    def select_study(self, study_uid: str, series_uids: Iterable[str] | None = None) -> None:
        """Mark a study whole; optionally seed its series when they are known.

        ``series_uids=None`` means «the list is still loading»: the whole-study
        flag is enough and the dialog fetches the list before downloading.
        """
        self._whole_studies.add(study_uid)
        if series_uids is not None:
            self._selected_series[study_uid] = {uid for uid in series_uids if uid}

    def deselect_study(self, study_uid: str) -> None:
        self._whole_studies.discard(study_uid)
        self._selected_series.pop(study_uid, None)

    def sync_known_series(self, study_uid: str, series_uids: Iterable[str]) -> None:
        """Mirror a freshly loaded series list for a whole study.

        A partial selection is not touched: its explicit set is the user's
        choice, not a projection of the cache.
        """
        if study_uid in self._whole_studies:
            self._selected_series[study_uid] = {uid for uid in series_uids if uid}

    def set_series_selected(
        self,
        study_uid: str,
        series_uid: str,
        selected: bool,
        known_series_uids: Iterable[str],
    ) -> set[str]:
        """Toggle one series and return the new explicit selection.

        An empty explicit set is kept as a key: the dialog's existing plan and
        button state treat «a study row is open but no series is ticked» as a
        selected study with an empty list.  Changing that is a separate UX
        decision, not part of this owner move.
        """
        chosen = set(self._selected_series.get(study_uid, ()))
        if selected:
            chosen.add(series_uid)
        else:
            chosen.discard(series_uid)
        self._selected_series[study_uid] = chosen
        known = {uid for uid in known_series_uids if uid}
        if known and chosen >= known:
            self._whole_studies.add(study_uid)
        else:
            self._whole_studies.discard(study_uid)
        return set(chosen)

    def check_state(self, study_uid: str, known_series_uids: Iterable[str]) -> tuple[bool, bool]:
        """``(checked, partial)`` for a study row, given the known series."""
        known = {uid for uid in known_series_uids if uid}
        if known:
            chosen = self._selected_series.get(study_uid) or set()
            if chosen >= known:
                return True, False
            if chosen:
                return False, True
            return False, False
        if study_uid in self._whole_studies:
            return True, False
        return False, False

    def download_plan(
        self,
        known_series: Mapping[str, Sequence[str]],
        *,
        excluded: Collection[str] = (),
    ) -> list[DownloadEntry]:
        """``(study_uid, series_uids)`` pairs for the visible, selected studies.

        ``known_series`` maps a study UID to its cached series (the dialog
        passes only UIDs it knows).  ``excluded`` are studies hidden by the
        current filter: they stay selected but must not be downloaded silently.
        """
        result: list[DownloadEntry] = []
        for study_uid in self.study_uids():
            if not study_uid or study_uid in excluded:
                continue
            known = [uid for uid in known_series.get(study_uid, ()) if uid]
            if study_uid in self._whole_studies:
                # «Whole study»: every series we know about.  While the list is
                # loading the entry carries an empty list — the selection is
                # real and the dialog fetches the list before anything starts.
                uids = known or sorted(self._selected_series.get(study_uid, set()))
            else:
                chosen = self._selected_series.get(study_uid, set())
                uids = [uid for uid in known if uid in chosen] if known else sorted(chosen)
            result.append((study_uid, uids))
        return result
