INSERT INTO did.business_term (term, definition, calculation, notes) VALUES
('Workload', 'Actual hours recorded for a person during a defined time window.', 'SUM(time_entry.hours) grouped by person and period.', 'Use daily survey hours. Do not treat task count as hours.'),
('Utilization', 'Actual hours divided by assumed available hours.', 'Weekly: actual_hours / 40. Monthly: actual_hours / 160.', 'Capacity calendar is not in source data yet; 40h/week and 160h/month are assumptions. Exclude cancelled deliveries from future views.'),
('Available Hours', 'Working hours minus leave, holiday, training, and admin.', 'Not yet sourced. Assumed 40h per week / 160h per month.', 'When a calendar feed exists, replace the assumption in vw_capacity_vs_demand.'),
('Future workload', 'Open assignments on deliveries whose planned date is still in the future.', 'Rows in vw_person_future_assignments. Hours are not always available, so count tasks/deliveries.', 'Planned hours per task are not in LoT extracts; use due dates and task counts.'),
('Active delivery count', 'Distinct delivery IDs with recorded hours or open future assignments in the window.', 'COUNT(DISTINCT delivery_id)', 'High delivery count with moderate hours indicates context switching.'),
('Active study count', 'Distinct study IDs in the same window.', 'COUNT(DISTINCT study_id)', 'Proxy for context switching.'),
('On-time rate', 'Share of completed deliveries that finished on or before the planned date.', 'COUNT(on_time) FILTER (WHERE on_time) / COUNT(*) on vw_on_time_delivery.', 'Cancelled deliveries are excluded.'),
('Production', 'Programmer who generates the dataset or TLF.', 'task.production_name / assignment role = Production', 'One task typically has Production and QC.'),
('QC', 'Programmer who independently validates the dataset or TLF.', 'task.qc_name / assignment role = QC', 'Do not compare Production hours and QC hours as equivalent effort without context.'),
('Productivity', 'Team operational insight only: completed output relative to hours, not individual performance ranking.', 'Depends on task type; prefer delivery throughput and on-time rate.', 'Never present as a personal performance score.'),
('Stress index', 'Composite risk from utilization, delivery count, and near-term due dates.', 'High utilization + many active deliveries + several due within 14 days.', 'Qualitative in MVP; not a stored numeric column yet.'),
('DID', 'Delivery ID. DID_N is a delivery; DID_0 is the study-level record.', 'delivery.delivery_id / study.study_id', 'Example: C5471001_2 is a delivery under study C5471001.'),
('Study', 'A clinical trial or asset, identified by protocol/study number.', 'study.study_id, often the same as DID_part1 in the survey.', 'SDP work may use request/asset names instead of a protocol number.'),
('Capacity band', 'Monthly utilization class.', '<70% under-utilized; 70-90% healthy; 90-105% high; >105% overloaded.', 'From vw_capacity_vs_demand.')
ON CONFLICT (term) DO UPDATE
SET definition = EXCLUDED.definition,
    calculation = EXCLUDED.calculation,
    notes = EXCLUDED.notes;
