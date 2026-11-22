"""Lazy re-exports (PEP 562).

The historical eager imports here made every ``domain.models`` →
``domain.calculations`` import drag ``doppler_metrics`` (and through it
``domain.models.measurements``) into partially-initialized modules — a
circular import (А.10). No consumer reads the package-level names, so they
stay available but load on first attribute access.
"""

from __future__ import annotations

_LAZY: dict[str, tuple[str, str]] = {
    "pressure_gradient_mmhg": ("echo_personal_tool.domain.calculations.bernoulli", "pressure_gradient_mmhg"),
    "compute": ("echo_personal_tool.domain.calculations.doppler_metrics", "compute"),
    "la_from_measurements": ("echo_personal_tool.domain.calculations.la_area_length", "from_measurements"),
    "la_volume_ml": ("echo_personal_tool.domain.calculations.la_area_length", "volume_ml"),
    "calculate": ("echo_personal_tool.domain.calculations.lvef_simpson", "calculate"),
    "from_linear_measurements": ("echo_personal_tool.domain.calculations.teichholz", "from_linear_measurements"),
    "volume_ml": ("echo_personal_tool.domain.calculations.teichholz", "volume_ml"),
}

__all__ = [
    "calculate",
    "compute",
    "from_linear_measurements",
    "la_from_measurements",
    "la_volume_ml",
    "pressure_gradient_mmhg",
    "volume_ml",
]


def __getattr__(name: str) -> object:  # PEP 562 module getter
    entry = _LAZY.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(entry[0])
    return getattr(module, entry[1])
