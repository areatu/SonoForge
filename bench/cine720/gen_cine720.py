"""Generate synthetic 1280x720 multiframe DICOM cines for playback benchmarking.

Variants:
  rgb_raw   - RGB 8-bit uncompressed (Explicit VR Little Endian)  - typical US colour export
  mono_raw  - MONOCHROME2 16-bit uncompressed                     - typical B-mode raw
  jpeg      - RGB JPEG baseline (1.2.840.10008.1.2.4.50)          - typical US vendor export
  jp2k      - RGB JPEG2000 lossless (1.2.840.10008.1.2.4.90)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pydicom
from pydicom.encaps import encapsulate
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

ROWS, COLS = 720, 1280


def make_frames(n: int, *, colour: bool = True, seed: int = 7) -> np.ndarray:
    """Ultrasound-like moving content: sector gradient + speckle + moving cavity."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:ROWS, 0:COLS].astype(np.float32)
    base = (yy / ROWS) * 90.0 + (xx / COLS) * 30.0
    # fixed speckle texture (correlated between frames, like real tissue)
    speckle = rng.normal(0.0, 18.0, (ROWS, COLS)).astype(np.float32)
    speckle = cv2.GaussianBlur(speckle, (0, 0), 1.6)
    frames = []
    for i in range(n):
        phase = 2.0 * np.pi * i / max(1, n)
        img = base + speckle + 12.0 * np.sin(phase)
        cx = COLS * 0.5 + COLS * 0.06 * np.cos(phase)
        cy = ROWS * 0.45 + ROWS * 0.05 * np.sin(phase)
        rx = COLS * (0.16 + 0.03 * np.cos(phase))
        ry = ROWS * (0.22 + 0.04 * np.cos(phase))
        mask = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
        img[mask] = 20.0 + 6.0 * np.sin(phase)
        # bright annulus ring
        ring = (mask & ~(((xx - cx) / (rx * 0.86)) ** 2 + ((yy - cy) / (ry * 0.86)) ** 2 <= 1.0))
        img[ring] = 210.0
        g = np.clip(img, 0, 255).astype(np.uint8)
        if colour:
            bgr = cv2.merge([g, g, g])
            # colour Doppler wedge (highly saturated) - realistic for echo cines
            wedge = np.zeros((ROWS, COLS), np.uint8)
            cv2.rectangle(wedge, (int(COLS * 0.55), int(ROWS * 0.30)), (int(COLS * 0.85), int(ROWS * 0.75)), 255, -1)
            bgr[wedge > 0, 2] = np.clip(g[wedge > 0].astype(int) + 40, 0, 255).astype(np.uint8)
            bgr[wedge > 0, 0] = (g[wedge > 0] * 0.4).astype(np.uint8)
            frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        else:
            frames.append(g)
    return np.stack(frames)


def _base_ds(n: int, *, samples: int, bits: int, pi: str) -> pydicom.Dataset:
    ds = pydicom.Dataset()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"  # US Multiframe Image
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "US"
    ds.Rows = ROWS
    ds.Columns = COLS
    ds.NumberOfFrames = n
    ds.SamplesPerPixel = samples
    ds.PhotometricInterpretation = pi
    ds.BitsAllocated = bits
    ds.BitsStored = bits
    ds.HighBit = bits - 1
    ds.PixelRepresentation = 0
    ds.PlanarConfiguration = 0
    ds.FrameTime = 33  # ~30 fps
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds


def write(path: Path, variant: str, n: int) -> None:
    colour = variant != "mono_raw"
    frames = make_frames(n, colour=colour)
    if variant == "rgb_raw":
        ds = _base_ds(n, samples=3, bits=8, pi="RGB")
        ds.PixelData = frames.astype(np.uint8).tobytes()
        ts = ExplicitVRLittleEndian
    elif variant == "mono_raw":
        g = (frames if frames.ndim == 3 else frames[..., None]).reshape(n, ROWS, COLS, -1)[..., 0]
        g = g.astype(np.uint16) * 257
        ds = _base_ds(n, samples=1, bits=16, pi="MONOCHROME2")
        ds.PixelData = g.tobytes()
        ts = ExplicitVRLittleEndian
    elif variant == "jpeg":
        blobs = [cv2.imencode(".jpg", cv2.cvtColor(f, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
                 for f in frames]
        ds = _base_ds(n, samples=3, bits=8, pi="YBR_FULL_422")
        ds.PixelData = encapsulate(blobs, has_bot=True)
        ts = "1.2.840.10008.1.2.4.50"
    elif variant == "jp2k":
        import openjpeg
        blobs = []
        for f in frames:
            arr = np.ascontiguousarray(f)
            blobs.append(openjpeg.encode(arr, compression_ratios=[20.0])[0].data
                         if hasattr(openjpeg, "encode") else b"")
        ds = _base_ds(n, samples=3, bits=8, pi="RGB")
        ds.PixelData = encapsulate(blobs, has_bot=True)
        ts = "1.2.840.10008.1.2.4.90"
    else:
        raise SystemExit(f"unknown variant {variant}")
    ds.file_meta = pydicom.Dataset()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ts
    ds.file_meta.ImplementationClassUID = generate_uid()
    ds.save_as(str(path), enforce_file_format=True)
    print(f"{path}  {path.stat().st_size/1e6:.2f} MB  variant={variant} frames={n}")


if __name__ == "__main__":
    import tempfile

    default_dir = Path(os.environ.get("CINE720_DIR", Path(tempfile.gettempdir()) / "sonoforge-cine720"))
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dir
    out.mkdir(parents=True, exist_ok=True)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    variants = sys.argv[3].split(",") if len(sys.argv) > 3 else ["rgb_raw", "mono_raw", "jpeg"]
    for v in variants:
        write(out / f"cine720_{v}_{n}.dcm", v, n)
