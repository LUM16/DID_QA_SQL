-- Optional Neo4j slim-down. Review counts BEFORE deleting anything.
-- PostgreSQL should own time-series / assignment facts after the Source Data load.
-- Do not run the DETACH DELETE block until you have a backup.

-- 1) Inventory
CALL db.labels();
CALL db.relationshipTypes();

// Time-series survey facts (move to PostgreSQL time_entry)
MATCH (n:DeliverySurvey) RETURN count(n) AS delivery_survey_nodes;
MATCH (n:StudySurvey) RETURN count(n) AS study_survey_nodes;
MATCH ()-[r:PERSON_DELIVERY_DAILY_SURVEY_DIDN]->() RETURN count(r) AS rel_person_delivery_didn;
MATCH ()-[r:PERSON_DELIVERY_DAILY_SURVEY_DID0]->() RETURN count(r) AS rel_person_delivery_did0;
MATCH ()-[r:PERSON_STUDY_DAILY_SURVEY_DIDN]->() RETURN count(r) AS rel_person_study_didn;
MATCH ()-[r:PERSON_STUDY_DAILY_SURVEY_DID0]->() RETURN count(r) AS rel_person_study_did0;

// Granular TLF catalog (133k+); assignments belong in PostgreSQL did.task
MATCH (n:TLF) RETURN count(n) AS tlf_nodes;
MATCH ()-[r:HAS_TLF]->() RETURN count(r) AS rel_has_tlf;
MATCH ()-[r:HAS_DATA]->() RETURN count(r) AS rel_has_data;

// Initiative / BID graph — keep only if you still ask BID questions in Neo4j
MATCH (n:Task_Force) RETURN count(n) AS task_force_nodes;
MATCH (n:BID_0) RETURN count(n) AS bid0_nodes;
MATCH (n:BID_Cat) RETURN count(n) AS bid_cat_nodes;

// Accomplishment facts — better as SQL metrics
MATCH ()-[r:HAS_ACCOMPLISHMENT]->() RETURN count(r) AS rel_accomplishment;

-- 2) Recommended keep set after slim-down
-- (:Person), (:Study), (:Delivery)
-- (:Study)-[:HAS_DELIVERY]->(:Delivery)
-- optional summary: (:Person)-[:WORKED_ON]->(:Delivery)  -- one edge per person-delivery, not daily
-- optional: (:Submission) if submission questions still go to Neo4j

-- 3) Example deletes (BACKUP FIRST). Uncomment only after counts look right.
-- MATCH (n:DeliverySurvey) DETACH DELETE n;
-- MATCH (n:StudySurvey) DETACH DELETE n;
-- MATCH (n:TLF) DETACH DELETE n;
-- MATCH (n:Data) DETACH DELETE n;
-- MATCH (n:Task_Force) DETACH DELETE n;
-- MATCH (n:BID_0) DETACH DELETE n;
-- MATCH (n:BID_Cat) DETACH DELETE n;
