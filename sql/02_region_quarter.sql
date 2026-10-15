-- One row per region per quarter: how capacity, outages, tickets and overtime moved.
SELECT
    region_id,
    CAST((week_index - week_index % 13) / 13 AS INTEGER) AS quarter,
    AVG(capacity_index) AS avg_capacity_index,
    SUM(detected_outage_episodes) AS outage_episodes,
    SUM(incident_tickets) AS incident_tickets,
    AVG(overtime_hours_per_head) AS avg_overtime_hours
FROM team_week_features
GROUP BY region_id, CAST((week_index - week_index % 13) / 13 AS INTEGER)
ORDER BY region_id, quarter;
