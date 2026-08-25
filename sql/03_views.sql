-- Metric / semantic layer. The NL2SQL agent is instructed to prefer these views.

CREATE OR REPLACE VIEW did.vw_task_assignment AS
SELECT
    task_id,
    delivery_id,
    study_id,
    task_kind,
    task_type,
    task_name,
    dataset,
    file_name,
    tlf_number,
    'Production'::TEXT AS role,
    production_name AS person_name
FROM did.task
WHERE production_name IS NOT NULL AND btrim(production_name) <> ''
UNION ALL
SELECT
    task_id,
    delivery_id,
    study_id,
    task_kind,
    task_type,
    task_name,
    dataset,
    file_name,
    tlf_number,
    'QC'::TEXT AS role,
    qc_name AS person_name
FROM did.task
WHERE qc_name IS NOT NULL AND btrim(qc_name) <> '';

CREATE OR REPLACE VIEW did.vw_person_weekly_workload AS
SELECT
    p.person_id,
    p.person_name,
    p.email,
    p.manager,
    p.team,
    p.ta_lead,
    p.site,
    date_trunc('week', t.entry_date)::date AS week_start,
    SUM(t.hours) AS actual_hours,
    COUNT(DISTINCT t.delivery_id) AS delivery_count,
    COUNT(DISTINCT t.study_id) AS study_count,
    COUNT(DISTINCT t.entry_date) AS days_worked,
    ROUND(SUM(t.hours) / 40.0, 3) AS utilization
FROM did.time_entry t
JOIN did.person p ON p.person_id = t.person_id
GROUP BY p.person_id, p.person_name, p.email, p.manager, p.team, p.ta_lead, p.site,
         date_trunc('week', t.entry_date)::date;

CREATE OR REPLACE VIEW did.vw_person_monthly_workload AS
SELECT
    p.person_id,
    p.person_name,
    p.email,
    p.manager,
    p.team,
    p.ta_lead,
    p.site,
    to_char(t.entry_date, 'YYYY-MM') AS year_month,
    date_trunc('month', t.entry_date)::date AS month_start,
    SUM(t.hours) AS actual_hours,
    COUNT(DISTINCT t.delivery_id) AS delivery_count,
    COUNT(DISTINCT t.study_id) AS study_count,
    COUNT(DISTINCT t.entry_date) AS days_worked,
    ROUND(SUM(t.hours) / 160.0, 3) AS utilization
FROM did.time_entry t
JOIN did.person p ON p.person_id = t.person_id
GROUP BY p.person_id, p.person_name, p.email, p.manager, p.team, p.ta_lead, p.site,
         to_char(t.entry_date, 'YYYY-MM'), date_trunc('month', t.entry_date)::date;

CREATE OR REPLACE VIEW did.vw_delivery_hours AS
SELECT
    d.delivery_id,
    d.study_id,
    d.source_system,
    d.status,
    d.reporting_event,
    d.work_type,
    d.draft_or_final,
    d.planned_delivery_date,
    d.actual_delivery_date,
    d.quality,
    d.cancelled,
    d.urgent,
    s.ta,
    s.phase,
    COALESCE(SUM(t.hours), 0) AS actual_hours,
    COUNT(DISTINCT t.person_id) AS people_count,
    COUNT(DISTINCT t.entry_date) AS days_with_hours
FROM did.delivery d
LEFT JOIN did.study s ON s.study_id = d.study_id
LEFT JOIN did.time_entry t ON t.delivery_id = d.delivery_id
GROUP BY d.delivery_id, d.study_id, d.source_system, d.status, d.reporting_event,
         d.work_type, d.draft_or_final, d.planned_delivery_date, d.actual_delivery_date,
         d.quality, d.cancelled, d.urgent, s.ta, s.phase;

CREATE OR REPLACE VIEW did.vw_study_hours AS
SELECT
    st.study_id,
    st.ta,
    st.phase,
    st.indication,
    st.status AS study_status,
    st.sdsl,
    COALESCE(SUM(t.hours), 0) AS actual_hours,
    COUNT(DISTINCT t.person_id) AS people_count,
    COUNT(DISTINCT t.delivery_id) AS delivery_count
FROM did.study st
LEFT JOIN did.time_entry t ON t.study_id = st.study_id
GROUP BY st.study_id, st.ta, st.phase, st.indication, st.status, st.sdsl;

