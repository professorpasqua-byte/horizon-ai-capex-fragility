# Data dictionary

Everything here is synthetic. Horizon is a fictional company with 4 regions, 8 teams and 28 clusters, simulated for one year (1 Oct 2025 to 30 Sep 2026).

## Folders

| Folder | What it holds | Who may read it |
|---|---|---|
| `data/raw` | The clean originals before any mess is added | Grading only |
| `data/landing` | What each source system hands over, messy on purpose | The pipeline |
| `data/silver` | Cleaned tables | Models, SQL |
| `data/gold` | Analysis-ready tables | Models, SQL, dashboard |
| `data/truth` | The planted answer key | The grader only |
| `results` | Small result files, safe to publish | The dashboard |

## Reference tables (data/raw/dims)

- `dim_region`: `region_id`, `region_name`, `utc_offset_hours`, `diversion_start_quarter` (empty for the protected control region), `is_control`
- `dim_team`: `team_id`, `region_id`, `team_name`, `starting_headcount`
- `dim_cluster`: `cluster_id`, `region_id`, `team_id`, `cluster_name`, `hardware_age_years`, `capacity_units`

## Landing sources (data/landing)

**telemetry**, near real time, one reading per cluster per hour
- `cluster_id`, `ts_reported` (apac-south logs local time as if it were UTC), `ingested_ts` (when it arrived)
- `cpu_util_pct`, `inlet_temp_c` (-999 means a sensor glitch), `throttle_pct`, `packet_drop_pct`, `p99_latency_ms`
- `health_check_ok` (1 healthy, 0 failed)

**staffing**, weekly HR export, arrives days late
- `team_label` (messy spellings), `week_ending`, `funded_headcount`, `headcount`, `hires`, `departures`, `reductions`
- `overtime_hours_per_head` (-1 means missing), `delivered_at`

**budget**, quarterly, money stored as text
- `region_name`, `fiscal_quarter`, `quarter_start`, `version` (2 is a restatement)
- `total_budget`, `ai_budget`, `core_budget` (like $12.50M), `ai_share` (like 5.0%), `delivered_at`

**tickets**, daily batch
- `ticket_id`, `created_ts` and `resolved_ts` (text, latam-central carries a -03:00 offset)
- `team_id`, `cluster_id`, `ticket_type` (incident or routine), `severity` (blank on some routine tickets), `delivered_at`

**postmortems**
- `ticket_id`, `written_ts`, `root_cause` (free text), `delivered_at`

**survey**, monthly pulse on psychological safety
- `team_label`, `month_start`, `invited`, `responses`, `mean_safety_score` (1 to 5, hidden when fewer than 5 responses), `delivered_at`

## Gold tables (data/gold)

**gold_cluster_hour**, one row per cluster per hour (245,280 rows)
- Keys: `cluster_id`, `region_id`, `team_id`, `hour_index`, `ts_utc`
- Telemetry: `reading_count`, `cpu_util_pct`, `inlet_temp_c`, `throttle_pct`, `packet_drop_pct`, `p99_latency_ms`, `health_ok` (empty when no reading arrived)
- Known at that hour, joined as of delivery date: `headcount_known`, `funded_known`, `overtime_known`, `safety_known`, `ai_share_known`, `core_share_known`, `heads_per_cluster_known`

**gold_team_week**, one row per team per week (416 rows)
- Keys: `team_id`, `region_id`, `week_index`, `week_start`
- Staffing: `staffing_missing` (true when the week was filled by interpolation), `headcount`, `funded_headcount`, `hires`, `departures`, `reductions`, `overtime_hours_per_head`
- Tickets: `incident_tickets`, `routine_tickets`, `median_resolution_hours`, `open_backlog_end`
- Telemetry: `mean_cpu_util_pct`, `mean_throttle_pct`, `mean_packet_drop_pct`, `mean_p99_latency_ms`, `health_fail_hours`, `telemetry_coverage`, `detected_outage_episodes`
- Context: `safety_known`, `ai_share_known`, `core_share_known`

## Results (results/)

`findings.json` (all model outputs), `grading.csv` (found against truth), `tipping_profile.csv`, `lead_time_profile.csv`, `early_warning.csv`, `reporting_gap.csv`, `team_signals.csv`, `dq_report.csv`, `cleaning_report.csv`, `sql_checks.csv`, `region_quarter.csv`.
