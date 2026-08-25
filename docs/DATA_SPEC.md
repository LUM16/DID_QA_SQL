# DID Q&A PostgreSQL data spec

System of record: database `did_qa`, schema `did`.  
Source folder: `C:\Neo4j\Download\Source Data`.  
Loader: `etl/load_source_to_pg.py` (staging → typed tables → views).

This load **does** clean and reshape the CSVs. It does not copy files 1:1.

| Rule | What happens |
|------|----------------|
| Empty / `nan` / `none` / `null` | Stored as SQL `NULL` |
| Dates | Keep `YYYY-MM-DD`; parse `MM/DD/YYYY`; otherwise `NULL` |
| Booleans (`cancelled`, `urgent`, `redelivery`) | `true`/`yes` → `TRUE`; `false`/`no` → `FALSE`; else `NULL` |
| Hours (`DIDhr`) | Strip commas; skip the row if not numeric |
| Keys | `DISTINCT ON` study / delivery / person so duplicates collapse |
| SDSA vs SDP same `DID` | One row kept; `ORDER BY delivery_id, source_system` so **SDP wins** over SDSA |
| Survey hours join | `time_entry` only for survey rows whose **email** matches `did.person` |
| Agent | Queries curated tables and `vw_*` views. Do not query `stg_*`. |

Loaded instance (Aug 2026): `person` 2,807 · `study` 1,716 · `delivery` 16,498 · `time_entry` 507,256 · `task` 442,660.

`SDSA DID_clean.csv` was not in the source folder at load time; the loader used **`SDSA DID.csv`**.

---

## 1. Source files → PostgreSQL objects

| Source file | Loaded? | Staging | Curated tables |
|-------------|---------|---------|----------------|
| `DID_0.csv` | Yes | `did.stg_study` | `did.study` |
| `SDSA DID.csv` | Yes | `did.stg_delivery` | `did.delivery` (`source_system = 'SDSA'`) |
| `SDP DID.csv` | Yes | `did.stg_delivery` | `did.delivery` (`source_system = 'SDP'`) |
| `survey_data.csv` | Yes | `did.stg_survey` | `did.person`, `did.time_entry`; extra `did.delivery` rows with `source_system = 'SURVEY'` |
| `didTlf.csv` | Yes | `did.stg_task` | `did.task` (`task_kind = 'TLF'`); extra `did.person` names |
| `didData.csv` | Yes | `did.stg_task` | `did.task` (`task_kind = 'DATA'`); extra `did.person` names |
| `SDP DID_0.csv` | No | — | — |
| `Archive SDSA DID.csv` | No | — | — |
| `csr_VA_*` / `std_VA_*` / `esub_VA_*` / `sda_VA_*` | No | — | — |
| BID / iPort / study-tracker Excel | No | — | — |

`did.business_term` is **not** from Source Data. It is seeded by `sql/04_glossary.sql`.

---

## 2. Tables the agent uses

| Object | Kind | Role |
|--------|------|------|
| `did.study` | table | Study / asset master |
| `did.delivery` | table | SDSA + SDP deliveries (plus survey-only DIDs) |
| `did.person` | table | People from daily survey, plus LoT Production/QC names |
| `did.time_entry` | table | One row per person-day-DID hours |
| `did.task` | table | LoT TLF and dataset assignments |
| `did.business_term` | table | Metric glossary |
| `did.vw_*` | views | Preferred metric layer for NL2SQL |
| `did.stg_*` | tables | Load-only. Not for Q&A. |

---

## 3. Column lineage

### 3.1 `did.study`

Primary source: `DID_0.csv`. Extra `study_id`-only rows are added from deliveries whose study is missing in `DID_0`.

