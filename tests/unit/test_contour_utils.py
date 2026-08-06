import numpy as np

from echo_personal_tool.domain.services.contour_utils import resample_contour


def test_resample_contour_fixed_count():
    pts = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]], dtype=np.float64)
    out = resample_contour(pts, n_points=128)
    assert out.shape == (128, 2)


def test_resample_contour_deterministic():
    pts = np.array([[0.0, 0.0], [5.0, 5.0], [10.0, 0.0]], dtype=np.float64)
    a = resample_contour(pts, 64)
    b = resample_contour(pts, 64)
    np.testing.assert_array_equal(a, b)
