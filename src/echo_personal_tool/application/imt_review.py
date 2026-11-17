"""Explicit live review lease: a loaded draft never inherits current status."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from echo_personal_tool.application.imt import correct_imt
from echo_personal_tool.domain.models.imt import Boundary, ImtDraft, ImtRefusal, ImtSource


class ImtReview:
    """Own only transient freshness; the document owns historical results."""

    def __init__(self, draft: ImtDraft, *, live: bool = False) -> None:
        self.draft = draft
        self.live = live

    def invalidate(self) -> None:
        self.live = False
        self.draft = replace(self.draft, confirmed=False)

    def revalidate(self, current: ImtSource, image: np.ndarray) -> ImtDraft:
        """Explicit operator action after reload/context change, never automatic."""
        self.invalidate()
        old = self.draft.source
        if (old.study_uid, old.instance_uid, old.frame_index) != (
            current.study_uid,
            current.instance_uid,
            current.frame_index,
        ):
            raise ImtRefusal("stale_draft")
        candidate = replace(self.draft, source=current, confirmed=False)
        self.draft = correct_imt(
            candidate, current, image, lumen_intima=candidate.lumen_intima, media_adventitia=candidate.media_adventitia
        )
        self.live = True
        return self.draft

    def edit(self, current: ImtSource, image: np.ndarray, li: Boundary, ma: Boundary) -> ImtDraft:
        if not self.live:
            raise ImtRefusal("review_required")
        self.draft = correct_imt(self.draft, current, image, lumen_intima=li, media_adventitia=ma)
        return self.draft

    def confirm(self, current: ImtSource) -> ImtDraft:
        if not self.live:
            raise ImtRefusal("review_required")
        self.draft = self.draft.confirm(current)
        return self.draft
