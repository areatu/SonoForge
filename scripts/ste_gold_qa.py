#!/usr/bin/env python3
"""Headless STE QA on gold clips with AI-corrected contours.

Replays the exact worker pipeline (sequential tracking, physiology_prior off,
relaxed wall clamps) on a gold clip and measures, against the true ES
endocardial contour:

  * per-frame NCC and % valid kernels over the ED..ES window,
  * at ES: fraction of kernels inside the true ES wall band, inside the
    cavity (inward of ES endo), and outside the epicardium (outward of the
    ES endo inflated by the wall thickness),
  * how far (mm) the outermost "epi-layer" kernels sit relative to the true
    ES wall.

Usage: python scripts/ste_gold_qa.py <gold_dcm> <gold_json> [clip_uid]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
from echo_personal_tool.domain.models.speckle import SpeckleConfig
from echo_personal_tool.domain.services.myocardial_zone import create_myocardial_zone
from echo_personal_tool.infrastructure.dicom_session import DicomSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _gray(f):
    return np.mean(f[..., :3], axis=2).astype(np.uint8) if f.ndim == 3 else f.astype(np.uint8)


def _poly(points) -> np.ndarray:
    pts = np.array(points, dtype=np.float64)
    # close the polygon for inside/outside tests
    if len(pts) > 1 and not np.allclose(pts[0], pts[-1]):
        pts = np.concatenate([pts, pts[:1]], axis=0)
    return pts


def _load_gold_for_clip(json_path: Path, dcm_path: Path):
    """Pick gold frames belonging to the given DICOM clip.

    ``instance_path`` entries in older gold files are stale (files moved), so
    match on SOPInstanceUID when the path does not resolve to the file.
    """
    import pydicom

    ds = pydicom.dcmread(dcm_path, stop_before_pixels=True, force=True)
    sop_uid = str(ds.get("SOPInstanceUID", ""))
    data = json.loads(json_path.read_text())
    out = {}
    for frame in data.get("frames", []):
        ip = frame.get("instance_path")
        path_ok = bool(ip) and Path(ip).resolve() == dcm_path.resolve()
        uid_ok = bool(sop_uid) and frame.get("sop_instance_uid") == sop_uid
        if path_ok or uid_ok:
            out.setdefault(frame["phase"].upper(), []).append(frame)
    return out


def _inside_fraction(points: np.ndarray, poly: np.ndarray) -> float:
    from matplotlib.path import Path as MplPath  # noqa: N813

    path = MplPath(poly)
    inside = path.contains_points(points)
    return float(np.mean(inside))


def main() -> None:
    dcm = Path(sys.argv[1]).resolve()
    gold = Path(sys.argv[2]).resolve()
    by_phase = _load_gold_for_clip(gold, dcm)
    eds = sorted(by_phase.get("ED", []), key=lambda f: f["frame_index"])
    ess = sorted(by_phase.get("ES", []), key=lambda f: f["frame_index"])
    if not eds or not ess:
        print("no ED/ES frames for this clip in gold json")
        return
    ed_g, es_g = eds[0], ess[0]
    ed_fr, es_fr = int(ed_g["frame_index"]), int(es_g["frame_index"])
    print(f"clip: {dcm.name}  ED frame={ed_fr}  ES frame={es_fr}")

    session = DicomSession()
    session.open(dcm)
    raw = session.decode_all_frames()
    session.release_heavy()
    frames = np.stack([_gray(f) for f in raw])
    print(f"frames: {frames.shape}  spacing mm/px: {ed_g.get('pixel_spacing_mm')}")

    spacing = ed_g.get("pixel_spacing_mm") or (0.3, 0.3)
    endo = np.array(ed_g["points"], dtype=np.float64)
    # replicate the app: epicardium derived from the ED endo + wall thickness
    zone = create_myocardial_zone(endo, spacing, 8.0, epi_points=None)

    worker = SpeckleTrackingWorker(
        frames=frames,
        zone=zone,
        pixel_spacing=tuple(spacing),
        frame_time_ms=33.3,
        config=SpeckleConfig.preset_standard(),
        config_preset="standard",
        manual_ed=ed_fr,
        manual_es=es_fr,
    )
    finished, errors = [], []
    worker.signals.finished.connect(lambda r: finished.append(r))
    worker.signals.error.connect(lambda m: errors.append(m))
    worker.run()
    if errors or not finished:
        print("ERROR:", errors)
        return
    res = finished[0]
    es_fr_local = es_fr - res.tracking_window_start
    pos = res.tracked_positions_all  # (n_frames, n_kernels, 2)
    ncc = res.ncc_all_frames
    lo, hi = res.tracking_window_start, res.tracking_window_end

    # per-frame QC over the systolic window
    print("\n-- per-frame over ED..ES window --")
    for t in range(lo, hi + 1):
        v = np.isfinite(ncc[t]) & (ncc[t] >= res.ncc_threshold)
        print(
            f"  frame {t:3d}: NCC mean={np.nanmean(ncc[t]):.3f}  "
            f"valid={np.mean(v)*100:4.0f}%"
        )

    # containment at ES against the TRUE ES endo + thickness-based epi
    es_endo = _poly(es_g["points"])
    es_epi = _poly(
        create_myocardial_zone(np.array(es_g["points"], dtype=np.float64), spacing, 8.0).epi_points
    )
    es_pos = pos[es_fr]
    valid = np.isfinite(ncc[es_fr]) & (ncc[es_fr] >= res.ncc_threshold)
    q = es_pos[valid]
    in_endo = _inside_fraction(q, es_endo)
    in_epi = _inside_fraction(q, es_epi)
    print("\n-- containment at ES vs true ES contours (valid kernels) --")
    print(f"  valid kernels at ES: {valid.sum()}/{len(es_pos)}")
    print(f"  inside TRUE ES endo (cavity side is INside endo polygon): {in_endo*100:.1f}%")
    print(f"  inside ES endo inflated by 8mm (epi)                    : {in_epi*100:.1f}%")
    print(
        f"  kernels OUTSIDE the true ES epicardium                    : {(1-in_epi)*100:.1f}%"
    )

    layers = [i for i, k in enumerate(res.kernels) if k.layer == "epi"]
    if layers:
        epi_q = es_pos[np.array(layers)][np.isfinite(ncc[es_fr, layers])]
        in_epi_l = _inside_fraction(epi_q, es_epi)
        print(
            f"  epi-LAYER kernels inside true ES epi: {in_epi_l*100:.1f}% "
            f"(of {len(epi_q)} valid epi kernels)"
        )

    # Containment against the ED-frame epicardium (what the user draws):
    ed_epi_poly = _poly(zone.epi_points)
    ed_endo_poly = _poly(endo)
    print("\n-- containment at ES vs ED-drawn contours (user scenario) --")
    print(f"  kernels OUTSIDE the ED epicardium (all kernels)      : {(1-_inside_fraction(es_pos, ed_epi_poly))*100:.1f}%")
    if layers:
        epi_all = es_pos[np.array(layers)]
        print(f"  epi-LAYER kernels OUTSIDE the ED epicardium          : {(1-_inside_fraction(epi_all, ed_epi_poly))*100:.1f}%")
    print(f"  kernels INSIDE the ED endo (into cavity)             : {_inside_fraction(es_pos, ed_endo_poly)*100:.1f}%")

    # Net contraction: radial distance from the ED cavity centroid.
    from scipy.spatial.distance import cdist

    endo_idx = [i for i, k in enumerate(res.kernels) if k.layer == "endo"]
    c0 = np.mean(endo, axis=0)
    ed_pos = pos[res.tracking_window_start]
    r_ed = np.linalg.norm(ed_pos[endo_idx] - c0, axis=1)
    r_es = np.linalg.norm(es_pos[endo_idx] - c0, axis=1)
    # true ES endo radius along each ED kernel ray (nearest point on ES contour)
    true_es = np.array(es_g["points"], dtype=np.float64)
    rays = (ed_pos[endo_idx] - c0)
    rays /= np.linalg.norm(rays, axis=1, keepdims=True) + 1e-9
    end_pts = c0 + rays * 2000
    dist = cdist(true_es, end_pts)
    r_true = true_es[np.argmin(dist, axis=0)] - c0
    r_true = np.linalg.norm(r_true, axis=1)
    # How well the tracked ES wall follows the true ES endocardium:
    # distance of each tracked ES endo kernel to the nearest true ES endo pt.
    from scipy.spatial import cKDTree

    tree = cKDTree(true_es) if "true_es" in dir() else None
    true_es_arr = np.array(es_g["points"], dtype=np.float64)
    tree = cKDTree(true_es_arr)
    endo_es = es_pos[endo_idx]
    d_true, _ = tree.query(endo_es)
    print("\n-- endo kernels at ES vs TRUE ES endo contour (px) --")
    print(f"  mean dist to true ES endo: {np.mean(d_true):5.1f}  (10mm={10/ (0.3):.0f}px at 0.3mm/px)")
    print(f"  p90 dist to true ES endo : {np.percentile(d_true,90):5.1f}")

    print("\n-- endo-layer radial contraction ED->ES (px) --")
    print(f"  kernels ED mean r     : {np.mean(r_ed):7.1f}")
    print(f"  kernels ES mean r     : {np.mean(r_es):7.1f}   (delta {np.mean(r_es)-np.mean(r_ed):+.1f})")
    print(f"  TRUE ES endo mean r   : {np.mean(r_true):7.1f}   (delta {np.mean(r_true)-np.mean(r_ed):+.1f})")
    print(f"  contraction captured  : {(np.mean(r_ed)-np.mean(r_es))/(np.mean(r_ed)-np.mean(r_true))*100:.0f}%")
    print(f"  tracked ES endo centroid offset from true: {np.linalg.norm(np.mean(es_pos[endo_idx],axis=0)-np.mean(true_es,axis=0)):.1f} px")


if __name__ == "__main__":
    main()
