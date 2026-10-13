"""Build the fictional Horizon Infrastructure Group: regions, teams, clusters.

build_world is pure: same config in, same tables out. The hidden truth is
returned separately and never placed inside a dimension table.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from horizon.config import REGIONS, SCALES, TEAMS_PER_REGION, SimConfig

Table = dict[str, list]


def build_world(cfg: SimConfig) -> dict:
    """Return dimension tables (plain column dicts) plus the hidden truth."""
    team_ss, cluster_ss = np.random.SeedSequence(cfg.seed).spawn(2)
    team_rng = np.random.default_rng(team_ss)
    cluster_rng = np.random.default_rng(cluster_ss)

    dim_region: Table = {
        "region_id": list(range(len(REGIONS))),
        "region_name": [r[0] for r in REGIONS],
        "utc_offset_hours": [r[1] for r in REGIONS],
        "diversion_start_quarter": [r[2] for r in REGIONS],
        "is_control": [r[2] is None for r in REGIONS],
    }

    # Latent safety is spread across a range so low and high safety teams
    # always exist, then jittered per seed. It lives in the truth only.
    n_teams = len(REGIONS) * TEAMS_PER_REGION
    safety = np.linspace(0.20, 0.85, n_teams)
    safety = team_rng.permutation(safety) + team_rng.normal(0, 0.02, n_teams)
    safety = np.clip(safety, 0.05, 0.95)

    dim_team: Table = {
        "team_id": [],
        "region_id": [],
        "team_name": [],
        "starting_headcount": [],
    }
    for region_id, (name, _, _) in enumerate(REGIONS):
        for k in range(TEAMS_PER_REGION):
            dim_team["team_id"].append(region_id * TEAMS_PER_REGION + k)
            dim_team["region_id"].append(region_id)
            dim_team["team_name"].append(f"sre-{name}-{k + 1}")
            dim_team["starting_headcount"].append(int(team_rng.integers(8, 15)))

    # Clusters in a region alternate between its teams.
    dim_cluster: Table = {
        "cluster_id": [],
        "region_id": [],
        "team_id": [],
        "cluster_name": [],
        "hardware_age_years": [],
        "capacity_units": [],
    }
    cid = 0
    for region_id, (name, _, _) in enumerate(REGIONS):
        for j in range(cfg.scale.clusters_per_region):
            team_id = region_id * TEAMS_PER_REGION + (j % TEAMS_PER_REGION)
            dim_cluster["cluster_id"].append(cid)
            dim_cluster["region_id"].append(region_id)
            dim_cluster["team_id"].append(team_id)
            dim_cluster["cluster_name"].append(f"{name}-c{j + 1:02d}")
            dim_cluster["hardware_age_years"].append(round(float(cluster_rng.uniform(1, 7)), 2))
            dim_cluster["capacity_units"].append(int(cluster_rng.integers(80, 241)))
            cid += 1

    truth = asdict(cfg.truth)
    truth["latent_safety_by_team"] = {
        str(tid): round(float(s), 4) for tid, s in zip(dim_team["team_id"], safety)
    }

    return {
        "dim_region": dim_region,
        "dim_team": dim_team,
        "dim_cluster": dim_cluster,
        "truth": truth,
    }


def write_world(world: dict, root: Path = Path("data")) -> None:
    """Write dimensions to Parquet and the truth to its own folder."""
    import polars as pl

    dims_dir = root / "raw" / "dims"
    truth_dir = root / "truth"
    dims_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    for name in ("dim_region", "dim_team", "dim_cluster"):
        pl.DataFrame(world[name]).write_parquet(dims_dir / f"{name}.parquet")
    (truth_dir / "hidden_truth.json").write_text(json.dumps(world["truth"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Horizon world.")
    parser.add_argument("--scale", choices=SCALES, default="standard")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args()

    cfg = SimConfig(scale=SCALES[args.scale], seed=args.seed)
    world = build_world(cfg)
    write_world(world, args.out)
    print(
        f"scale={cfg.scale.name} regions={len(world['dim_region']['region_id'])} "
        f"teams={len(world['dim_team']['team_id'])} "
        f"clusters={len(world['dim_cluster']['cluster_id'])} "
        f"gold_rows={cfg.expected_gold_rows:,}"
    )


if __name__ == "__main__":
    main()
