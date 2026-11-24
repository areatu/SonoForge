"""Release surface restrictions; data and research implementations stay intact."""

# These are not user preferences: existing custom layouts must not expose
# unvalidated tools via search, favourites, radial menus or restored layouts.
HIDDEN_TOOL_IDS = frozenset({"la.strain", "rv.gls"})
