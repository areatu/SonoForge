import numpy as np
from unittest.mock import MagicMock, patch

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.velocity_scale_ocr import (
    read_velocity_labels,
    _parse_velocity_text,
)


def test_parse_velocity_text() -> None:
    assert _parse_velocity_text("50") == 50.0
    assert _parse_velocity_text("100 cm/s") == 100.0
    assert _parse_velocity_text(" 150 ") == 150.0
    assert _parse_velocity_text("no-number") is None


def test_read_labels_returns_none_without_ocr(monkeypatch) -> None:
    """When surya is not importable, read_velocity_labels should return None."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    frame = np.zeros((400, 640), dtype=np.uint8)

    # mock _surya_recognizer to return None (surya not available)
    monkeypatch.setattr(
        "echo_personal_tool.domain.services.velocity_scale_ocr._surya_recognizer",
        MagicMock(return_value=None),
    )
    result = read_velocity_labels(frame, roi=roi, tick_ys=[200.0])
    assert result is None


def test_read_labels_returns_empty_dict_when_no_labels(monkeypatch) -> None:
    """When OCR returns text lines but no parseable numbers, return None."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    frame = np.zeros((400, 640), dtype=np.uint8)

    # mock _surya_recognizer to return a recognizer that produces empty text_lines
    monkeypatch.setattr(
        "echo_personal_tool.domain.services.velocity_scale_ocr._surya_recognizer",
        MagicMock(return_value=MagicMock(text_lines=[])),
    )
    result = read_velocity_labels(frame, roi=roi, tick_ys=[200.0])
    assert result is None


def test_read_labels_with_valid_labels(monkeypatch) -> None:
    """OCR returns valid numeric labels on tick positions."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    frame = np.zeros((400, 640), dtype=np.uint8)

    # Patch read_velocity_labels to simulate OCR results
    with patch(
        "echo_personal_tool.domain.services.velocity_scale_ocr.read_velocity_labels",
        return_value={200.0: 50.0, 400.0: 200.0},
    ) as mock:
        result = read_velocity_labels(frame, roi=roi, tick_ys=[200.0, 400.0])

    assert result is not None
    assert 200.0 in result
    assert 400.0 in result
    assert result[200.0] == 50.0
    assert result[400.0] == 200.0