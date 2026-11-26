"""Release surface visibility; experimental research features are active."""

from __future__ import annotations

# Kept as exported sets so layout, profile, and catalog callers share one gate.
# All experimental research tools and study profiles hidden in 0.4.2 are active.
HIDDEN_TOOL_IDS: frozenset[str] = frozenset()
HIDDEN_PROFILE_IDS: frozenset[str] = frozenset()
