"""Release surface restrictions; data and research implementations stay intact."""

# These are not user preferences: existing custom layouts must not expose
# unvalidated tools via search, favourites, radial menus or restored layouts.
HIDDEN_TOOL_IDS = frozenset({"la.strain", "rv.gls", "cca.imt_semiauto"})

# Unfinished study profiles (#650 follow-ups): the profile switch never offers
# them and a saved selection falls back to the default profile. The profile
# data itself stays intact, so reports of older snapshots rebuild unchanged.
HIDDEN_PROFILE_IDS = frozenset({"builtin.pediatric_echo", "builtin.fetal_echo"})
