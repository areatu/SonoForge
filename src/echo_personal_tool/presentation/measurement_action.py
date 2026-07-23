"""Worksheet action identifiers for measurement workflow routing."""

from __future__ import annotations

from enum import StrEnum


class MeasurementAction(StrEnum):
    """User-selectable measurement worksheet actions."""

    CALIBRATION = "calibration"
    CALIPER = "caliper"
    SPLINE_AREA = "spline_area"
    SPLINE_VOLUME = "spline_volume"
    RESET = "reset"
    MANUAL_SIMPSON = "manual_simpson"
    MBS_SIMPSON = "mbs_simpson"
    LV2D_ALL_DIASTOLE = "lv2d_all_diastole"
    LV2D_ES = "lv2d_es"
    LA_DIAMETER = "la_diameter"
    LAV_4C = "lav_4c"
    LAV_BI = "lav_bi"
    RA_DIAMETER = "ra_diameter"
    RA_AREA = "ra_area"
    RAV_VOLUME = "rav_volume"
    RV_BASAL = "rv_basal"
    RV_TAPSE = "rv_tapse"
    RV_S_PRIME = "rv_s_prime"
    RV_FAC = "rv_fac"
    DOPPLER_PEAK = "doppler_peak"
    DOPPLER_E_DT_A = "doppler_e_dt_a"
    DOPPLER_INTERVAL = "doppler_interval"
    DOPPLER_TRACE = "doppler_trace"
    DOPPLER_MITRAL_INFLOW = "doppler_mitral_inflow"
    AUTO_SEGMENT = "auto_segment"
    LAV_4C_AUTO = "lav_4c_auto"
    LAV_4C_AI_PLUS = "lav_4c_ai_plus"
    SPECKLE_TRACKING = "speckle_tracking"
    MMODE = "mmode"
