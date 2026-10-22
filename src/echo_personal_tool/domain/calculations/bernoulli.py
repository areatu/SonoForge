def pressure_gradient_mmhg(velocity_cm_s: float) -> float:
    """Simplified Bernoulli: PG = 4 * v^2 with v in m/s."""
    v_m_s = velocity_cm_s / 100.0
    return 4.0 * v_m_s * v_m_s
