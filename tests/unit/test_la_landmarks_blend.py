"""Tests for LA landmark blending (AI mask + user clicks)."""

import numpy as np
import pytest

from echo_personal_tool.domain.services.la_segmentation_service import (
    la_landmarks_from_mask_or_user,
)


@pytest.fixture()
def dummy_mask():
    """Synthetic LA mask: ellipse in center of 224x224 image."""
    mask = np.zeros((224, 224), dtype=bool)
    cy, cx = 112, 112
    for y in range(224):
        for x in range(224):
            if ((x - cx) / 50) ** 2 + ((y - cy) / 80) ** 2 <= 1:
                mask[y, x] = True
    return mask.astype(np.uint8) * 255


def test_pure_ai_landmarks(dummy_mask):
    septal, lateral, apex = la_landmarks_from_mask_or_user(dummy_mask)
    assert septal is not None
    assert lateral is not None
    assert apex is not None
    # Septal should be left of lateral
    assert septal[0] < lateral[0]
    # Apex should be above MA (smaller y = superior in image coords)
    assert apex[1] < septal[1]


def test_blended_landmarks(dummy_mask):
    user_septal = (80.0, 180.0)
    user_lateral = (140.0, 180.0)
    user_apex = (112.0, 40.0)
    septal, lateral, apex = la_landmarks_from_mask_or_user(
        dummy_mask,
        user_septal=user_septal,
        user_lateral=user_lateral,
        user_apex=user_apex,
        blend_factor=0.5,
    )
    # Blended result should be between AI and user
    ai_septal, ai_lateral, ai_apex = la_landmarks_from_mask_or_user(dummy_mask)
    # Check that blended is different from pure user
    assert septal[0] != user_septal[0]
    # Check that blended is different from pure AI
    assert septal[0] != ai_septal[0]


def test_blend_factor_zero_uses_user(dummy_mask):
    """blend_factor=0 should return pure user landmarks."""
    user_septal = (80.0, 180.0)
    user_lateral = (140.0, 180.0)
    user_apex = (112.0, 40.0)
    septal, lateral, apex = la_landmarks_from_mask_or_user(
        dummy_mask,
        user_septal=user_septal,
        user_lateral=user_lateral,
        user_apex=user_apex,
        blend_factor=0.0,
    )
    assert septal == user_septal
    assert lateral == user_lateral
    assert apex == user_apex


def test_blend_factor_one_uses_ai(dummy_mask):
    """blend_factor=1.0 should return pure AI landmarks."""
    user_septal = (80.0, 180.0)
    user_lateral = (140.0, 180.0)
    user_apex = (112.0, 40.0)
    septal, lateral, apex = la_landmarks_from_mask_or_user(
        dummy_mask,
        user_septal=user_septal,
        user_lateral=user_lateral,
        user_apex=user_apex,
        blend_factor=1.0,
    )
    ai_septal, ai_lateral, ai_apex = la_landmarks_from_mask_or_user(dummy_mask)
    assert septal == ai_septal
    assert lateral == ai_lateral
    assert apex == ai_apex
