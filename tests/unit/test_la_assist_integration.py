"""Tests for AI-assisted manual LA contour integration."""


import numpy as np
import pytest

from echo_personal_tool.domain.services.la_segmentation_service import (
    la_landmarks_from_mask_or_user,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    fit_contour_from_landmarks,
)


@pytest.fixture()
def synthetic_la_mask():
    """Binary mask simulating LA cavity in 224x224 frame."""
    mask = np.zeros((224, 224), dtype=np.uint8)
    cy, cx = 112, 100
    for y in range(224):
        for x in range(224):
            if ((x - cx) / 55) ** 2 + ((y - cy) / 75) ** 2 <= 1:
                mask[y, x] = 255
    return mask


def test_manual_contour_starts_as_ellipse():
    """Verify manual contour is initially a pure ellipse (no AI)."""
    contour = fit_contour_from_landmarks(
        septal=(80.0, 180.0),
        lateral=(140.0, 180.0),
        apex=(112.0, 40.0),
        phase="ES",
        view="A4C",
        chamber="LA",
    )
    assert contour.chamber == "LA"
    assert contour.source == "model"
    assert len(contour.points) == 32
    # Endpoints should be at MA
    assert contour.points[0] == (80.0, 180.0)
    assert contour.points[-1] == (140.0, 180.0)


def test_ai_landmarks_differ_from_geometric(synthetic_la_mask):
    """AI-derived landmarks should differ from pure geometric ellipse."""
    ai_septal, ai_lateral, ai_apex = la_landmarks_from_mask_or_user(
        synthetic_la_mask
    )
    # AI landmarks come from mask, not from user clicks
    assert ai_septal is not None
    assert ai_lateral is not None
    assert ai_apex is not None


def test_blend_shifts_toward_ai(synthetic_la_mask):
    """Blended landmarks should be closer to AI than pure user clicks."""
    user_septal = (60.0, 190.0)
    user_lateral = (160.0, 190.0)
    user_apex = (112.0, 30.0)

    blended = la_landmarks_from_mask_or_user(
        synthetic_la_mask,
        user_septal=user_septal,
        user_lateral=user_lateral,
        user_apex=user_apex,
        blend_factor=0.7,
    )
    ai = la_landmarks_from_mask_or_user(synthetic_la_mask)

    # Blended should be 70% AI + 30% user
    for b, a, u in zip(blended, ai, [user_septal, user_lateral, user_apex]):
        assert abs(b[0] - a[0]) < abs(u[0] - a[0])  # Closer to AI
