"""Exploratory tests: hypothesis-based fuzzing for DICOM UIDs, pixel spacing, measurements, contours."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from echo_personal_tool.domain.calculations.body_surface import bsa_du_bois_m2
from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.calculations.planimeter import closed_polygon_area_cm2
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.linear_measurement import (
    LinearMeasurement,
    format_length_mm,
    pixel_to_mm_length,
)
from echo_personal_tool.infrastructure.dicom_uid_validator import (
    safe_uid_path_component,
    validate_dicom_uid,
)

# ── DICOM UID fuzzing ──────────────────────────────────────────────

valid_uid_chars = st.text(
    alphabet=st.sampled_from(list("0123456789")),
    min_size=1,
    max_size=64,
)


@given(uid=valid_uid_chars)
@settings(max_examples=200)
def test_valid_dicom_uid_accepted(uid: str) -> None:
    """UIDs containing only digits are always valid."""
    dotted = ".".join(uid[i : i + 3] for i in range(0, len(uid), 3))
    assert validate_dicom_uid(dotted) is True


@given(
    base=st.integers(min_value=1, max_value=10**18),
    suffix=st.text(
        alphabet=st.sampled_from(list("0123456789.") + ["a", "z", "!", " "]),
        min_size=1,
        max_size=10,
    ),
)
@settings(max_examples=100)
def test_invalid_dicom_uid_rejected(base: int, suffix: str) -> None:
    """UIDs with non-digit characters are rejected."""
    uid = f"{base}.{suffix}"
    result = validate_dicom_uid(uid)
    # If suffix contains any non-digit, non-dot char, must be False
    has_bad_char = any(c not in "0123456789." for c in uid)
    if has_bad_char:
        assert result is False


@given(uid=valid_uid_chars)
@settings(max_examples=100)
def test_safe_uid_path_component_returns_string(uid: str) -> None:
    """safe_uid_path_component returns the UID string for valid inputs."""
    dotted = ".".join(uid[i : i + 3] for i in range(0, len(uid), 3))
    result = safe_uid_path_component(dotted)
    assert result == dotted


def test_empty_uid_rejected() -> None:
    """Empty UID is rejected."""
    assert validate_dicom_uid("") is False


def test_uid_with_letters_rejected() -> None:
    """UID with letters is rejected."""
    assert validate_dicom_uid("1.2.3.abc") is False


def test_uid_with_spaces_rejected() -> None:
    """UID with spaces is rejected."""
    assert validate_dicom_uid("1.2.3 4") is False


# ── Pixel spacing fuzzing ──────────────────────────────────────────

@given(
    row_spacing=st.floats(min_value=0.01, max_value=5.0),
    col_spacing=st.floats(min_value=0.01, max_value=5.0),
)
@settings(max_examples=200)
def test_pixel_to_mm_length_never_negative(
    row_spacing: float, col_spacing: float
) -> None:
    """pixel_to_mm_length always returns a non-negative value for valid inputs."""
    length = pixel_to_mm_length(
        pixel_length=100.0,
        angle_degrees=45.0,
        pixel_spacing=(row_spacing, col_spacing),
    )
    assert length >= 0.0
    assert math.isfinite(length)


@given(
    pixel_length=st.floats(min_value=0.0, max_value=10000.0),
    row_spacing=st.floats(min_value=0.01, max_value=2.0),
    col_spacing=st.floats(min_value=0.01, max_value=2.0),
)
@settings(max_examples=200)
def test_pixel_to_mm_length_monotonic_with_pixel_length(
    pixel_length: float, row_spacing: float, col_spacing: float
) -> None:
    """Doubling pixel_length should at least not decrease mm result."""
    angle = 0.0
    spacing = (row_spacing, col_spacing)
    l1 = pixel_to_mm_length(pixel_length, angle, spacing)
    l2 = pixel_to_mm_length(pixel_length * 2, angle, spacing)
    assert l2 >= l1 - 1e-10


# ── Measurement value fuzzing ──────────────────────────────────────

@given(
    mm_value=st.floats(min_value=0.1, max_value=500.0),
    unit=st.sampled_from(["mm", "cm"]),
)
@settings(max_examples=100)
def test_format_length_mm_always_returns_string(mm_value: float, unit: str) -> None:
    """format_length_mm always returns a non-empty string."""
    result = format_length_mm(mm_value, unit)
    assert isinstance(result, str)
    assert len(result) > 0
    assert unit in result


@given(
    label=st.text(min_size=1, max_size=20, alphabet=st.sampled_from(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))),
    pixel_length=st.floats(min_value=0.0, max_value=10000.0),
    mm_length=st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=500.0),
    ),
)
@settings(max_examples=100)
def test_linear_measurement_display_text_never_raises(
    label: str, pixel_length: float, mm_length: float | None
) -> None:
    """LinearMeasurement.display_text never raises for valid inputs."""
    m = LinearMeasurement(
        label=label,
        pixel_length=pixel_length,
        millimeter_length=mm_length,
    )
    text = m.display_text()
    assert isinstance(text, str)
    assert label in text or "px" in text or "mm" in text


# ── Contour coordinate fuzzing ─────────────────────────────────────

@given(
    n_points=st.integers(min_value=3, max_value=50),
    x_range=st.floats(min_value=0.0, max_value=500.0),
    y_range=st.floats(min_value=0.0, max_value=500.0),
)
@settings(max_examples=100)
def test_contour_area_always_positive_for_closed_polygon(
    n_points: int, x_range: float, y_range: float
) -> None:
    """Planimeter area is always positive for a valid closed contour with >= 3 points."""
    points = []
    for i in range(n_points):
        angle = 2 * math.pi * i / n_points
        x = 100 + x_range * math.cos(angle)
        y = 100 + y_range * math.sin(angle)
        points.append((x, y))

    contour = Contour(phase="ed", view="A4C", chamber="LV", points=points)
    area = closed_polygon_area_cm2(contour, pixel_spacing=(0.3, 0.3))
    # Area should be positive for a valid polygon
    assert area is None or area > 0.0


def test_contour_with_insufficient_points() -> None:
    """Contour with fewer than 3 points returns None area."""
    contour = Contour(phase="ed", view="A4C", chamber="LV", points=[(0, 0), (1, 1)])
    area = closed_polygon_area_cm2(contour, pixel_spacing=(0.3, 0.3))
    assert area is None
