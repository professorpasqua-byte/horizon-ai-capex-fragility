"""Model 3a: would the index have warned before the outages surged?

A team is flagged when its capacity index sits below the tipping point for
`consecutive` weeks. An outage surge is `surge_count` or more detected outage
episodes within a trailing `surge_window` weeks. Lead = surge week - flag week.
"""

import numpy as np

from horizon.models.features import capacity_index


def early_warning(tw, knot, consecutive=2, surge_window=6, surge_count=4):
    idx, out = capacity_index(tw), {k: [] for k in ("team_id", "flag_week", "surge_week", "lead_weeks")}
    for t in np.unique(tw["team_id"]):
        m = tw["team_id"] == t
        below = idx[m] < knot
        run = np.convolve(below.astype(int), np.ones(consecutive, dtype=int), "full")[consecutive - 1 : len(below)]
        flags = np.flatnonzero(run >= consecutive)
        flag = int(flags[0]) - (consecutive - 1) if len(flags) else -1
        roll = np.convolve(tw["detected_outage_episodes"][m], np.ones(surge_window), "full")[: m.sum()]
        surges = np.flatnonzero(roll >= surge_count)
        surge = int(surges[0]) if len(surges) else -1
        out["team_id"].append(int(t))
        out["flag_week"].append(flag)
        out["surge_week"].append(surge)
        out["lead_weeks"].append(surge - flag if flag >= 0 and surge >= 0 else np.nan)
    return {k: np.array(v) for k, v in out.items()}
