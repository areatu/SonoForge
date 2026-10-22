"""Pulmonary pressures and resistance from Doppler (Э11в).

Pure functions, no Qt.  Every function returns ``None`` when an input is
missing or not physically meaningful.  The right atrial pressure is never
assumed: it is entered by the user (estimated from the IVC per guideline).

* PASP: ``4 · TR Vmax² + RAP`` (simplified Bernoulli, no RVOT/PV obstruction).
  Rudski LG et al. J Am Soc Echocardiogr 2010;23:685–713.
* mPAP from PASP (Chemla): ``0.61 · PASP + 2``.
  Chemla D et al. Chest 2004;126:1313–1317.
* mPAP from the RVOT acceleration time (Mahan): ``79 − 0.45 · AT``.
  Mahan G et al. Circulation 1983;68(Suppl III):III-367; cited in Rudski 2010.
* PVR (Abbas): ``10 · TR Vmax / RVOT VTI + 0.16`` Wood units.
  Abbas AE et al. J Am Coll Cardiol 2003;41:1021–1027.
"""

from __future__ import annotations

import math


def _finite(*values: float | None) -> bool:
    return all(value is not None and math.isfinite(value) for value in values)


def _positive(*values: float | None) -> bool:
    return _finite(*values) and all(value > 0.0 for value in values)  # type: ignore[operator]


def tr_gradient_mmhg(tr_vmax_m_s: float | None) -> float | None:
    """RV–RA systolic gradient, mmHg: ``4 · V²`` (V in m/s)."""
    if not _positive(tr_vmax_m_s):
        return None
    return 4.0 * tr_vmax_m_s * tr_vmax_m_s


def pasp_mmhg(tr_gradient: float | None, rap_mmhg: float | None) -> float | None:
    """Pulmonary artery systolic pressure, mmHg: TR gradient + RAP.

    RAP may be 0 mmHg; a negative RAP is rejected.
    """
    if not _positive(tr_gradient) or not _finite(rap_mmhg) or rap_mmhg < 0.0:  # type: ignore[operator]
        return None
    return tr_gradient + rap_mmhg


def mpap_chemla_mmhg(pasp: float | None) -> float | None:
    """Mean PA pressure, mmHg, from PASP: ``0.61 · PASP + 2`` (Chemla 2004)."""
    if not _positive(pasp):
        return None
    return 0.61 * pasp + 2.0


def mpap_mahan_mmhg(rvot_at_ms: float | None) -> float | None:
    """Mean PA pressure, mmHg, from the RVOT acceleration time: ``79 − 0.45 · AT``.

    A non-positive result (AT above ~175 ms) is returned as ``None``: the
    regression has no meaning there.
    """
    if not _positive(rvot_at_ms):
        return None
    value = 79.0 - 0.45 * rvot_at_ms
    return value if value > 0.0 else None


def pvr_abbas_wu(tr_vmax_m_s: float | None, rvot_vti_cm: float | None) -> float | None:
    """Pulmonary vascular resistance, Wood units: ``10 · TRV / VTI_RVOT + 0.16``."""
    if not _positive(tr_vmax_m_s, rvot_vti_cm):
        return None
    return 10.0 * tr_vmax_m_s / rvot_vti_cm + 0.16
