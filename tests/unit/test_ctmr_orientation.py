"""Patient-space orientation labelling for CT/MR stacks (#557)."""

import pytest

from echo_personal_tool.domain.services.ctmr_orientation import (
    orientation_labels,
    slice_plane_label,
)


def test_axial_axes_follow_lps_convention():
    # First vector = increasing column (+X = Left), second = increasing row
    # (+Y = Posterior); normal +Z -> axial.
    assert orientation_labels((1, 0, 0, 0, 1, 0)) == ("L", "P")
    assert slice_plane_label((1, 0, 0, 0, 1, 0)) == "AXIAL"


def test_negative_axes_name_the_opposite_direction():
    assert orientation_labels((-1, 0, 0, 0, -1, 0)) == ("R", "A")
    assert slice_plane_label((-1, 0, 0, 0, -1, 0)) == "AXIAL"


def test_superior_inferior_and_plane_names():
    # Column +X (L), row +Z (S): normal is -Y -> sagittal.
    assert orientation_labels((1, 0, 0, 0, 0, 1)) == ("L", "S")
    assert slice_plane_label((1, 0, 0, 0, 0, 1)) == "SAGITTAL"
    # Column +Y (P), row +X (L): normal is +Z? cross((0,1,0),(1,0,0))=(0,0,-1)
    assert orientation_labels((0, 1, 0, 1, 0, 0)) == ("P", "L")
    assert slice_plane_label((0, 1, 0, 1, 0, 0)) == "AXIAL"


def test_coronal_plane_normal_is_left_right():
    # Column +Y (P), row +Z (S): normal cross((0,1,0),(0,0,1))=(1,0,0) -> coronal.
    assert orientation_labels((0, 1, 0, 0, 0, 1)) == ("P", "S")
    assert slice_plane_label((0, 1, 0, 0, 0, 1)) == "CORONAL"


def test_oblique_vector_gets_no_label_but_plane_may_still_be_named():
    a = 2**-0.5
    assert orientation_labels((a, 0, a, 0, 1, 0)) == ("", "P")
    # The normal is oblique too, so no plane name is invented.
    assert slice_plane_label((a, 0, a, 0, 1, 0)) == ""


@pytest.mark.parametrize("bad", [(1, 0, 0), (1, 0, 0, 0, 1, 0, 0), ()])
def test_invalid_orientation_rejected(bad):
    with pytest.raises(ValueError):
        orientation_labels(bad)
    with pytest.raises(ValueError):
        slice_plane_label(bad)
