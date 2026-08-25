# DID Free-text Q&A (RSC)

Workforce / delivery / task intelligence agent for SDSA programming operations.

This follows the Copilot design in *DID Agent Discussion*: **PostgreSQL is the system of record**, Neo4j is the relationship layer, and the agent uses **NL2SQL + optional Cypher + a fixed metric glossary**. Phase 1 (this folder) is a controlled SQL-first chat app for Posit Connect.

## What this agent answers

- Historical workload: hours by person / study / delivery / week / month
- Utilization bands (assumed 40h week / 160h month until a calendar feed exists)
- Delivery and study status, on-time completions
- Future assignments from LoT Production/QC names and planned dates
- Production/QC pairing and experience counts
- Graph questions (collaboration paths) still go to Neo4j when needed

It does **not** chat with raw Excel. Excel/CSV is ingested into governed tables and views first.

## Architecture

```
User free-text
    → Intent router (sql | cypher | both | glossary)
        → PostgreSQL views   (hours, rankings, due dates)
        → Neo4j Cypher       (relationship / network)
        → Business glossary  (metric definitions)
    → Answer composer (Vox GenAI)
```

## Data recommendation

**Load Source Data into PostgreSQL. Keep Data Preprocessing for Neo4j.**

| Folder | Role |
|--------|------|
| `C:\Neo4j\Download\Source Data` | **Use for PostgreSQL.** These are the operational facts: study master (`DID_0.csv`), deliveries (`SDSA DID_clean.csv`, `SDP DID.csv`), daily hours (`survey_data.csv`), LoT tasks (`didTlf.csv`, `didData.csv`). |
| `C:\Neo4j\Download\Data Preprocessing` | **Keep for Neo4j load.** Node/relationship CSVs are a graph projection. Putting them into PostgreSQL would store edges as tables and make `SUM(hours)` harder, not easier. |

Do not load both copies of the same facts into PostgreSQL. Optional exception: `Node_Person.csv` is a cleaner person master (NTID, site, status) if you want to enrich `did.person` later.

### What is loaded into PostgreSQL

| Source file | Destination |
|-------------|-------------|
| `DID_0.csv` | `did.study` |
| `SDSA DID_clean.csv` + `SDP DID.csv` | `did.delivery` |
| `survey_data.csv` | `did.person` + `did.time_entry` |
| `didTlf.csv` + `didData.csv` | `did.task` (+ `did.vw_task_assignment`) |

Not loaded in MVP: accomplishment extracts (`csr_VA_*`, `std_VA_*`, …), BID/task-force files, Archive lists. Those can be added as extra fact tables later.

## Neo4j: what you can drop

After PostgreSQL owns hours and task assignments, Neo4j only needs **Person / Study / Delivery** and a few relationships.

**Safe to remove from Neo4j (facts belong in SQL):**

- `DeliverySurvey`, `StudySurvey` nodes
- Daily survey relationships (`rel_Person_*_Daily_Survey_*`)
- Granular `TLF` / `Data` catalog nodes and `rel_Delivery_TLF*` / `rel_Delivery_Data` (133k+ TLF nodes)
- `rel_Person_accomplishment`
- `rel_Delivery_Unblind` (store as a delivery flag in SQL instead)

**Optional to remove if you will not ask BID questions in the graph:**

- `Task_Force`, `BID_0`, `BID_Cat` and their relationships

**Keep:**

- `Person`, `Study`, `Delivery`
- Study → Delivery
- A **summary** Person → Delivery edge (not daily hours)

Count first, backup first. See `sql/neo4j_prune_counts.cypher`. Do not delete until PostgreSQL load is verified.

## PostgreSQL info needed to connect from this app / RSC

The screenshot is **pgManage** on `http://10.109.17.64:3000` (web UI). The app talks to PostgreSQL on the **database port** `15432`, not 3000.

Please send (or put in `.env` / Connect Vars):

| Item | Likely value from screenshot | Notes |
|------|------------------------------|--------|
| Host | `10.109.17.64` | Same VM as Neo4j / pgManage |
| Port | `15432` | Mapped PostgreSQL port (not 3000) |
| Database | create `did_qa` | Do **not** use the `postgres` system DB. `testdb` is OK for a trial. |
| User | `postgres` | Prefer a read-only role for the app later |
| Password | *(you have this in pgManage)* | Required |
| SSL mode | `prefer` or `disable` | Internal network often `disable` / `prefer` |
| RSC reachability | Connect server → `10.109.17.64:15432` | Same firewall pattern as Neo4j Bolt `7687` |

Local `.env` keys: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`.

## Load data (high level)

pgManage **cannot** `COPY` files from your Windows laptop onto the Linux server. Run SQL in pgManage, then load CSVs with the Python ETL from this machine.

1. In pgManage, connect as `postgres`.
2. Open a query on the `postgres` database and run `sql/01_create_database.sql` (`CREATE DATABASE did_qa;`).
3. Switch the session to `did_qa` (or add a connection to `did_qa`). You do **not** have to paste `02`–`04` by hand; the loader applies them.
4. Copy `.env.example` to `.env`. Set `PGPASSWORD` (and Vox / Neo4j if you want the chat app).
5. From this folder:

```cmd
py -m pip install -r requirements.txt
py etl/load_source_to_pg.py
```

6. In pgManage, refresh `did_qa`. You should see schema `did` with tables and `vw_*` views.
7. Start the app: `start-local.bat` or `py -m streamlit run app.py`.

Expected volume (approximate): ~2k studies, ~14k deliveries, ~500k time-entry rows, ~470k tasks. First load may take several minutes.

Re-running the loader **truncates** curated + staging tables and reloads.

## SQL objects

- `sql/01_create_database.sql` — create `did_qa`
- `sql/02_schema.sql` — staging + `person` / `study` / `delivery` / `time_entry` / `task`
- `sql/03_views.sql` — metric layer (`vw_person_weekly_workload`, `vw_capacity_vs_demand`, …)
- `sql/04_glossary.sql` — metric definitions

The agent is instructed to query **views**, not `stg_*` tables, and only `SELECT`/`WITH`.

## Local run

```cmd
cd "C:\Users\lum16\Documents\Neo4j\DID Agent\rsc-app2"
copy .env.example .env
notepad .env
start-local.bat
```

Open http://127.0.0.1:8501

Example questions:

- Who had the highest workload last month?
- What did study C1071007 consume in hours?
- Who is assigned to deliveries due in the next 4 weeks?
- What is utilization?
- Who is often paired as Production/QC?

## Deploy to Posit Connect

See [`GITHUB_DEPLOY.md`](GITHUB_DEPLOY.md). GitHub repo: `https://github.com/LUM16/DID_QA_SQL`. Import from Git on Connect as a **new** content item. Set PostgreSQL, Neo4j, and Vox Vars. Never upload `.env`.

## Security

- App queries are read-only (SQL and Cypher validators).
- Utilization uses assumed capacity until a calendar table exists; answers should say so.
- Do not treat hours or utilization as individual performance scores.
