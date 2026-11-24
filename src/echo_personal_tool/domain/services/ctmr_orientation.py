"""Patient-space orientation labels for classic CT/MR slices (#557).

DICOM patient coordinates are LPS (Left, Posterior, Superior):
``+X`` is patient Left, ``-X`` Right, ``+Y`` Posterior, ``-Y`` Anterior,
``+Z`` Superior (head), ``-Z`` Inferior (feet).

This module maps the two in-plane direction vectors of an
``ImageOrientationPatient`` tuple onto the patient axes they follow and names
the slice plane from their cross product.  It is deliberately Qt-free and
pixel-free so the labelling rule can be tested without a window.

The vector order here follows the convention already used by
:meth:`echo_personal_tool.domain.models.ctmr_stack.SliceGeometry.patient_point`:
the first three values describe increasing *column*, the last three increasing
*row*.  Labels are therefore reported as ``(column, row)``.

A slice whose vectors do not align with a patient axis (a genuinely oblique
acquisition) yields empty labels instead of a guessed one.
"""

from __future__ import annotations

from math import sqrt

Vector3 = tuple[float, float, float]
Orientation = tuple[float, float, float, float, float, float]

#: Patient-axis direction cosines in LPS, paired with the label the direction
#: points *towards*.  ``+X -> L``, ``-X -> R``, ``+Y -> P``, ``-Y -> A``,
#: ``+Z -> S`` (superior), ``-Z -> I`` (inferior).
_AXES: tuple[tuple[Vector3, str], ...] = (
    ((1.0, 0.0, 0.0), "L"),
    ((-1.0, 0.0, 0.0), "R"),
    ((0.0, 1.0, 0.0), "P"),
    ((0.0, -1.0, 0.0), "A"),
    ((0.0, 0.0, 1.0), "S"),
    ((0.0, 0.0, -1.0), "I"),
)

#: Plane named by the normal that is orthogonal to it.
_PLANES: tuple[tuple[Vector3, str], ...] = (
    ((0.0, 0.0, 1.0), "AXIAL"),
    ((0.0, 0.0, -1.0), "AXIAL"),
    ((1.0, 0.0, 0.0), "CORONAL"),
    ((-1.0, 0.0, 0.0), "CORONAL"),
    ((0.0, 1.0, 0.0), "SAGITTAL"),
    ((0.0, -1.0, 0.0), "SAGITTAL"),
)

#: Direction-cosine vectors must be unit length; a near-axis match is one whose
#: cosine with a patient axis exceeds this threshold.
_AXIS_ATOL = 1e-3


def _normalise(vector: Vector3) -> Vector3:
    norm = sqrt(sum(component * component for component in vector))
    if norm <= 0.0:
        return vector
    return (vector[0] / norm, vector[1] / norm, vector[2] / norm)


def _axis_label(vector: Vector3) -> str:
    unit = _normalise(vector)
    for axis, label in _AXES:
        if abs(sum(a * b for a, b in zip(unit, axis, strict=True)) - 1.0) <= _AXIS_ATOL:
            return label
    return ""


def orientation_labels(orientation: Orientation) -> tuple[str, str]:
    """Return the patient-axis label of the column and row direction.

    The first element labels increasing column, the second increasing row.
    An empty string means the vector is oblique and does not follow a patient
    axis, so no label is invented for it.
    """
    if len(orientation) != 6:
        raise ValueError("invalid_orientation")
    column = _axis_label(orientation[:3])
    row = _axis_label(orientation[3:])
    return column, row


def slice_plane_label(orientation: Orientation) -> str:
    """Name the plane of the slice from the normal ``cross(column, row)``."""
    if len(orientation) != 6:
        raise ValueError("invalid_orientation")
    col = orientation[:3]
    row = orientation[3:]
    normal = (
        col[1] * row[2] - col[2] * row[1],
        col[2] * row[0] - col[0] * row[2],
        col[0] * row[1] - col[1] * row[0],
    )
    unit = _normalise(normal)
    for axis, label in _PLANES:
        if abs(sum(a * b for a, b in zip(unit, axis, strict=True)) - 1.0) <= _AXIS_ATOL:
            return label
    return ""