| PG column | Type | Source file | Source column | Transform |
|-----------|------|-------------|----------------|-----------|
| `study_id` | TEXT PK | `DID_0.csv` | `Study or Asset` | Skip blank; `DISTINCT ON (study_id)` |
| `sdsl` | TEXT | `DID_0.csv` | `SDSL` | Trim / null |
| `sdsl_email` | TEXT | `DID_0.csv` | `SDSL Email` | Trim / null |
| `ta` | TEXT | `DID_0.csv` | `Study TA` | Trim / null |
| `phase` | TEXT | `DID_0.csv` | `Study Phase` | Trim / null |
| `indication` | TEXT | `DID_0.csv` | `Primary Indication` | Trim / null |
| `compound_name` | TEXT | `DID_0.csv` | `Compound Name` | Trim / null |
| `compound_number` | TEXT | `DID_0.csv` | `Compound Number` | Trim / null |
| `candidate_code` | TEXT | `DID_0.csv` | `Candidate Code` | Trim / null |
| `study_design` | TEXT | `DID_0.csv` | `Study Design` | Trim / null |
| `status` | TEXT | `DID_0.csv` | `Study or Asset Status` | Trim / null |
| `fap_date` | DATE | `DID_0.csv` | `FAP Date` | Date parse |
| `fsfv_date` | DATE | `DID_0.csv` | `FSFV Date` | Date parse |
| `lslv_date` | DATE | `DID_0.csv` | `LSLV Date` | Date parse |
| `dbr_date` | DATE | `DID_0.csv` | `Study Database Release Date` | Date parse |
| `final_csr_date` | DATE | `DID_0.csv` | `Final CSR Date` | Date parse |
| `reporting_system` | TEXT | `DID_0.csv` | `Reporting System` | Trim / null |
| `sharepoint_id` | TEXT | `DID_0.csv` | `ID` | SharePoint list item ID |
| `business_rationale` | TEXT | `DID_0.csv` | `Business Rationale` | Trim / null |

Gap-fill `INSERT`: `study_id` from `SDSA DID.csv`.`Study or Asset` or SDP study-name logic (below), if not already in `did.study`. Other study attributes stay NULL on those rows.

**Not loaded from `DID_0.csv`:** PoC names/emails, OneSource flags, SIGMA migration, Nexus flags, iPort site flags, `DID_N Link`, `LoT Folder`, and other operational columns.

---

### 3.2 `did.delivery`

Union of SDSA + SDP, then `DISTINCT ON (delivery_id)`. Then survey DIDs that are not already present.

#### From `SDSA DID.csv` (`source_system = 'SDSA'`)

| PG column | Type | Source column | Transform |
|-----------|------|----------------|-----------|
| `delivery_id` | TEXT PK | `DID` | Skip blank |
| `study_id` | TEXT | `Study or Asset` | Trim / null |
| `source_system` | TEXT | — | Literal `SDSA` |
| `status` | TEXT | `DID Status` | Trim / null |
| `reporting_event` | TEXT | `Reporting Event` | Trim / null |
| `reporting_detail` | TEXT | `Reporting Detail` | Trim / null |
| `work_type` | TEXT | — | Always `NULL` for SDSA |
| `delivery_content` | TEXT | `Delivery Content` | Trim / null |
| `draft_or_final` | TEXT | `Draft or Final` | Trim / null |
| `planned_delivery_date` | DATE | `Planned Delivery Date` | Date parse |
| `actual_delivery_date` | DATE | `Actual Delivery Date` | Date parse |
| `quality` | TEXT | `Quality` | Trim / null |
| `cancelled` | BOOLEAN | `Delivery Cancelled?` | Yes/true / no/false |
| `urgent` | BOOLEAN | `Urgent Request?` | Yes/true / no/false |
| `redelivery` | BOOLEAN | `Re-Delivery?` | Yes/true / no/false |
| `redelivery_reason` | TEXT | `Reason of Re-delivery` | Trim / null |
| `linked_did` | TEXT | `Linked DID` | Trim / null |
| `sdsl` | TEXT | `SDSL` | Trim / null |
| `sharepoint_id` | TEXT | `ID` | SharePoint list item ID |

#### From `SDP DID.csv` (`source_system = 'SDP'`)

