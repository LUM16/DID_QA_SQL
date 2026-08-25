"""Load Source Data CSVs into PostgreSQL (did_qa).

This is the system-of-record load for the DID Q&A agent.
Do not load Neo4j node/relationship CSVs here.

Usage:
  py etl/load_source_to_pg.py
  py etl/load_source_to_pg.py --source "C:\\Neo4j\\Download\\Source Data"
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import tempfile
import time
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
ENV_FILE = ROOT / ".env"
DEFAULT_SOURCE = Path(r"C:\Neo4j\Download\Source Data")
DBGATE = None


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def connect(dbname: str | None = None):
    load_env()
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "10.109.17.64"),
        port=int(os.environ.get("PGPORT", "15432")),
        dbname=dbname or os.environ.get("PGDATABASE", "did_qa"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", ""),
        sslmode=os.environ.get("PGSSLMODE", "prefer"),
    )


def split_sql(text: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("--"):
            continue
        buf.append(line)
        if line.endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
    leftover = "\n".join(buf).strip()
    if leftover:
        statements.append(leftover)
    return statements


def run_sql_file(conn, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    if DBGATE is not None:
        for stmt in split_sql(sql):
            DBGATE.execute(stmt)
        return
    with conn.cursor() as cur:
        for stmt in split_sql(sql):
            cur.execute(stmt)
    conn.commit()


def ensure_database() -> None:
    target = os.environ.get("PGDATABASE", "did_qa")
    admin_db = os.environ.get("PGADMIN_DATABASE", "postgres")
    conn = connect(admin_db)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,))
            if cur.fetchone() is None:
                if not target.replace("_", "").isalnum():
                    raise SystemExit(f"Unsafe database name: {target}")
                cur.execute(f'CREATE DATABASE "{target}"')
                print(f"Created database {target}")
            else:
                print(f"Database {target} already exists")
    finally:
        conn.close()


def parse_hours(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def open_csv(path: Path):
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            fh = path.open("r", encoding=enc, newline="")
            fh.read(2048)
            fh.seek(0)
            return fh
        except UnicodeDecodeError:
            continue
    return path.open("r", encoding="utf-8", errors="replace", newline="")


def copy_rows(conn, table: str, columns: list[str], rows) -> int:
    if DBGATE is not None:
        return copy_rows_dbgate(table, columns, rows)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    count = 0
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
        count += 1
        if count % 50000 == 0:
            print(f"  {table}: {count:,} rows buffered")
    buf.seek(0)
    col_sql = ", ".join(columns)
    with conn.cursor() as cur:
        cur.copy_expert(
            f"COPY {table} ({col_sql}) FROM STDIN WITH (FORMAT csv, NULL '')",
            buf,
        )
    conn.commit()
    return count


def copy_rows_dbgate(table: str, columns: list[str], rows) -> int:
    schema, name = table.split(".", 1)
    tmp = Path(tempfile.gettempdir()) / f"did_load_{name}.csv"
    count = 0
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            count += 1
            if count % 50000 == 0:
                print(f"  {table}: {count:,} rows buffered")
    print(f"  {table}: uploading {count:,} rows ({tmp.stat().st_size / 1_000_000:.1f} MB)")
    remote = DBGATE.upload_file(tmp)
    before = DBGATE.table_count(table)
    DBGATE.import_csv(remote, schema, name)
    deadline = time.time() + 1800
    while time.time() < deadline:
        time.sleep(3)
        now = DBGATE.table_count(table)
        print(f"    {table}: {now:,} / {before + count:,}")
        if now >= before + count:
            break
    else:
        raise RuntimeError(f"Import timeout for {table}: {DBGATE.table_count(table)} rows")
    try:
        tmp.unlink()
    except OSError:
        pass
    return count


def truncate_all(conn) -> None:
    sql = """
            TRUNCATE TABLE
                did.time_entry,
                did.task,
                did.delivery,
                did.study,
                did.person,
                did.stg_survey,
                did.stg_task,
                did.stg_delivery,
                did.stg_study
            RESTART IDENTITY CASCADE
            """
    if DBGATE is not None:
        DBGATE.execute(sql)
        return
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def load_study(conn, source: Path) -> None:
    path = source / "DID_0.csv"
    print(f"Loading {path.name}")
    rows = []
    with open_csv(path) as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            study_id = clean(rec.get("Study or Asset"))
            if not study_id:
                continue
            rows.append(
                (
                    study_id,
                    clean(rec.get("SDSL")),
                    clean(rec.get("SDSL Email")),
                    clean(rec.get("Study TA")),
                    clean(rec.get("Study Phase")),
                    clean(rec.get("Primary Indication")),
                    clean(rec.get("Compound Name")),
                    clean(rec.get("Compound Number")),
                    clean(rec.get("Candidate Code")),
                    clean(rec.get("Study Design")),
                    clean(rec.get("Study or Asset Status")),
                    clean(rec.get("FAP Date")),
                    clean(rec.get("FSFV Date")),
                    clean(rec.get("LSLV Date")),
                    clean(rec.get("Study Database Release Date")),
                    clean(rec.get("Final CSR Date")),
                    clean(rec.get("Reporting System")),
                    clean(rec.get("ID")),
                    clean(rec.get("Business Rationale")),
                )
            )
    n = copy_rows(
        conn,
        "did.stg_study",
        [
            "study_id", "sdsl", "sdsl_email", "ta", "phase", "indication",
            "compound_name", "compound_number", "candidate_code", "study_design",
            "status", "fap_date", "fsfv_date", "lslv_date", "dbr_date",
            "final_csr_date", "reporting_system", "sharepoint_id", "business_rationale",
        ],
        rows,
    )
    print(f"  staged {n:,} study rows")


def load_sdsa_delivery(conn, source: Path) -> list[tuple]:
    path = source / "SDSA DID_clean.csv"
    if not path.exists():
        path = source / "SDSA DID.csv"
    print(f"Loading {path.name}")
    rows = []
    with open_csv(path) as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            delivery_id = clean(rec.get("DID"))
            if not delivery_id:
                continue
            rows.append(
                (
                    delivery_id,
                    clean(rec.get("Study or Asset")),
                    "SDSA",
                    clean(rec.get("DID Status")),
                    clean(rec.get("Reporting Event")),
                    clean(rec.get("Reporting Detail")),
                    None,
                    clean(rec.get("Delivery Content")),
                    clean(rec.get("Draft or Final")),
                    clean(rec.get("Planned Delivery Date")),
                    clean(rec.get("Actual Delivery Date")),
                    clean(rec.get("Quality")),
                    clean(rec.get("Delivery Cancelled?")),
                    clean(rec.get("Urgent Request?")),
                    clean(rec.get("Re-Delivery?")),
                    clean(rec.get("Reason of Re-delivery")),
                    clean(rec.get("Linked DID")),
                    clean(rec.get("SDSL")),
                    clean(rec.get("ID")),
                )
            )
    return rows


def load_sdp_delivery(source: Path) -> list[tuple]:
    path = source / "SDP DID.csv"
    print(f"Loading {path.name}")
    rows = []
    with open_csv(path) as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            delivery_id = clean(rec.get("DID"))
            if not delivery_id:
                continue
            study_name = clean(rec.get("Study Name"))
            asset = clean(rec.get("Asset"))
            request = clean(rec.get("Request Name/Asset or Study Name"))
            if study_name and study_name.lower() not in {"multiple", "na", "n/a"}:
                study_id = study_name
            else:
                study_id = asset or request
            rows.append(
                (
                    delivery_id,
                    study_id,
                    "SDP",
                    clean(rec.get("DID Status")),
                    clean(rec.get("Work Type")),
                    clean(rec.get("Deliverable Detail")),
                    clean(rec.get("Work Type")),
                    None,
                    clean(rec.get("Draft or Final")),
                    clean(rec.get("Planned Delivery Date")),
                    clean(rec.get("Actual Delivery Date")),
                    clean(rec.get("Quality")),
                    clean(rec.get("Delivery Cancelled?")),
                    clean(rec.get("Urgent Request?")),
                    clean(rec.get("Re-Delivery?")),
                    clean(rec.get("Reason for Re-delivery")),
                    clean(rec.get("Linked DID")),
                    clean(rec.get("SDSL")),
                    clean(rec.get("ID")),
                )
            )
    return rows


def load_delivery(conn, source: Path) -> None:
    rows = load_sdsa_delivery(conn, source) + load_sdp_delivery(source)
    n = copy_rows(
        conn,
        "did.stg_delivery",
        [
            "delivery_id", "study_id", "source_system", "status", "reporting_event",
            "reporting_detail", "work_type", "delivery_content", "draft_or_final",
            "planned_delivery_date", "actual_delivery_date", "quality", "cancelled",
            "urgent", "redelivery", "redelivery_reason", "linked_did", "sdsl",
            "sharepoint_id",
        ],
        rows,
    )
    print(f"  staged {n:,} delivery rows")


def load_survey(conn, source: Path) -> None:
    path = source / "survey_data.csv"
    print(f"Loading {path.name} (large)")
    rows = []
    with open_csv(path) as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            hours = parse_hours(rec.get("DIDhr"))
            if hours is None:
                continue
            rows.append(
                (
                    clean(rec.get("Name")),
                    clean(rec.get("Manager")),
                    clean(rec.get("Team")),
                    clean(rec.get("TAlead")),
                    clean(rec.get("sdsaSite")),
                    clean(rec.get("Email")),
                    clean(rec.get("DailySurveyDate")),
                    clean(rec.get("DID")),
                    clean(rec.get("ReportingEvent")),
                    str(hours),
                    clean(rec.get("DID_part1")),
                    clean(rec.get("SDSL")),
                    clean(rec.get("sdslTAlead")),
                    clean(rec.get("Category")),
                )
            )
    n = copy_rows(
        conn,
        "did.stg_survey",
        [
            "person_name", "manager", "team", "ta_lead", "site", "email",
            "entry_date", "delivery_id", "reporting_event", "hours", "study_id",
            "sdsl", "sdsl_ta_lead", "category",
        ],
        rows,
    )
    print(f"  staged {n:,} survey rows")


def load_tasks(conn, source: Path) -> None:
    rows = []
    tlf_path = source / "didTlf.csv"
    print(f"Loading {tlf_path.name}")
    with open_csv(tlf_path) as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            delivery_id = clean(rec.get("Title"))
            if not delivery_id:
                continue
            rows.append(
                (
                    delivery_id,
                    "TLF",
                    clean(rec.get("LType")),
                    clean(rec.get("LTitle")),
                    clean(rec.get("LSource")),
                    clean(rec.get("LFile")),
                    clean(rec.get("LNumber")),
                    clean(rec.get("LProd")),
                    clean(rec.get("LQC")),
                )
            )
    data_path = source / "didData.csv"
    print(f"Loading {data_path.name}")
    with open_csv(data_path) as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            delivery_id = clean(rec.get("Title"))
            if not delivery_id:
                continue
            rows.append(
                (
                    delivery_id,
                    "DATA",
                    clean(rec.get("DType")),
                    clean(rec.get("DDataset")),
                    clean(rec.get("DDataset")),
                    None,
                    None,
                    clean(rec.get("DProd")),
                    clean(rec.get("DQC")),
                )
            )
    n = copy_rows(
        conn,
        "did.stg_task",
        [
            "delivery_id", "task_kind", "task_type", "task_name", "dataset",
            "file_name", "tlf_number", "production_name", "qc_name",
        ],
        rows,
    )
    print(f"  staged {n:,} task rows")


def transform(conn) -> None:
    print("Building curated tables")
    sql = """
    CREATE INDEX IF NOT EXISTS idx_stg_survey_email ON did.stg_survey (lower(email));
    CREATE INDEX IF NOT EXISTS idx_stg_survey_did ON did.stg_survey (delivery_id);
    CREATE INDEX IF NOT EXISTS idx_stg_task_did ON did.stg_task (delivery_id);

    INSERT INTO did.person (person_name, email, manager, team, ta_lead, site)
    SELECT DISTINCT ON (COALESCE(lower(email), lower(person_name)))
        person_name, email, manager, team, ta_lead, site
    FROM did.stg_survey
    WHERE person_name IS NOT NULL
    ORDER BY COALESCE(lower(email), lower(person_name)), email NULLS LAST;

    INSERT INTO did.person (person_name)
    SELECT DISTINCT name
    FROM (
        SELECT production_name AS name FROM did.stg_task
        UNION
        SELECT qc_name FROM did.stg_task
    ) x
    WHERE name IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM did.person p
          WHERE lower(p.person_name) = lower(x.name)
      );

    INSERT INTO did.study (
        study_id, sdsl, sdsl_email, ta, phase, indication, compound_name,
        compound_number, candidate_code, study_design, status, fap_date,
        fsfv_date, lslv_date, dbr_date, final_csr_date, reporting_system,
        sharepoint_id, business_rationale
    )
    SELECT DISTINCT ON (study_id)
        study_id, sdsl, sdsl_email, ta, phase, indication, compound_name,
        compound_number, candidate_code, study_design, status,
        CASE WHEN fap_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(fap_date, 10)::date WHEN fap_date ~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}' THEN to_date(fap_date, 'MM/DD/YYYY') ELSE NULL END,
        CASE WHEN fsfv_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(fsfv_date, 10)::date WHEN fsfv_date ~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}' THEN to_date(fsfv_date, 'MM/DD/YYYY') ELSE NULL END,
        CASE WHEN lslv_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(lslv_date, 10)::date WHEN lslv_date ~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}' THEN to_date(lslv_date, 'MM/DD/YYYY') ELSE NULL END,
        CASE WHEN dbr_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(dbr_date, 10)::date WHEN dbr_date ~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}' THEN to_date(dbr_date, 'MM/DD/YYYY') ELSE NULL END,
        CASE WHEN final_csr_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(final_csr_date, 10)::date WHEN final_csr_date ~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}' THEN to_date(final_csr_date, 'MM/DD/YYYY') ELSE NULL END,
        reporting_system, sharepoint_id, business_rationale
    FROM did.stg_study
    WHERE study_id IS NOT NULL
    ORDER BY study_id;

    INSERT INTO did.study (study_id)
    SELECT DISTINCT study_id
    FROM did.stg_delivery
    WHERE study_id IS NOT NULL
      AND study_id NOT IN (SELECT study_id FROM did.study);

    INSERT INTO did.delivery (
        delivery_id, study_id, source_system, status, reporting_event,
        reporting_detail, work_type, delivery_content, draft_or_final,
        planned_delivery_date, actual_delivery_date, quality, cancelled,
        urgent, redelivery, redelivery_reason, linked_did, sdsl, sharepoint_id
    )
    SELECT DISTINCT ON (delivery_id)
        delivery_id, study_id, source_system, status, reporting_event,
        reporting_detail, work_type, delivery_content, draft_or_final,
        CASE
            WHEN planned_delivery_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(planned_delivery_date, 10)::date
            WHEN planned_delivery_date ~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}' THEN to_date(planned_delivery_date, 'MM/DD/YYYY')
            ELSE NULL
        END,
        CASE
            WHEN actual_delivery_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(actual_delivery_date, 10)::date
            WHEN actual_delivery_date ~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}' THEN to_date(actual_delivery_date, 'MM/DD/YYYY')
            ELSE NULL
        END,
        quality,
        CASE lower(coalesce(cancelled, '')) WHEN 'true' THEN TRUE WHEN 'yes' THEN TRUE WHEN 'false' THEN FALSE WHEN 'no' THEN FALSE ELSE NULL END,
        CASE lower(coalesce(urgent, '')) WHEN 'true' THEN TRUE WHEN 'yes' THEN TRUE WHEN 'false' THEN FALSE WHEN 'no' THEN FALSE ELSE NULL END,
        CASE lower(coalesce(redelivery, '')) WHEN 'true' THEN TRUE WHEN 'yes' THEN TRUE WHEN 'false' THEN FALSE WHEN 'no' THEN FALSE ELSE NULL END,
        redelivery_reason, linked_did, sdsl, sharepoint_id
    FROM did.stg_delivery
    WHERE delivery_id IS NOT NULL
    ORDER BY delivery_id, source_system;

    INSERT INTO did.delivery (delivery_id, study_id, source_system)
    SELECT DISTINCT delivery_id, study_id, 'SURVEY'
    FROM did.stg_survey
    WHERE delivery_id IS NOT NULL
      AND delivery_id NOT IN (SELECT delivery_id FROM did.delivery);

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
    WHERE NULLIF(s.hours, '') IS NOT NULL;

    DELETE FROM did.time_entry WHERE entry_date IS NULL;

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
    if DBGATE is not None:
        for stmt in split_sql(sql):
            preview = " ".join(stmt.split()[0:6])
            if "INSERT INTO did.time_entry" in stmt:
                print("  transform: time_entry by year")
                for year in ("2024", "2025", "2026"):
                    chunk = stmt.rstrip(";") + f"\n AND left(coalesce(s.entry_date,''), 4) = '{year}';"
                    print(f"    year {year}")
                    DBGATE.execute(chunk, timeout=900)
                continue
            print(f"  transform: {preview}")
            DBGATE.execute(stmt, timeout=900)
        return
    with conn.cursor() as cur:
        for stmt in split_sql(sql):
            cur.execute(stmt)
    conn.commit()


