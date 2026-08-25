"""DID free-text Q&A agent: intent router + NL2SQL + Neo4j + glossary."""

from __future__ import annotations

import json
import re
from typing import Any

from config import load_env
from neo4j_client import get_schema as get_neo4j_schema
from neo4j_client import neo4j_configured, run_cypher
from pg_client import SCHEMA_FOR_LLM, pg_configured, run_sql
from vox_client import add_usage, chat as _chat, empty_usage

SQL_BLOCK = re.compile(r"```(?:sql)?\s*([\s\S]*?)```", re.IGNORECASE)
CYPHER_BLOCK = re.compile(r"```(?:cypher)?\s*([\s\S]*?)```", re.IGNORECASE)
JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

LANGUAGE_RULE = (
    "Language policy: Match the user's question language. "
    "If the question is primarily Chinese, respond in Chinese. "
    "If the question is primarily English, respond in English. "
    "Do not switch languages mid-answer unless quoting data labels."
)

GLOSSARY = {
    "Workload": "SUM of daily survey hours for a person in a time window. Not task count.",
    "Utilization": "Weekly actual_hours/40; monthly actual_hours/160. Capacity calendar is not loaded yet.",
    "Future workload": "Open Production/QC assignments on deliveries with a future planned date. Planned hours per task are usually missing, so use task/delivery counts.",
    "DID": "Delivery ID. Example C5471001_2 is a delivery; C5471001 is the study (DID_0).",
    "Production / QC": "Each LoT task typically has one Production programmer and one QC programmer.",
    "Productivity": "Team operational insight only. Do not rank individuals as a performance score.",
    "Capacity band": "<70% under-utilized; 70-90% healthy; 90-105% high; >105% overloaded.",
}

SQL_HINTS = """
Example SQL:
1) Last month top workload
SELECT person_name, actual_hours, utilization, delivery_count, study_count, capacity_band
FROM did.vw_capacity_vs_demand
WHERE year_month = to_char(date_trunc('month', CURRENT_DATE - interval '1 month'), 'YYYY-MM')
ORDER BY actual_hours DESC
LIMIT 10;

2) Hours for one person last 7 days
SELECT p.person_name, t.entry_date, t.delivery_id, t.study_id, t.hours, t.reporting_event
FROM did.time_entry t
JOIN did.person p ON p.person_id = t.person_id
WHERE p.person_name ILIKE '%NAME%'
  AND t.entry_date >= CURRENT_DATE - 7
ORDER BY t.entry_date DESC
LIMIT 50;

3) Study effort
SELECT study_id, ta, actual_hours, people_count, delivery_count
FROM did.vw_study_hours
WHERE study_id ILIKE '%C1071007%'
LIMIT 20;

4) Upcoming deliveries
SELECT delivery_id, study_id, reporting_event, planned_delivery_date, days_until_due, urgent, ta
FROM did.vw_future_delivery
WHERE planned_delivery_date <= CURRENT_DATE + 28
ORDER BY planned_delivery_date
LIMIT 50;

5) Who is assigned to a future delivery
SELECT person_name, role, task_kind, task_name, delivery_id, planned_delivery_date
FROM did.vw_person_future_assignments
WHERE person_name ILIKE '%NAME%'
ORDER BY planned_delivery_date
LIMIT 50;
"""


