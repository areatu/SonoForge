"""Build Samsung tick calibration from training data."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from echo_personal_tool.infrastructure.samsung_tick_detector import detect_ticks

logger = logging.getLogger(__name__)

_CALIBRATION_FILE = Path(__file__).parent / "samsung_tick_calibration.json"


@dataclass
class TickMeasurement:
    """Single frequency measurement."""
    frequency_hz: float
    tick_spacing_px: float
    tick_count: int
    confidence: float


@dataclass
class SamsungTickCalibration:
    """Samsung device tick calibration."""
    device_model: str
    k_constant: float
    r_squared: float
    image_height_ref: int
    measured_points: list[TickMeasurement]


def build_calibration(
    training_data: list[tuple[float, np.ndarray]],
    device_model: str = "RS85-RUS",
) -> SamsungTickCalibration:
    """Build calibration from training data.

    Args:
        training_data: List of (frequency_hz, pixel_array) tuples.
        device_model: Samsung device model name.

    Returns:
        SamsungTickCalibration with K constant and quality metrics.

    Raises:
        ValueError: If fewer than 2 valid measurements.
    """
    measurements: list[TickMeasurement] = []

    for freq, pixel_array in training_data:
        result = detect_ticks(pixel_array)
        if result.confidence > 0.3 and result.spacing_px > 0:
            measurements.append(TickMeasurement(
                frequency_hz=freq,
                tick_spacing_px=result.spacing_px,
                tick_count=len(result.tick_positions),
                confidence=result.confidence,
            ))

    if len(measurements) < 2:
        raise ValueError(f"Insufficient valid measurements: {len(measurements)}")

    # Fit K = spacing * frequency for each point
    k_values = [m.tick_spacing_px * m.frequency_hz for m in measurements]
    k_constant = float(np.median(k_values))  # Median is robust to outliers

    # Compute R² for fit quality
    k_array = np.array(k_values)
    k_mean = float(k_array.mean())
    ss_res = float(((k_array - k_constant) ** 2).sum())
    ss_tot = float(((k_array - k_mean) ** 2).sum())
    if ss_tot > 0:
        r_squared = 1.0 - (ss_res / ss_tot)
    else:
        # Zero variance: perfect fit if residual is also zero, otherwise undefined
        r_squared = 1.0 if ss_res == 0 else 0.0

    # Get reference image height from first measurement's array
    image_height_ref = int(training_data[0][1].shape[0])

    return SamsungTickCalibration(
        device_model=device_model,
        k_constant=k_constant,
        r_squared=r_squared,
        image_height_ref=image_height_ref,
        measured_points=measurements,
    )


def save_calibration(calibration: SamsungTickCalibration) -> None:
    """Save calibration to JSON file."""
    data = {
        "device_model": calibration.device_model,
        "k_constant": calibration.k_constant,
        "r_squared": calibration.r_squared,
        "image_height_ref": calibration.image_height_ref,
        "measured_points": [asdict(m) for m in calibration.measured_points],
    }
    _CALIBRATION_FILE.write_text(json.dumps(data, indent=2))
    logger.info("Saved calibration to %s", _CALIBRATION_FILE)


def load_calibration() -> SamsungTickCalibration | None:
    """Load calibration from JSON file. Returns None if missing or invalid."""
    if not _CALIBRATION_FILE.exists():
        return None
    try:
        data = json.loads(_CALIBRATION_FILE.read_text())
        measurements = [TickMeasurement(**m) for m in data["measured_points"]]
        return SamsungTickCalibration(
            device_model=data["device_model"],
            k_constant=data["k_constant"],
            r_squared=data["r_squared"],
            image_height_ref=data["image_height_ref"],
            measured_points=measurements,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load calibration: %s", e)
        return None