def print_counts(conn) -> None:
    tables = (
        "did.person",
        "did.study",
        "did.delivery",
        "did.time_entry",
        "did.task",
    )
    if DBGATE is not None:
        for table in tables:
            print(f"  {table}: {DBGATE.table_count(table):,}")
        return
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT count(*) FROM {table}")
            print(f"  {table}: {cur.fetchone()[0]:,}")


def main() -> int:
    global DBGATE
    parser = argparse.ArgumentParser(description="Load DID Source Data into PostgreSQL")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Source Data folder")
    parser.add_argument("--skip-create-db", action="store_true")
    parser.add_argument(
        "--via-dbgate",
        action="store_true",
        help="Load through DbGate HTTP on port 3000 when PostgreSQL is firewalled",
    )
    args = parser.parse_args()
    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"Source folder not found: {source}")

    load_env()
    if not os.environ.get("PGPASSWORD"):
        raise SystemExit("PGPASSWORD is not set. Add it to .env before loading.")

    conn = None
    if args.via_dbgate:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from dbgate_client import DbGate

        DBGATE = DbGate()
        login = os.environ.get("DBGATE_LOGIN") or os.environ.get("PGUSER") or "postgre"
        print(f"Using DbGate SQL proxy as {login}")
        DBGATE.login(login, os.environ["PGPASSWORD"])
        if not args.skip_create_db:
            DBGATE.ensure_database()
            print(f"Database {DBGATE.database} ready")
    else:
        if not args.skip_create_db:
            try:
                ensure_database()
            except Exception as exc:  # noqa: BLE001
                print(f"Could not auto-create database (run sql/01_create_database.sql in pgManage): {exc}")
        conn = connect()
    try:
        for name in ("02_schema.sql", "03_views.sql", "04_glossary.sql"):
            print(f"Applying {name}")
            run_sql_file(conn, SQL_DIR / name)
        truncate_all(conn)
        load_study(conn, source)
        load_delivery(conn, source)
        load_survey(conn, source)
        load_tasks(conn, source)
        transform(conn)
        print("Row counts:")
        print_counts(conn)
        print("Load complete.")
        return 0
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