| PG column | Type | Source column | Transform |
|-----------|------|----------------|-----------|
| `delivery_id` | TEXT PK | `DID` | Skip blank |
| `study_id` | TEXT | `Study Name` / `Asset` / `Request Name/Asset or Study Name` | If `Study Name` is present and not `multiple`/`na`/`n/a`, use it; else `Asset`; else request name |
| `source_system` | TEXT | — | Literal `SDP` |
| `status` | TEXT | `DID Status` | Trim / null |
| `reporting_event` | TEXT | `Work Type` | Same source as `work_type` |
| `reporting_detail` | TEXT | `Deliverable Detail` | Trim / null |
| `work_type` | TEXT | `Work Type` | Trim / null |
| `delivery_content` | TEXT | — | Always `NULL` for SDP |
| `draft_or_final` | TEXT | `Draft or Final` | Trim / null |
| `planned_delivery_date` | DATE | `Planned Delivery Date` | Date parse |
| `actual_delivery_date` | DATE | `Actual Delivery Date` | Date parse |
| `quality` | TEXT | `Quality` | Trim / null |
| `cancelled` | BOOLEAN | `Delivery Cancelled?` | Yes/true / no/false |
| `urgent` | BOOLEAN | `Urgent Request?` | Yes/true / no/false |
| `redelivery` | BOOLEAN | `Re-Delivery?` | Yes/true / no/false |
| `redelivery_reason` | TEXT | `Reason for Re-delivery` | Note: SDSA column name is `Reason of Re-delivery` |
| `linked_did` | TEXT | `Linked DID` | Trim / null |
| `sdsl` | TEXT | `SDSL` | Trim / null |
| `sharepoint_id` | TEXT | `ID` | SharePoint list item ID |

#### Survey-only deliveries

If `survey_data.csv`.`DID` is not already in `did.delivery`: insert `delivery_id`, `study_id` from `DID_part1`, `source_system = 'SURVEY'`. Other delivery attributes stay NULL.

**Not loaded from DID extracts:** unblinded programming, resource distribution, snapshot date, approval workflow, PoCs, LoT folder, quality issue description, exception request, duplicated study attributes on the DID list (TA/phase/compound on SDSA DID — those live on `did.study` from `DID_0.csv`).

---

### 3.3 `did.person`

| PG column | Type | Source file | Source column | Transform |
|-----------|------|-------------|----------------|-----------|
| `person_id` | BIGSERIAL PK | — | — | Generated |
| `person_name` | TEXT | `survey_data.csv` | `Name` | Required; `DISTINCT ON (lower(email) or lower(name))` |
| `email` | TEXT | `survey_data.csv` | `Email` | Person key when present |
| `ntid` | TEXT | — | — | **Not loaded** (schema reserved) |
| `manager` | TEXT | `survey_data.csv` | `Manager` | From survey row that won DISTINCT |
| `team` | TEXT | `survey_data.csv` | `Team` | |
| `ta_lead` | TEXT | `survey_data.csv` | `TAlead` | |
| `site` | TEXT | `survey_data.csv` | `sdsaSite` | |
| `status` | TEXT | — | — | **Not loaded** |

Additional people: distinct `LProd`/`LQC` (`didTlf.csv`) and `DProd`/`DQC` (`didData.csv`) whose name is not already in `did.person` (case-insensitive). Those rows have **name only** (no email/manager/team/site).

---

### 3.4 `did.time_entry`

Source: `survey_data.csv` via `did.stg_survey`. Rows with non-numeric `DIDhr` never enter staging. Rows with unparseable dates are deleted after insert.

| PG column | Type | Source file | Source column | Transform |
|-----------|------|-------------|----------------|-----------|
| `time_entry_id` | BIGSERIAL PK | — | — | Generated |
| `person_id` | BIGINT FK | `survey_data.csv` | `Email` | Join `lower(person.email) = lower(Email)`; **email required** — rows without a matching email are dropped |
| `entry_date` | DATE | `survey_data.csv` | `DailySurveyDate` | Date parse; NULL dates deleted |
| `delivery_id` | TEXT | `survey_data.csv` | `DID` | Trim / null |
| `study_id` | TEXT | `survey_data.csv` | `DID_part1` | Trim / null |
| `hours` | NUMERIC(10,2) | `survey_data.csv` | `DIDhr` | Strip commas; skip if not numeric |
| `reporting_event` | TEXT | `survey_data.csv` | `ReportingEvent` | Trim / null |
| `category` | TEXT | `survey_data.csv` | `Category` | Trim / null |
| `source_system` | TEXT | — | — | Default `'daily_survey'` |

Staged but **not copied** to `time_entry`: `SDSL`, `sdslTAlead`.

---

### 3.5 `did.task`

`study_id` is looked up from `did.delivery` on `delivery_id` (`Title` in LoT files). Skip rows with blank `Title`.

#### TLF rows — `didTlf.csv` (`task_kind = 'TLF'`)

