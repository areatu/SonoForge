"""View-recognition orchestration (domain service, no IO).

Pure coordination between a :class:`~echo_personal_tool.domain.ports.IViewRecognizer`
and the rest of the application: it turns a clip into a :class:`RecognizedView`
and exposes the coarse category / confidence that the UI (step 4) will consume.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from echo_personal_tool.domain.models.view_recognition import RecognizedView
from echo_personal_tool.domain.ports import IViewRecognizer


class ViewRecognitionService:
    """Run a view classifier and interpret its result.

    The service is deliberately thin: it does not know how the recognizer works,
    only that it returns a :class:`RecognizedView` for a stack of frames.
    """

    def __init__(self, recognizer: IViewRecognizer) -> None:
        self._recognizer = recognizer

    def recognize(self, frames: Sequence[np.ndarray]) -> RecognizedView:
        """Classify ``frames`` (a cine clip) into a recognised view + confidence."""
        return self._recognizer.recognize(frames)

    def recognize_clip(self, clip: np.ndarray) -> RecognizedView:
        """Convenience wrapper for an already-stacked ``(N, H, W[, C])`` clip."""
        frames = [clip[i] for i in range(clip.shape[0])]
        return self.recognize(frames)

    def describe(self, frames: Sequence[np.ndarray]) -> dict[str, object]:
        """Return a small, UI-ready summary of the recognition result."""
        result = self.recognize(frames)
        return {
            "view": result.view,
            "confidence": result.confidence,
            "category": result.category,
            "confident": result.is_confident,
        }
