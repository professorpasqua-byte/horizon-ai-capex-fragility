"""Central configuration for the Horizon simulation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

# The simulated window: 1 Oct 2025 to 30 Sep 2026.
WINDOW_START = datetime(2025, 10, 1, tzinfo=timezone.utc)

# (name, UTC offset in hours, quarter when AI budget diversion starts).
# None marks the protected control region that never diverts.
REGIONS: tuple[tuple[str, int, int | None], ...] = (
    ("na-east", -5, 0),
    ("eu-west", 0, 1),
    ("apac-south", 8, 2),
    ("latam-central", -3, None),
)

TEAMS_PER_REGION = 2


@dataclass(frozen=True)
class Scale:
    """How big a run is. The gold grain is always one row per cluster-hour."""

    name: str
    clusters_per_region: int
    days: int
    samples_per_hour: int  # raw telemetry readings per cluster per hour


SCALES: dict[str, Scale] = {
    "tiny": Scale("tiny", clusters_per_region=2, days=28, samples_per_hour=1),
    "standard": Scale("standard", clusters_per_region=7, days=365, samples_per_hour=1),
    "full": Scale("full", clusters_per_region=7, days=365, samples_per_hour=12),
}


@dataclass(frozen=True)
class HiddenTruth:
    """The causal rules baked into the simulation.

    Written to a separate file that analysis code must never read.
    The grading step compares what the pipeline finds with these values.
    """

    fracture_ratio: float = 0.72
    ramp_width: float = 0.10
    lag_weeks: int = 6
    underreport_low_safety: float = 0.35
    underreport_high_safety: float = 0.05
    low_safety_cutoff: float = 0.5


@dataclass(frozen=True)
class SimConfig:
    scale: Scale
    seed: int = 42
    truth: HiddenTruth = field(default_factory=HiddenTruth)

    @property
    def hours(self) -> int:
        return self.scale.days * 24

    @property
    def n_clusters(self) -> int:
        return len(REGIONS) * self.scale.clusters_per_region

    @property
    def expected_gold_rows(self) -> int:
        """Rows in the cluster-hour table: clusters times hours."""
        return self.n_clusters * self.hours
