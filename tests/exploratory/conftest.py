"""Hypothesis profile registration for exploratory property/fuzz tests (issue 483).

Profiles:
  - ``ci``: fast, deterministic PR gate (``max_examples=40``, ``derandomize=True``).
  - ``nightly``: deep scheduled exploration (``max_examples=500``, ``derandomize=False``).
  - ``default``: local developer run (``max_examples=100``, ``derandomize=True``).
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    max_examples=40,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=500,
    derandomize=False,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "default",
    max_examples=100,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
