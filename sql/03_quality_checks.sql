-- Data quality checks on the gold layer. passed is 1 or 0, detail is the number behind it.
SELECT 'gold_cluster_hour' AS table_name, 'one_row_per_cluster_hour' AS check_name,
       CASE WHEN COUNT(*) = COUNT(DISTINCT cluster_id * 100000 + hour_index) THEN 1 ELSE 0 END AS passed,
       COUNT(*) AS detail
FROM gold_cluster_hour
UNION ALL
SELECT 'gold_cluster_hour', 'grid_complete',
       CASE WHEN COUNT(*) = (SELECT COUNT(*) FROM dim_cluster) * (MAX(hour_index) + 1) THEN 1 ELSE 0 END,
       COUNT(*)
FROM gold_cluster_hour
UNION ALL
SELECT 'gold_cluster_hour', 'cpu_between_0_and_100',
       CASE WHEN SUM(CASE WHEN cpu_util_pct < 0 OR cpu_util_pct > 100 THEN 1 ELSE 0 END) = 0 THEN 1 ELSE 0 END,
       SUM(CASE WHEN cpu_util_pct < 0 OR cpu_util_pct > 100 THEN 1 ELSE 0 END)
FROM gold_cluster_hour
UNION ALL
SELECT 'gold_cluster_hour', 'no_missing_keys',
       CASE WHEN SUM(CASE WHEN cluster_id IS NULL OR team_id IS NULL OR region_id IS NULL THEN 1 ELSE 0 END) = 0 THEN 1 ELSE 0 END,
       SUM(CASE WHEN cluster_id IS NULL OR team_id IS NULL OR region_id IS NULL THEN 1 ELSE 0 END)
FROM gold_cluster_hour
UNION ALL
SELECT 'gold_cluster_hour', 'telemetry_coverage_between_95_and_100_percent',
       CASE WHEN AVG(CASE WHEN reading_count > 0 THEN 1.0 ELSE 0.0 END) > 0.95
             AND AVG(CASE WHEN reading_count > 0 THEN 1.0 ELSE 0.0 END) < 1.0 THEN 1 ELSE 0 END,
       AVG(CASE WHEN reading_count > 0 THEN 1.0 ELSE 0.0 END)
FROM gold_cluster_hour
UNION ALL
SELECT 'gold_cluster_hour', 'staffing_known_after_first_deliveries',
       CASE WHEN AVG(CASE WHEN headcount_known IS NULL THEN 1.0 ELSE 0.0 END) < 0.06 THEN 1 ELSE 0 END,
       AVG(CASE WHEN headcount_known IS NULL THEN 1.0 ELSE 0.0 END)
FROM gold_cluster_hour
UNION ALL
SELECT 'gold_team_week', 'one_row_per_team_week',
       CASE WHEN COUNT(*) = COUNT(DISTINCT team_id * 1000 + week_index) THEN 1 ELSE 0 END,
       COUNT(*)
FROM gold_team_week
UNION ALL
SELECT 'gold_team_week', 'grid_complete',
       CASE WHEN COUNT(*) = (SELECT COUNT(*) FROM dim_team) * (MAX(week_index) + 1) THEN 1 ELSE 0 END,
       COUNT(*)
FROM gold_team_week
UNION ALL
SELECT 'gold_team_week', 'outage_counts_not_negative',
       CASE WHEN MIN(detected_outage_episodes) >= 0 THEN 1 ELSE 0 END,
       MIN(detected_outage_episodes)
FROM gold_team_week
UNION ALL
SELECT 'team_week_features', 'capacity_index_positive',
       CASE WHEN MIN(capacity_index) > 0 THEN 1 ELSE 0 END,
       MIN(capacity_index)
FROM team_week_features;