def _extract_block(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip().rstrip(";") if match else None


def _parse_intent(raw: str) -> dict[str, str]:
    blob = _extract_block(raw, JSON_BLOCK) or raw
    start = blob.find("{")
    end = blob.rfind("}")
    if start >= 0 and end > start:
        blob = blob[start : end + 1]
    data = json.loads(blob)
    tool = str(data.get("tool") or "sql").strip().lower()
    if tool not in {"sql", "cypher", "both", "glossary"}:
        tool = "sql"
    return {
        "tool": tool,
        "reason": str(data.get("reason") or ""),
    }


def classify_intent(question: str, history: list[dict[str, str]] | None = None) -> tuple[dict[str, str], dict[str, int]]:
    history_text = ""
    if history:
        recent = history[-6:]
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
    system = """You route questions for a clinical programming workforce agent.
Return JSON only: {"tool":"sql"|"cypher"|"both"|"glossary","reason":"short"}
Rules:
- sql: hours, workload, utilization, rankings, counts, dates, status, on-time, future due dates, assignments, top N.
- cypher: collaboration network, who worked with whom as a graph, hidden SME via multi-hop, relationship paths.
- both: needs exact hours/counts AND relationship/network context.
- glossary: definition of workload, utilization, DID, productivity, capacity band, or how a metric is calculated.
Prefer sql. Use cypher only when the graph relationship is the point of the question.
If PostgreSQL is the system of record, do not choose cypher just because people and studies are related."""
    user = f"""Conversation:
{history_text or '(none)'}

Question: {question}
"""
    raw, usage = _chat(system, user)
    try:
        return _parse_intent(raw), usage
    except Exception:  # noqa: BLE001
        q = question.lower()
        if any(k in q for k in ("what is", "定义", "怎么算", "how is", "meaning of")):
            return {"tool": "glossary", "reason": "fallback definition"}, usage
        if any(k in q for k in ("collaborat", "network", "who worked with", "合作", "配对")):
            return {"tool": "cypher", "reason": "fallback relationship"}, usage
        return {"tool": "sql", "reason": "fallback sql"}, usage


def generate_sql(question: str, history: list[dict[str, str]] | None = None) -> tuple[str, dict[str, int]]:
    history_text = ""
    if history:
        recent = history[-6:]
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
    system = """You are a PostgreSQL expert for SDSA clinical programming operations.
Write one read-only SQL query.
Rules:
1. Output exactly one statement in a ```sql block.
2. SELECT or WITH only. Never write/DDL.
3. Add LIMIT 50 unless the user asked for a count only.
4. Prefer did.vw_* views for metrics.
5. Match people with ILIKE. Match study_id / delivery_id with ILIKE unless an exact ID is given.
6. "Last week" = entry_date >= CURRENT_DATE - 7. "Last month" = previous calendar month via year_month or date_trunc.
7. Do not invent columns. Use only the provided schema.
8. For overloaded people use vw_capacity_vs_demand and capacity_band = 'overloaded' or utilization > 1.05.
9. Keep SQL keywords in English."""
    user = f"""Schema:
{SCHEMA_FOR_LLM}

{SQL_HINTS}

Conversation:
{history_text or '(none)'}

Question: {question}
"""
    raw, usage = _chat(system, user)
    sql = _extract_block(raw, SQL_BLOCK)
    if not sql:
        for line in raw.splitlines():
            if line.strip().upper().startswith(("SELECT", "WITH")):
                sql = line.strip().rstrip(";")
                break
    if not sql:
        raise ValueError(f"Could not parse SQL from model output:\n{raw}")
    return sql, usage


def generate_cypher(
    question: str,
    schema: dict[str, Any],
    history: list[dict[str, str]] | None = None,
) -> tuple[str, dict[str, int]]:
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
    history_text = ""
    if history:
        recent = history[-6:]
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
    system = """You are a Neo4j Cypher expert. Write one read-only Cypher query.
Rules:
1. Output exactly one statement in a ```cypher block.
2. Never CREATE/MERGE/DELETE/SET/REMOVE/DROP.
3. Add LIMIT 50 unless the user asked for a count only.
4. Study identifiers often use IPort_Study or Name. Delivery uses DID.
5. Use only labels, relationship types, and property keys from the schema.
6. Prefer person-study-delivery paths. Do not re-aggregate daily survey hours if a simpler path exists."""
    user = f"""Schema:
{schema_text}

Conversation:
{history_text or '(none)'}

Question: {question}
"""
    raw, usage = _chat(system, user)
    cypher = _extract_block(raw, CYPHER_BLOCK)
    if not cypher:
        for line in raw.splitlines():
            if line.strip().upper().startswith(("MATCH", "CALL", "WITH", "RETURN", "OPTIONAL", "UNWIND")):
                cypher = line.strip().rstrip(";")
                break
    if not cypher:
        raise ValueError(f"Could not parse Cypher from model output:\n{raw}")
    return cypher, usage


def answer_from_rows(
    question: str,
    tool: str,
    queries: dict[str, str],
    rows: dict[str, list[dict[str, Any]]],
) -> tuple[str, dict[str, int]]:
    payload = json.dumps(
        {k: v[:80] for k, v in rows.items()},
        ensure_ascii=False,
        default=str,
    )
    system = f"""You are a workforce / delivery Q&A assistant for a clinical programming team.
Rules:
1. {LANGUAGE_RULE}
2. Lead with the direct answer, then brief supporting detail.
3. Never invent data that is not in the results.
4. If results are empty, explain likely reasons (name spelling, wrong DID, date window, or data not loaded).
5. For multiple rows, use a concise markdown table.
6. Keep study IDs, DID values, and field names as-is.
7. Do not present utilization or hours as individual performance scores.
8. If utilization uses 40h/week or 160h/month, mention that this is an assumed capacity.
9. Cite which source you used (PostgreSQL view name or Neo4j)."""
    user = f"""Question: {question}
Tool: {tool}
Queries: {json.dumps(queries, ensure_ascii=False)}
Results JSON: {payload}
Write the answer now."""
    return _chat(system, user)


def _glossary_answer(question: str) -> str:
    parts = [f"**{term}**: {text}" for term, text in GLOSSARY.items()]
    return (
        "These metric definitions are fixed in the semantic layer "
        "(PostgreSQL `did.business_term` / agent glossary):\n\n"
        + "\n".join(f"- {p}" for p in parts)
        + f"\n\nQuestion received: {question}"
    )


def ask(
    question: str,
    history: list[dict[str, str]] | None = None,
    neo4j_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    load_env()
    usage = empty_usage()
    queries: dict[str, str] = {}
    rows: dict[str, list[dict[str, Any]]] = {}
    error = None

    try:
        intent, u0 = classify_intent(question, history)
        usage = add_usage(usage, u0)
        tool = intent["tool"]

        if tool == "glossary":
            return {
                "answer": _glossary_answer(question),
                "tool": tool,
                "sql": None,
                "cypher": None,
                "rows": {},
                "schema": neo4j_schema,
                "error": None,
                "usage": usage,
                "reason": intent.get("reason"),
            }

        need_sql = tool in {"sql", "both"}
        need_cypher = tool in {"cypher", "both"}
        if need_sql and not pg_configured():
            if neo4j_configured():
                need_sql, need_cypher, tool = False, True, "cypher"
            else:
                raise ValueError("PostgreSQL is not configured (PGPASSWORD / PGHOST).")
        if need_cypher and not neo4j_configured():
            if pg_configured():
                need_sql, need_cypher, tool = True, False, "sql"
            else:
                raise ValueError("Neo4j is not configured (NEO4J_PASSWORD).")

        last_error = None
        for _attempt in range(3):
            try:
                hint = f"\nPrevious query failed: {last_error}" if last_error else ""
                if need_sql:
                    sql, u1 = generate_sql(question + hint, history)
                    usage = add_usage(usage, u1)
                    queries["sql"] = sql
                    rows["sql"] = run_sql(sql)
                if need_cypher:
                    neo4j_schema = neo4j_schema or get_neo4j_schema()
                    cypher, u2 = generate_cypher(question + hint, neo4j_schema, history)
                    usage = add_usage(usage, u2)
                    queries["cypher"] = cypher
                    rows["cypher"] = run_cypher(cypher)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                queries = {}
                rows = {}
        if last_error:
            raise RuntimeError(last_error)

        answer, u3 = answer_from_rows(question, tool, queries, rows)
        usage = add_usage(usage, u3)
        return {
            "answer": answer,
            "tool": tool,
            "sql": queries.get("sql"),
            "cypher": queries.get("cypher"),
            "rows": rows,
            "schema": neo4j_schema,
            "error": None,
            "usage": usage,
            "reason": intent.get("reason"),
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        return {
            "answer": f"Query failed: {error}",
            "tool": None,
            "sql": queries.get("sql"),
            "cypher": queries.get("cypher"),
            "rows": rows,
            "schema": neo4j_schema,
            "error": error,
            "usage": usage,
            "reason": None,
        }