| PG column | Type | Source column | Transform |
|-----------|------|----------------|-----------|
| `task_id` | BIGSERIAL PK | — | Generated |
| `delivery_id` | TEXT | `Title` | DID on the LoT item |
| `study_id` | TEXT | — | From `did.delivery.study_id` |
| `task_kind` | TEXT | — | Literal `TLF` |
| `task_type` | TEXT | `LType` | Trim / null |
| `task_name` | TEXT | `LTitle` | Trim / null |
| `dataset` | TEXT | `LSource` | Trim / null |
| `file_name` | TEXT | `LFile` | Trim / null |
| `tlf_number` | TEXT | `LNumber` | Trim / null |
| `production_name` | TEXT | `LProd` | Trim / null |
| `qc_name` | TEXT | `LQC` | Trim / null |

**Not loaded from `didTlf.csv`:** `Fdate`, `Qdate`, `LTlfr`, `srcFile`, `Name`, `Manager`, `Team`, `TAlead`, `sdsaSite1`.

#### DATA rows — `didData.csv` (`task_kind = 'DATA'`)

| PG column | Type | Source column | Transform |
|-----------|------|----------------|-----------|
| `task_id` | BIGSERIAL PK | — | Generated |
| `delivery_id` | TEXT | `Title` | DID on the LoT item |
| `study_id` | TEXT | — | From `did.delivery.study_id` |
| `task_kind` | TEXT | — | Literal `DATA` |
| `task_type` | TEXT | `DType` | Trim / null |
| `task_name` | TEXT | `DDataset` | Same column as `dataset` |
| `dataset` | TEXT | `DDataset` | Same column as `task_name` |
| `file_name` | TEXT | — | Always `NULL` |
| `tlf_number` | TEXT | — | Always `NULL` |
| `production_name` | TEXT | `DProd` | Trim / null |
| `qc_name` | TEXT | `DQC` | Trim / null |

**Not loaded from `didData.csv`:** `Fdate`, `Qdate`, `srcFile`, `adamType`, survey-style person fields.

---

### 3.6 `did.business_term`

| PG column | Type | Source |
|-----------|------|--------|
| `term` | TEXT PK | `sql/04_glossary.sql` |
| `definition` | TEXT | `sql/04_glossary.sql` |
| `calculation` | TEXT | `sql/04_glossary.sql` |
| `notes` | TEXT | `sql/04_glossary.sql` |

Terms include Workload, Utilization, Future workload, DID, Production/QC, Capacity band, etc.

---

## 4. Views (derived — no extra source files)

NL2SQL is instructed to prefer these over base tables.

| View | Grain | Built from | Notes |
|------|-------|------------|--------|
| `vw_task_assignment` | one row per Production **or** QC name on a task | `did.task` | `role` is literal `Production` / `QC` |
| `vw_person_weekly_workload` | person × week | `time_entry` + `person` | `utilization = actual_hours / 40` |
| `vw_person_monthly_workload` | person × `YYYY-MM` | `time_entry` + `person` | `utilization = actual_hours / 160` |
| `vw_delivery_hours` | delivery | `delivery` + `study` + `time_entry` | Hours may be 0 |
| `vw_study_hours` | study | `study` + `time_entry` | |
| `vw_person_delivery_hours` | person × delivery | `time_entry` + `person` + `delivery` | |
| `vw_future_delivery` | open future DID | `delivery` + `study` | Not cancelled; planned date ≥ today; not completed |
| `vw_person_future_assignments` | person × future task | `vw_task_assignment` + `delivery` + `study` | Planned hours are **not** in LoT extracts |
| `vw_capacity_vs_demand` | person × month | `vw_person_monthly_workload` | `assumed_available_hours = 160`; bands under-utilized / healthy / high / overloaded |
| `vw_person_experience` | person × role × task_kind × TA | assignments + delivery + study | Counts, not hours |
| `vw_production_qc_pairing` | Production × QC pair | `did.task` | |
| `vw_on_time_delivery` | completed DID | `did.delivery` | `on_time` if actual ≤ planned; cancelled excluded |

---

## 5. Known gaps (intentionally not in PostgreSQL yet)

- Person NTID / employment status (could come from Neo4j `Node_Person.csv` later).
- Working calendar / leave → utilization uses 40h week and 160h month.
- Planned hours per LoT task (`Fdate`/`Qdate` are dates, not effort).
- Unblinded programming flag on the DID list.
- SDP request master (`SDP DID_0.csv`).
- Accomplishment / BID / archive extracts.

Do not treat hours or utilization as an individual performance score.