CREATE OR REPLACE VIEW did.vw_person_delivery_hours AS
SELECT
    p.person_name,
    p.email,
    p.manager,
    p.team,
    p.site,
    t.delivery_id,
    t.study_id,
    d.reporting_event,
    d.status AS delivery_status,
    d.planned_delivery_date,
    SUM(t.hours) AS actual_hours,
    MIN(t.entry_date) AS first_entry_date,
    MAX(t.entry_date) AS last_entry_date
FROM did.time_entry t
JOIN did.person p ON p.person_id = t.person_id
LEFT JOIN did.delivery d ON d.delivery_id = t.delivery_id
GROUP BY p.person_name, p.email, p.manager, p.team, p.site, t.delivery_id, t.study_id,
         d.reporting_event, d.status, d.planned_delivery_date;

CREATE OR REPLACE VIEW did.vw_future_delivery AS
SELECT
    d.delivery_id,
    d.study_id,
    d.status,
    d.reporting_event,
    d.work_type,
    d.planned_delivery_date,
    d.actual_delivery_date,
    d.urgent,
    d.cancelled,
    s.ta,
    s.phase,
    s.sdsl,
    (d.planned_delivery_date - CURRENT_DATE) AS days_until_due
FROM did.delivery d
LEFT JOIN did.study s ON s.study_id = d.study_id
WHERE d.cancelled IS NOT TRUE
  AND d.planned_delivery_date IS NOT NULL
  AND d.planned_delivery_date >= CURRENT_DATE
  AND (d.actual_delivery_date IS NULL OR d.status ILIKE '%progress%' OR d.status ILIKE '%planned%' OR d.status IS NULL);

CREATE OR REPLACE VIEW did.vw_person_future_assignments AS
SELECT
    a.person_name,
    a.role,
    a.task_kind,
    a.task_type,
    a.task_name,
    a.delivery_id,
    d.study_id,
    d.status AS delivery_status,
    d.reporting_event,
    d.planned_delivery_date,
    d.urgent,
    s.ta
FROM did.vw_task_assignment a
JOIN did.delivery d ON d.delivery_id = a.delivery_id
LEFT JOIN did.study s ON s.study_id = d.study_id
WHERE d.cancelled IS NOT TRUE
  AND d.planned_delivery_date IS NOT NULL
  AND d.planned_delivery_date >= CURRENT_DATE
  AND d.actual_delivery_date IS NULL;

CREATE OR REPLACE VIEW did.vw_capacity_vs_demand AS
SELECT
    w.person_name,
    w.email,
    w.manager,
    w.team,
    w.year_month,
    w.actual_hours,
    160.0 AS assumed_available_hours,
    w.utilization,
    w.study_count,
    w.delivery_count,
    CASE
        WHEN w.utilization < 0.70 THEN 'under-utilized'
        WHEN w.utilization < 0.90 THEN 'healthy'
        WHEN w.utilization <= 1.05 THEN 'high'
        ELSE 'overloaded'
    END AS capacity_band
FROM did.vw_person_monthly_workload w;

CREATE OR REPLACE VIEW did.vw_person_experience AS
SELECT
    a.person_name,
    a.role,
    a.task_kind,
    COALESCE(s.ta, 'Unknown') AS ta,
    COUNT(*) AS task_count,
    COUNT(DISTINCT a.delivery_id) AS delivery_count,
    COUNT(DISTINCT a.study_id) AS study_count
FROM did.vw_task_assignment a
LEFT JOIN did.delivery d ON d.delivery_id = a.delivery_id
LEFT JOIN did.study s ON s.study_id = COALESCE(a.study_id, d.study_id)
GROUP BY a.person_name, a.role, a.task_kind, COALESCE(s.ta, 'Unknown');

CREATE OR REPLACE VIEW did.vw_production_qc_pairing AS
SELECT
    t.production_name,
    t.qc_name,
    COUNT(*) AS task_count,
    COUNT(DISTINCT t.delivery_id) AS delivery_count
FROM did.task t
WHERE t.production_name IS NOT NULL AND btrim(t.production_name) <> ''
  AND t.qc_name IS NOT NULL AND btrim(t.qc_name) <> ''
GROUP BY t.production_name, t.qc_name;

CREATE OR REPLACE VIEW did.vw_on_time_delivery AS
SELECT
    delivery_id,
    study_id,
    status,
    reporting_event,
    planned_delivery_date,
    actual_delivery_date,
    CASE
        WHEN actual_delivery_date IS NULL THEN NULL
        WHEN planned_delivery_date IS NULL THEN NULL
        WHEN actual_delivery_date <= planned_delivery_date THEN TRUE
        ELSE FALSE
    END AS on_time
FROM did.delivery
WHERE cancelled IS NOT TRUE
  AND actual_delivery_date IS NOT NULL;
