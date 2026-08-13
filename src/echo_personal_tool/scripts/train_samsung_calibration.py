"""Train Samsung tick calibration from renamed DICOM files.

Empirical model (validated on the RS85 training set): the time-axis ruler
spacing is LINEAR in sweep frequency, ``spacing_px = frequency_hz / 5``,
so ``k_constant = 5.0`` (Hz per pixel). This script loads "PW <N> Hz.dcm" and
"CW <N> Hz.dcm" files, detects tick spacing, fits the linear model and writes
``samsung_tick_calibration.json``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pydicom

from echo_personal_tool.infrastructure.samsung_calibration_builder import (
    build_calibration,
    save_calibration,
)


def _parse_frequency(name: str) -> float | None:
    """Extract sweep frequency from a filename like 'PW 60 Hz' or 'CW 120 Hz'."""
    match = re.fullmatch(r"(PW|CW)\s+(\d+)\s*Hz", name)
    if match is None:
        return None
    return float(match.group(2))


def load_dicom_pixels(path: Path) -> object:
    """Load DICOM file and return RGB pixel array."""
    return pydicom.dcmread(str(path)).pixel_array


def main() -> None:
    data_dir = Path("/home/areatu/ECHO2026_src/New Folder2")

    training_data: list[tuple[float, object]] = []
    for dcm_path in sorted(data_dir.glob("*.dcm")):
        freq = _parse_frequency(dcm_path.stem)
        if freq is None:
            continue
        pixels = load_dicom_pixels(dcm_path)
        training_data.append((freq, pixels))
        print(f"Loaded {dcm_path.stem}: {freq:.0f} Hz")

    print(f"\nLoaded {len(training_data)} training files")

    calibration = build_calibration(training_data)  # type: ignore[arg-type]

    print("\nCalibration results:")
    print(f"  k_constant: {calibration.k_constant:.3f} Hz/px")
    print(f"  R²: {calibration.r_squared:.4f}")
    print(f"  image_height_ref: {calibration.image_height_ref}")
    print(f"  Measurements: {len(calibration.measured_points)}")
    for m in calibration.measured_points:
        print(f"    {m.frequency_hz:6.0f} Hz: {m.tick_spacing_px:6.2f} px (n={m.tick_count}, conf={m.confidence:.2f})")

    save_calibration(calibration)
    print("\nSaved to samsung_tick_calibration.json")


if __name__ == "__main__":
    main()
