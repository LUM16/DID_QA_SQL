"""Streamlit entry point for the DID free-text Q&A agent (Posit Connect)."""

from __future__ import annotations

import streamlit as st

from agent import GLOSSARY, ask
from config import load_env
from neo4j_client import connection_summary as neo4j_summary
from neo4j_client import get_schema, neo4j_configured
from pg_client import connection_summary as pg_summary
from pg_client import pg_configured, ping as pg_ping
from vox_client import add_usage, empty_usage

st.set_page_config(
    page_title="DID Q&A",
    page_icon="◈",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  .stApp { background: linear-gradient(165deg, #f3f6f4 0%, #e8eef2 45%, #f7f3ee 100%); }
  [data-testid="stHeader"] { background: transparent; }
  .block-container { padding-top: 1.5rem; max-width: 860px; }
  .brand {
    font-family: "Segoe UI", "PingFang SC", sans-serif;
    font-size: 2rem; font-weight: 700; letter-spacing: -0.02em;
    color: #1a3a32; margin-bottom: 0.15rem;
  }
  .tagline { color: #4a635c; margin-bottom: 1.4rem; }
  .query-box {
    font-family: Consolas, "Courier New", monospace;
    font-size: 0.82rem; background: #1e2a28; color: #c8e6d8;
    padding: 0.75rem 1rem; border-radius: 8px; overflow-x: auto;
    margin-top: 0.4rem;
  }
</style>
""",
    unsafe_allow_html=True,
)


def ensure_state() -> None:
    load_env()
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "schema" not in st.session_state:
        st.session_state.schema = None
    if "show_query" not in st.session_state:
        st.session_state.show_query = True
    if "token_usage" not in st.session_state:
        st.session_state.token_usage = empty_usage()
    if "pg_stats" not in st.session_state:
        st.session_state.pg_stats = None


ensure_state()

st.markdown('<div class="brand">DID Q&A</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="tagline">Free-text questions on study / delivery / task / workload · PostgreSQL metrics + Neo4j relationships · Pfizer Vox</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Data sources")
    pg_ok = pg_configured()
    neo_ok = neo4j_configured()
    st.caption(f"PostgreSQL: `{pg_summary()}`")
    st.caption("Status: " + ("configured" if pg_ok else "not configured"))
    st.caption(f"Neo4j: `{neo4j_summary()}`")
    st.caption("Status: " + ("configured" if neo_ok else "not configured"))

    if st.button("Check PostgreSQL row counts", use_container_width=True):
        try:
            st.session_state.pg_stats = pg_ping()
        except Exception as exc:  # noqa: BLE001
            st.session_state.pg_stats = {"error": str(exc)}
    if st.session_state.pg_stats:
        stats = st.session_state.pg_stats
        if "error" in stats:
            st.error(stats["error"])
        else:
            st.caption(
                f"person {stats['person_count']:,} · study {stats['study_count']:,} · "
                f"delivery {stats['delivery_count']:,} · hours rows {stats['time_entry_count']:,} · "
                f"tasks {stats['task_count']:,}"
            )

    st.session_state.show_query = st.toggle(
        "Show generated SQL / Cypher", value=st.session_state.show_query
    )

    if st.button("Refresh Neo4j schema cache", use_container_width=True):
        try:
            with st.spinner("Loading Neo4j schema…"):
                st.session_state.schema = get_schema()
            st.success("Schema updated")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.token_usage = empty_usage()
        st.rerun()

    st.subheader("Ask about")
    st.caption("Last month hours by person · who is overloaded · deliveries for a study · future assignments · Production/QC pairing")

    with st.expander("Metric definitions"):
        for term, text in GLOSSARY.items():
            st.markdown(f"**{term}** — {text}")

    st.subheader("Token usage (this session)")
    u = st.session_state.token_usage
    st.metric("Total tokens", u.get("total_tokens", 0))
    st.caption(
        f"Prompt: {u.get('prompt_tokens', 0)} · Completion: {u.get('completion_tokens', 0)}"
    )

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and st.session_state.show_query:
            if msg.get("sql"):
                st.markdown(f'<div class="query-box">SQL\n{msg["sql"]}</div>', unsafe_allow_html=True)
            if msg.get("cypher"):
                st.markdown(f'<div class="query-box">Cypher\n{msg["cypher"]}</div>', unsafe_allow_html=True)
        if msg.get("usage") and msg["role"] == "assistant":
            uu = msg["usage"]
            st.caption(
                f"Tokens this turn: {uu.get('total_tokens', 0)} "
                f"(prompt {uu.get('prompt_tokens', 0)} · completion {uu.get('completion_tokens', 0)})"
            )

prompt = st.chat_input("e.g. Who had the highest workload last month?  /  C1071007 有哪些 delivery？")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Routing question and querying data…"):
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages[:-1]
            ]
            try:
                result = ask(prompt, history=history, neo4j_schema=st.session_state.schema)
                if result.get("schema"):
                    st.session_state.schema = result["schema"]
                answer = result["answer"]
                sql = result.get("sql") or ""
                cypher = result.get("cypher") or ""
                usage = result.get("usage") or empty_usage()
                st.session_state.token_usage = add_usage(st.session_state.token_usage, usage)
                st.markdown(answer)
                if st.session_state.show_query:
                    if sql:
                        st.markdown(f'<div class="query-box">SQL\n{sql}</div>', unsafe_allow_html=True)
                    if cypher:
                        st.markdown(f'<div class="query-box">Cypher\n{cypher}</div>', unsafe_allow_html=True)
                st.caption(
                    f"Tokens this turn: {usage.get('total_tokens', 0)} "
                    f"(prompt {usage.get('prompt_tokens', 0)} · completion {usage.get('completion_tokens', 0)})"
                )
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "sql": sql,
                        "cypher": cypher,
                        "usage": usage,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                err = f"Something went wrong: {exc}"
                st.error(err)
                st.session_state.messages.append({"role": "assistant", "content": err})
