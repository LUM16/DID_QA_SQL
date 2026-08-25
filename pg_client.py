"""PostgreSQL read-only helpers for the DID Q&A agent."""

from __future__ import annotations

import os
import re
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config import load_env

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|CALL|DO|EXECUTE|VACUUM|ANALYZE|COMMENT|LOAD)\b",
    re.IGNORECASE,
)

SCHEMA_FOR_LLM = """
PostgreSQL schema `did` (read-only). Prefer views over base tables.

Current date for relative windows: use CURRENT_DATE / CURRENT_TIMESTAMP.

Tables:
- did.person(person_id, person_name, email, ntid, manager, team, ta_lead, site, status)
- did.study(study_id, sdsl, sdsl_email, ta, phase, indication, compound_name, compound_number, candidate_code, study_design, status, fap_date, fsfv_date, lslv_date, dbr_date, final_csr_date, reporting_system, sharepoint_id, business_rationale)
- did.delivery(delivery_id, study_id, source_system, status, reporting_event, reporting_detail, work_type, delivery_content, draft_or_final, planned_delivery_date, actual_delivery_date, quality, cancelled, urgent, redelivery, redelivery_reason, linked_did, sdsl, sharepoint_id)
- did.time_entry(time_entry_id, person_id, entry_date, delivery_id, study_id, hours, reporting_event, category, source_system)
- did.task(task_id, delivery_id, study_id, task_kind, task_type, task_name, dataset, file_name, tlf_number, production_name, qc_name)
- did.business_term(term, definition, calculation, notes)

Views (use these for metrics):
- did.vw_person_weekly_workload(person_id, person_name, email, manager, team, ta_lead, site, week_start, actual_hours, delivery_count, study_count, days_worked, utilization)
  utilization = actual_hours / 40
- did.vw_person_monthly_workload(..., year_month 'YYYY-MM', month_start, actual_hours, delivery_count, study_count, days_worked, utilization)
  utilization = actual_hours / 160
- did.vw_delivery_hours(delivery_id, study_id, source_system, status, reporting_event, work_type, draft_or_final, planned_delivery_date, actual_delivery_date, quality, cancelled, urgent, ta, phase, actual_hours, people_count, days_with_hours)
- did.vw_study_hours(study_id, ta, phase, indication, study_status, sdsl, actual_hours, people_count, delivery_count)
- did.vw_person_delivery_hours(person_name, email, manager, team, site, delivery_id, study_id, reporting_event, delivery_status, planned_delivery_date, actual_hours, first_entry_date, last_entry_date)
- did.vw_future_delivery(delivery_id, study_id, status, reporting_event, work_type, planned_delivery_date, actual_delivery_date, urgent, cancelled, ta, phase, sdsl, days_until_due)
- did.vw_person_future_assignments(person_name, role, task_kind, task_type, task_name, delivery_id, study_id, delivery_status, reporting_event, planned_delivery_date, urgent, ta)
- did.vw_capacity_vs_demand(person_name, email, manager, team, year_month, actual_hours, assumed_available_hours, utilization, study_count, delivery_count, capacity_band)
  capacity_band: under-utilized <0.70, healthy 0.70-0.90, high 0.90-1.05, overloaded >1.05
- did.vw_person_experience(person_name, role, task_kind, ta, task_count, delivery_count, study_count)
- did.vw_task_assignment(task_id, delivery_id, study_id, task_kind, task_type, task_name, dataset, file_name, tlf_number, role, person_name)
  role is Production or QC
- did.vw_production_qc_pairing(production_name, qc_name, task_count, delivery_count)
- did.vw_on_time_delivery(delivery_id, study_id, status, reporting_event, planned_delivery_date, actual_delivery_date, on_time)

Identifiers:
- study_id example: C1071007
- delivery_id (DID) example: C1071007_2
- task_kind: TLF or DATA
- source_system: SDSA or SDP
Never query did.stg_* tables.
""".strip()


