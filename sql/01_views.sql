-- Team-week features computed in SQL.
-- The capacity index compares each week with the team's first four weeks:
-- (headcount / starting headcount) / (CPU use / starting CPU use). 1.0 = where the team started.
DROP VIEW IF EXISTS team_week_features;
CREATE VIEW team_week_features AS
SELECT
    team_id,
    region_id,
    week_index,
    headcount,
    overtime_hours_per_head,
    open_backlog_end,
    detected_outage_episodes,
    incident_tickets,
    ai_share_known,
    mean_cpu_util_pct,
    (headcount / AVG(CASE WHEN week_index < 4 THEN headcount END) OVER (PARTITION BY team_id))
    / (mean_cpu_util_pct / AVG(CASE WHEN week_index < 4 THEN mean_cpu_util_pct END) OVER (PARTITION BY team_id))
        AS capacity_index
FROM gold_team_week;
