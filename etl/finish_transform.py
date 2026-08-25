"""Resume curated-table build after staging load (skip already-filled person/study/delivery)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dbgate_client import DbGate, load_env  # noqa: E402


TIME_ENTRY_SQL = """
INSERT INTO did.time_entry (person_id, entry_date, delivery_id, study_id, hours, reporting_event, category)
SELECT
    p.person_id,
    CASE
        WHEN s.entry_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(s.entry_date, 10)::date
        WHEN s.entry_date ~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}' THEN to_date(s.entry_date, 'MM/DD/YYYY')
        ELSE NULL
    END,
    s.delivery_id,
    s.study_id,
    NULLIF(s.hours, '')::numeric,
    s.reporting_event,
    s.category
FROM did.stg_survey s
JOIN did.person p
  ON s.email IS NOT NULL AND lower(p.email) = lower(s.email)
WHERE NULLIF(s.hours, '') IS NOT NULL
  AND left(coalesce(s.entry_date,''), 4) = '{year}';
"""

TASK_SQL = """
INSERT INTO did.task (
    delivery_id, study_id, task_kind, task_type, task_name, dataset,
    file_name, tlf_number, production_name, qc_name
)
SELECT
    t.delivery_id,
    d.study_id,
    t.task_kind,
    t.task_type,
    t.task_name,
    t.dataset,
    t.file_name,
    t.tlf_number,
    t.production_name,
    t.qc_name
FROM did.stg_task t
LEFT JOIN did.delivery d ON d.delivery_id = t.delivery_id;
"""


def main() -> int:
    env = load_env()
    client = DbGate()
    client.login(env.get("PGUSER") or "postgre", env["PGPASSWORD"])
    for table in (
        "did.person",
        "did.study",
        "did.delivery",
        "did.time_entry",
        "did.task",
        "did.stg_survey",
        "did.stg_task",
    ):
        print(f"{table}: {client.table_count(table):,}")

    if client.table_count("did.time_entry") == 0:
        for year in ("2024", "2025", "2026"):
            print(f"time_entry {year}")
            try:
                client.execute(TIME_ENTRY_SQL.format(year=year), timeout=900)
            except Exception as exc:  # noqa: BLE001
                print(f"  failed: {exc}")
                return 1
            print(f"  now {client.table_count('did.time_entry'):,}")
        print("delete null dates")
        client.execute("DELETE FROM did.time_entry WHERE entry_date IS NULL;")

    if client.table_count("did.task") == 0:
        print("loading tasks")
        client.execute(TASK_SQL, timeout=900)

    print("final counts:")
    for table in ("did.person", "did.study", "did.delivery", "did.time_entry", "did.task"):
        print(f"  {table}: {client.table_count(table):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