def pg_configured() -> bool:
    load_env()
    return bool(os.environ.get("PGPASSWORD") or os.environ.get("PGHOST"))


def get_conn():
    load_env()
    password = os.environ.get("PGPASSWORD")
    if not password:
        raise ValueError("PGPASSWORD is not set (use Connect Vars or .env).")
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "10.109.17.64"),
        port=int(os.environ.get("PGPORT", "15432")),
        dbname=os.environ.get("PGDATABASE", "did_qa"),
        user=os.environ.get("PGUSER", "postgres"),
        password=password,
        sslmode=os.environ.get("PGSSLMODE", "prefer"),
        connect_timeout=15,
    )


def connection_summary() -> str:
    load_env()
    host = os.environ.get("PGHOST", "10.109.17.64")
    port = os.environ.get("PGPORT", "15432")
    db = os.environ.get("PGDATABASE", "did_qa")
    via = " via DbGate:3000" if os.environ.get("PG_VIA_DBGATE") == "1" else ""
    return f"{host}:{port}/{db}{via}"


def _dbgate():
    load_env()
    from pathlib import Path
    import sys

    etl = str(Path(__file__).resolve().parent / "etl")
    if etl not in sys.path:
        sys.path.insert(0, etl)
    from dbgate_client import DbGate

    client = getattr(_dbgate, "_client", None)
    if client is None:
        client = DbGate()
        login = os.environ.get("DBGATE_LOGIN") or os.environ.get("PGUSER") or "postgre"
        password = os.environ.get("PGPASSWORD")
        if not password:
            raise ValueError("PGPASSWORD is not set (use Connect Vars or .env).")
        client.login(login, password)
        _dbgate._client = client  # type: ignore[attr-defined]
    return client


def ensure_read_only(query: str) -> None:
    stripped = query.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Only one SQL statement is allowed.")
    if FORBIDDEN.search(stripped):
        raise ValueError("Only read-only SELECT/WITH queries are allowed.")
    if not re.match(r"^(WITH|SELECT|EXPLAIN)\b", stripped, re.IGNORECASE):
        raise ValueError("SQL must start with SELECT or WITH.")


def run_sql(query: str, limit_rows: int = 200) -> list[dict[str, Any]]:
    ensure_read_only(query)
    load_env()
    if os.environ.get("PG_VIA_DBGATE") == "1":
        return _dbgate().query(query, limit_rows=limit_rows)

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            if cur.description is None:
                return []
            rows = cur.fetchmany(limit_rows)
            return [dict(r) for r in rows]
    finally:
        conn.close()


def ping() -> dict[str, Any]:
    load_env()
    if os.environ.get("PG_VIA_DBGATE") == "1":
        rows = _dbgate().query(
            """
            SELECT
                (SELECT count(*) FROM did.person) AS person_count,
                (SELECT count(*) FROM did.study) AS study_count,
                (SELECT count(*) FROM did.delivery) AS delivery_count,
                (SELECT count(*) FROM did.time_entry) AS time_entry_count,
                (SELECT count(*) FROM did.task) AS task_count
            """
        )
        row = rows[0] if rows else {}
        return {
            "person_count": row.get("person_count"),
            "study_count": row.get("study_count"),
            "delivery_count": row.get("delivery_count"),
            "time_entry_count": row.get("time_entry_count"),
            "task_count": row.get("task_count"),
        }

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT count(*) FROM did.person) AS person_count,
                    (SELECT count(*) FROM did.study) AS study_count,
                    (SELECT count(*) FROM did.delivery) AS delivery_count,
                    (SELECT count(*) FROM did.time_entry) AS time_entry_count,
                    (SELECT count(*) FROM did.task) AS task_count
                """
            )
            row = cur.fetchone()
            return {
                "person_count": row[0],
                "study_count": row[1],
                "delivery_count": row[2],
                "time_entry_count": row[3],
                "task_count": row[4],
            }
    finally:
        conn.close()
