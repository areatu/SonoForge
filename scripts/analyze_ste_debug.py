#!/usr/bin/env python3
"""Analyze STE debug dump: check positions, contours, drift, strain."""

import json
import sys
from pathlib import Path

import numpy as np


def analyze(dump_path: str) -> None:
    with open(dump_path) as f:
        data = json.load(f)

    ed_frame = data["ed_frame"]
    es_frame = data["es_frame"]
    phase_start, phase_end = data["phase_window"]
    ps = tuple(data["pixel_spacing_mm"])
    n_frames = data["n_frames_total"]
    gls = data["gls_pct"]

    print(f"=== STE Debug: {dump_path} ===")
    print(f"ED={ed_frame}  ES={es_frame}  window=[{phase_start}..{phase_end}]")
    print(f"Pixel spacing: {ps} mm/px  GLS: {gls}%")
    print()

    positions = np.array(data["positions_per_frame"])
    ncc = np.array(data["ncc_per_frame"])
    local_n_frames = positions.shape[0]
    local_ed = 0
    local_es = local_n_frames - 1

    kernels = data["kernels"]
    endo_kernels = [k for k in kernels if k["layer"] == "endo"]
    epi_kernels = [k for k in kernels if k["layer"] == "epi"]
    endo_idx = sorted(
        [k["index"] for k in endo_kernels],
        key=lambda i: kernels[i]["node_index"],
    )
    epi_idx = sorted(
        [k["index"] for k in epi_kernels],
        key=lambda i: kernels[i]["node_index"],
    ) if epi_kernels else []

    print("--- Contour length per frame ---")
    for t in range(local_n_frames):
        pts = positions[t, endo_idx, :]
        diffs = np.diff(pts, axis=0)
        seg_lens = np.linalg.norm(diffs, axis=1)
        total_mm = float(np.sum(seg_lens) * np.mean(ps))
        valid_n = int(np.sum(ncc[t, endo_idx] > 0))
        global_t = phase_start + t
        marker = " <-- ED" if t == local_ed else (" <-- ES" if t == local_es else "")
        print(f"  Frame {global_t:3d} (local {t:2d}): {total_mm:7.1f} mm  valid={valid_n}/{len(endo_idx)}{marker}")

    print()
    print("--- ED contour length ---")
    if data["ed_contour"]:
        ed_pts = np.array(data["ed_contour"])
        diffs = np.diff(ed_pts, axis=0)
        ed_len = float(np.sum(np.linalg.norm(diffs, axis=1)) * np.mean(ps))
        print(f"  ED contour: {ed_len:.1f} mm ({len(ed_pts)} points)")

    if data["es_contour"]:
        es_pts = np.array(data["es_contour"])
        diffs = np.diff(es_pts, axis=0)
        es_len = float(np.sum(np.linalg.norm(diffs, axis=1)) * np.mean(ps))
        print(f"  ES contour: {es_len:.1f} mm ({len(es_pts)} points)")

    print()
    print("--- Displacement analysis (ED -> each frame) ---")
    ed_positions = positions[local_ed]
    for t in [0, local_n_frames // 4, local_n_frames // 2, 3 * local_n_frames // 4, local_es]:
        disp = positions[t] - ed_positions
        disp_mm = disp * np.mean(ps)
        mag = np.linalg.norm(disp_mm, axis=1)
        valid_n = int(np.sum(ncc[t] > 0))
        global_t = phase_start + t
        print(f"  Frame {global_t:3d}: mean_disp={mag.mean():.2f}mm  max={mag.max():.2f}mm  valid={valid_n}/{data['kernel_count']}")

    print()
    print("--- NCC quality per frame ---")
    for t in range(local_n_frames):
        mean_ncc = float(np.mean(ncc[t]))
        above = int(np.sum(ncc[t] > data["config"]["ncc_threshold"]))
        global_t = phase_start + t
        print(f"  Frame {global_t:3d}: mean_NCC={mean_ncc:.3f}  above_thr={above}/{data['kernel_count']}")

    print()
    print("--- Kernel displacement directions (ED -> ES) ---")
    disp_es = (positions[local_es] - ed_positions) * np.mean(ps)
    for layer_name, idx_list in [("endo", endo_idx), ("epi", epi_idx)]:
        if not idx_list:
            continue
        for k_idx in idx_list[:6]:
            k = kernels[k_idx]
            d = disp_es[k_idx]
            mag = np.linalg.norm(d)
            angle = np.degrees(np.arctan2(d[1], d[0]))
            print(f"  {layer_name}[{k['node_index']:2d}]: "
                  f"dx={d[0]:+6.2f} dy={d[1]:+6.2f} mm  "
                  f"|d|={mag:.2f}mm  angle={angle:.0f}deg")

    print()
    print("--- Longitudinal strain ---")
    ls = data.get("longitudinal_strain")
    if ls:
        for t in range(len(ls)):
            global_t = phase_start + t
            marker = " <-- ED" if t == local_ed else (" <-- ES" if t == local_es else "")
            if ls[t] is not None:
                print(f"  Frame {global_t:3d}: {ls[t]:+7.2f}%{marker}")

    print()
    print(f"Dump saved at: {dump_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        debug_dir = Path.home() / "ECHO2026_ste_debug"
        dumps = sorted(debug_dir.glob("ste_*.json"), key=lambda p: p.stat().st_mtime)
        if not dumps:
            print("No debug dumps found in ~/ECHO2026_ste_debug/")
            sys.exit(1)
        analyze(str(dumps[-1]))
    else:
        analyze(sys.argv[1])
