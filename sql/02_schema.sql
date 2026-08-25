-- DID Q&A core model (PostgreSQL system of record).
-- Agent queries curated tables + views only, not stg_* tables.

CREATE SCHEMA IF NOT EXISTS did;

CREATE TABLE IF NOT EXISTS did.stg_study (
    study_id            TEXT,
    sdsl                TEXT,
    sdsl_email          TEXT,
    ta                  TEXT,
    phase               TEXT,
    indication          TEXT,
    compound_name       TEXT,
    compound_number     TEXT,
    candidate_code      TEXT,
    study_design        TEXT,
    status              TEXT,
    fap_date            TEXT,
    fsfv_date           TEXT,
    lslv_date           TEXT,
    dbr_date            TEXT,
    final_csr_date      TEXT,
    reporting_system    TEXT,
    sharepoint_id       TEXT,
    business_rationale  TEXT
);

CREATE TABLE IF NOT EXISTS did.stg_delivery (
    delivery_id             TEXT,
    study_id                TEXT,
    source_system           TEXT,
    status                  TEXT,
    reporting_event         TEXT,
    reporting_detail        TEXT,
    work_type               TEXT,
    delivery_content        TEXT,
    draft_or_final          TEXT,
    planned_delivery_date   TEXT,
    actual_delivery_date    TEXT,
    quality                 TEXT,
    cancelled               TEXT,
    urgent                  TEXT,
    redelivery              TEXT,
    redelivery_reason       TEXT,
    linked_did              TEXT,
    sdsl                    TEXT,
    sharepoint_id           TEXT
);

CREATE TABLE IF NOT EXISTS did.stg_survey (
    person_name         TEXT,
    manager             TEXT,
    team                TEXT,
    ta_lead             TEXT,
    site                TEXT,
    email               TEXT,
    entry_date          TEXT,
    delivery_id         TEXT,
    reporting_event     TEXT,
    hours               TEXT,
    study_id            TEXT,
    sdsl                TEXT,
    sdsl_ta_lead        TEXT,
    category            TEXT
);

CREATE TABLE IF NOT EXISTS did.stg_task (
    delivery_id         TEXT,
    task_kind           TEXT,
    task_type           TEXT,
    task_name           TEXT,
    dataset             TEXT,
    file_name           TEXT,
    tlf_number          TEXT,
    production_name     TEXT,
    qc_name             TEXT
);

CREATE TABLE IF NOT EXISTS did.person (
    person_id           BIGSERIAL PRIMARY KEY,
    person_name         TEXT NOT NULL,
    email               TEXT,
    ntid                TEXT,
    manager             TEXT,
    team                TEXT,
    ta_lead             TEXT,
    site                TEXT,
    status              TEXT
);

CREATE TABLE IF NOT EXISTS did.study (
    study_id            TEXT PRIMARY KEY,
    sdsl                TEXT,
    sdsl_email          TEXT,
    ta                  TEXT,
    phase               TEXT,
    indication          TEXT,
    compound_name       TEXT,
    compound_number     TEXT,
    candidate_code      TEXT,
    study_design        TEXT,
    status              TEXT,
    fap_date            DATE,
    fsfv_date           DATE,
    lslv_date           DATE,
    dbr_date            DATE,
    final_csr_date      DATE,
    reporting_system    TEXT,
    sharepoint_id       TEXT,
    business_rationale  TEXT
);

CREATE TABLE IF NOT EXISTS did.delivery (
    delivery_id             TEXT PRIMARY KEY,
    study_id                TEXT,
    source_system           TEXT,
    status                  TEXT,
    reporting_event         TEXT,
    reporting_detail        TEXT,
    work_type               TEXT,
    delivery_content        TEXT,
    draft_or_final          TEXT,
    planned_delivery_date   DATE,
    actual_delivery_date    DATE,
    quality                 TEXT,
    cancelled               BOOLEAN,
    urgent                  BOOLEAN,
    redelivery              BOOLEAN,
    redelivery_reason       TEXT,
    linked_did              TEXT,
    sdsl                    TEXT,
    sharepoint_id           TEXT
);

CREATE TABLE IF NOT EXISTS did.time_entry (
    time_entry_id       BIGSERIAL PRIMARY KEY,
    person_id           BIGINT REFERENCES did.person (person_id),
    entry_date          DATE NOT NULL,
    delivery_id         TEXT,
    study_id            TEXT,
    hours               NUMERIC(10, 2) NOT NULL,
    reporting_event     TEXT,
    category            TEXT,
    source_system       TEXT DEFAULT 'daily_survey'
);

CREATE TABLE IF NOT EXISTS did.task (
    task_id             BIGSERIAL PRIMARY KEY,
    delivery_id         TEXT,
    study_id            TEXT,
    task_kind           TEXT,
    task_type           TEXT,
    task_name           TEXT,
    dataset             TEXT,
    file_name           TEXT,
    tlf_number          TEXT,
    production_name     TEXT,
    qc_name             TEXT
);

CREATE TABLE IF NOT EXISTS did.business_term (
    term                TEXT PRIMARY KEY,
    definition          TEXT NOT NULL,
    calculation         TEXT,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_person_email ON did.person (lower(email));
CREATE INDEX IF NOT EXISTS idx_person_name ON did.person (lower(person_name));
CREATE INDEX IF NOT EXISTS idx_delivery_study ON did.delivery (study_id);
CREATE INDEX IF NOT EXISTS idx_delivery_plan ON did.delivery (planned_delivery_date);
CREATE INDEX IF NOT EXISTS idx_time_person_date ON did.time_entry (person_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_time_delivery ON did.time_entry (delivery_id);
CREATE INDEX IF NOT EXISTS idx_time_study ON did.time_entry (study_id);
CREATE INDEX IF NOT EXISTS idx_task_delivery ON did.task (delivery_id);
CREATE INDEX IF NOT EXISTS idx_task_prod ON did.task (production_name);
CREATE INDEX IF NOT EXISTS idx_task_qc ON did.task (qc_name);
