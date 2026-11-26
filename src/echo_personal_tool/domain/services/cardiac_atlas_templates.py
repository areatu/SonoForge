"""Projection-specific analytic meshes, not reference-population normal values.

Coordinates are in a canonical metric frame, valve plane near Y=0 and apex
at positive Y. These intentionally simple seeds require local validation.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

ATLAS_VIEWS = ("A4C", "RV_A4C", "A2C", "A3C", "PLAX", "PSAX")


class AnalyticAtlasSeed(NamedTuple):
    """Leaf data record, deliberately independent of the fitted model module."""

    view: str
    structures: dict[str, tuple[int, ...]]
    landmarks: dict[str, int]
    mean_ed: np.ndarray
    mean_es: np.ndarray
    modes: np.ndarray
    eigenvalues: np.ndarray
    mode_names: tuple[str, ...]
    closed_structures: tuple[str, ...]


def _quadratic(a: np.ndarray, control: np.ndarray, b: np.ndarray, count: int) -> np.ndarray:
    t = np.linspace(0, 1, count)[:, None]
    return np.asarray((1 - t) ** 2 * a + 2 * t * (1 - t) * control + t**2 * b, dtype=np.float64)


def _dome(start: np.ndarray, roof: np.ndarray, end: np.ndarray, count: int) -> np.ndarray:
    n = count // 2 + 1
    c1 = np.array([start[0], roof[1]])
    c2 = np.array([end[0], roof[1]])
    return np.vstack([_quadratic(start, c1, roof, n), _quadratic(roof, c2, end, count - n + 1)[1:]])


def _apical_mesh(view: str) -> tuple[np.ndarray, dict[str, tuple[int, ...]], dict[str, int]]:
    left_t = np.r_[0.0, np.arcsin(5 / 80), np.linspace(0.18, np.pi / 2, 15)]
    right_t = np.linspace(np.pi / 2, np.pi, 16)[1:]
    theta = np.r_[left_t, right_t]
    width = 14.0 if view in {"A3C", "PLAX"} else 15.0
    lv = np.column_stack([-width * np.cos(theta), 80 * np.sin(theta)])
    nodes = list(lv)
    structures: dict[str, tuple[int, ...]] = {"LV": tuple(range(32))}
    if view != "A2C":
        structures["IVS"] = tuple(range(17))
    landmarks = {"MV_septal": 0, "MV_lateral": 31, "LV_apex": 16}
    la = _dome(lv[0], np.array([0.0, -40.0]), lv[-1], 24)
    roof = len(nodes) + 11
    la_indices = (0, *range(len(nodes), len(nodes) + 22), 31)
    nodes.extend(la[1:-1])
    structures["LA"] = la_indices
    landmarks["LA_apex"] = roof
    if view in {"A4C", "RV_A4C"}:
        shared = tuple(range(1, 13))
        lateral = np.array([-50.0 if view == "RV_A4C" else -45.0, 5.0])
        start = lv[shared[-1]]
        t = np.linspace(0, 1, 13)[:, None]
        c1, c2 = start + [-1, 12], np.array([lateral[0] - 8, 50])
        free = (1 - t) ** 3 * start + 3 * t * (1 - t) ** 2 * c1 + 3 * t**2 * (1 - t) * c2 + t**3 * lateral
        free_ids = tuple(range(len(nodes), len(nodes) + 12))
        nodes.extend(free[1:])
        structures["RV"] = (*shared, *free_ids)
        landmarks.update({"TV_septal": shared[0], "TV_lateral": free_ids[-1], "RV_apex": shared[-1]})
        ra = _dome(lv[1], np.array([-36.0, -34.0]), lateral, 24)
        ra_ids = (1, *range(len(nodes), len(nodes) + 22), free_ids[-1])
        landmarks["RA_apex"] = ra_ids[12]
        nodes.extend(ra[1:-1])
        structures["RA"] = ra_ids
    elif view in {"A3C", "PLAX"}:
        # Outflow tract and aortic root lie outside the LV/LA cavities.
        structures["LVOT"] = (0, len(nodes), len(nodes) + 1, len(nodes) + 2)
        nodes.extend([np.array([-19, 8]), np.array([-39, -18]), np.array([-32, -25])])
        structures["AO"] = (len(nodes) - 2, len(nodes), len(nodes) + 1, len(nodes) - 1)
        nodes.extend([np.array([-48, -32]), np.array([-40, -39])])
    return np.asarray(nodes, dtype=np.float64), structures, landmarks


def _short_axis_mesh() -> tuple[np.ndarray, dict[str, tuple[int, ...]], dict[str, int]]:
    theta = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    lv = np.column_stack([-25 * np.sin(theta), -25 * np.cos(theta)])
    # RV crescent shares the entire sampled left septal boundary, in reverse.
    t = np.array([0, 0.1, 0.55, 1.1, np.pi / 2, np.pi - 1.1, np.pi - 0.55, np.pi - 0.1, np.pi])
    free = np.column_stack([-48 * np.sin(t), 25 * np.cos(t)])
    nodes = np.vstack([lv, free[1:-1]])
    structures = {"LV": tuple(range(32)), "RV": (*range(17), *range(32, 39)), "IVS": tuple(range(17))}
    return nodes, structures, {}


def analytic_atlas_seed(view: str) -> AnalyticAtlasSeed:
    key = view.upper()
    if key not in ATLAS_VIEWS:
        raise ValueError(f"unsupported atlas view: {view}")
    ed, structures, landmarks = _short_axis_mesh() if key == "PSAX" else _apical_mesh(key)
    es = ed.copy()
    if key == "PSAX":
        es *= 0.78
    else:
        es[:, 0] *= np.where(ed[:, 1] < 0, 1.15, 0.85)
        es[:, 1] *= np.where(ed[:, 1] < 0, 1.2, 0.8)
    modes = np.zeros((4, len(ed), 2), dtype=np.float64)
    # Deform shared nodes only once; a common valve/IVS can never separate.
    for index in structures.get("LA", ()):
        weight = max(0.0, -float(ed[index, 1]) / 40)
        modes[0, index] = ed[index] * weight * 0.08
    septal = set(structures.get("IVS", ()))
    for index in structures.get("RV", ()):
        # RV lies on negative X: overload expands the free wall leftwards,
        # but pushes the shared septum RIGHT into the LV (D-shaped compression).
        direction = 1.0 if index in septal else -1.0
        modes[1, index, 0] = direction * 2.0 * np.sin(np.pi * max(0.0, float(ed[index, 1])) / 90)
    for index in structures["LV"]:
        modes[2, index, 0] = float(ed[index, 0]) * 0.06
    modes[3, :, 1] = np.maximum(ed[:, 1], 0) * -0.035
    # Longitudinal contraction is coupled to anti-phase atrial expansion.
    modes[3, ed[:, 1] < 0, 1] = ed[ed[:, 1] < 0, 1] * 0.035
    return AnalyticAtlasSeed(
        key,
        structures,
        landmarks,
        ed,
        es,
        modes,
        np.ones(4),
        ("la_dilatation", "rv_overload_ivs_shift", "lv_remodelling", "longitudinal_contraction"),
        ("LV", "RV") if key == "PSAX" else ("LVOT", "AO") if "LVOT" in structures else (),
    )
