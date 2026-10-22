import numpy as np

from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column


def test_extract_horizontal_line_from_uniform_frame() -> None:
    frame = np.full((100, 100), 128, dtype=np.uint8)
    col = extract_mmode_column(frame, (10.0, 50.0), (90.0, 50.0), num_samples=64)
    assert col.shape == (64,)
    assert col.dtype == np.uint8
    np.testing.assert_array_equal(col, 128)


def test_extract_vertical_line_gradient() -> None:
    frame = np.zeros((100, 100), dtype=np.uint8)
    for y in range(100):
        frame[y, :] = y
    col = extract_mmode_column(frame, (50.0, 0.0), (50.0, 99.0), num_samples=100)
    assert col.shape == (100,)
    assert col[0] == 0
    assert col[-1] == 99


def test_extract_diagonal_line() -> None:
    frame = np.zeros((100, 100), dtype=np.uint8)
    for i in range(100):
        frame[i, i] = 255
    col = extract_mmode_column(frame, (0.0, 0.0), (99.0, 99.0), num_samples=100)
    assert col.shape == (100,)
    assert col[0] == 255
    assert col[-1] == 255


def test_extract_preserves_dtype_uint16() -> None:
    frame = np.full((64, 64), 1000, dtype=np.uint16)
    col = extract_mmode_column(frame, (10.0, 32.0), (50.0, 32.0), num_samples=32)
    assert col.dtype == np.uint16
    np.testing.assert_array_equal(col, 1000)


def test_extract_short_line_minimum_samples() -> None:
    frame = np.full((64, 64), 200, dtype=np.uint8)
    col = extract_mmode_column(frame, (30.0, 30.0), (35.0, 30.0), num_samples=16)
    assert col.shape == (16,)


def test_extract_out_of_bounds_clamps() -> None:
    frame = np.full((64, 64), 50, dtype=np.uint8)
    col = extract_mmode_column(frame, (-10.0, 32.0), (70.0, 32.0), num_samples=32)
    assert col.shape == (32,)
    assert all(v == 50 for v in col)
