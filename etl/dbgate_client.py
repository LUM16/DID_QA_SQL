"""Load DID Source Data through DbGate HTTP (port 3000).

Direct PostgreSQL (15432) may be blocked from this PC. DbGate on the same host
already has a working localhost connection, so SQL is proxied through it.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DBGATE_URL = os.environ.get("DBGATE_URL", "http://10.109.17.64:3000")
CONID = "3ad949a9-34f0-4fa8-8e6d-6d8c2b80530a"
DATABASE = "did_qa"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


class DbGate:
    def __init__(self, base: str = DBGATE_URL) -> None:
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.session.headers["x-api-session-id"] = str(uuid.uuid4())
        self.conid = CONID
        self.database = DATABASE

    def login(self, login: str, password: str) -> None:
        last = None
        payloads = [
            {"amoid": "logins", "isAdminPage": False, "login": login, "password": password},
            {"amoid": "logins", "isAdminPage": False, "username": login, "password": password},
            {"amoid": "logins", "isAdminPage": False, "user": login, "password": password},
        ]
        for body in payloads:
            resp = self.session.post(f"{self.base}/auth/login", json=body, timeout=30)
            last = resp
            try:
                data = resp.json()
            except Exception:
                continue
            token = data.get("accessToken")
            if token:
                self.session.headers["Authorization"] = f"Bearer {token}"
                return
        raise RuntimeError(
            f"DbGate login failed ({getattr(last, 'status_code', '?')}): "
            f"{(getattr(last, 'text', '') or '')[:300]}"
        )

    def api(self, path: str, body: dict | None = None, timeout: int = 120):
        resp = self.session.post(
            f"{self.base}/{path.lstrip('/')}",
            json=body or {},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"DbGate {path} failed ({resp.status_code}): {resp.text[:800]}"
            )
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype.lower():
            return resp.json()
        return {"text": resp.text[:500], "status": resp.status_code}

    def run_script(self, sql: str, timeout: int = 300) -> dict:
        return self.api(
            "database-connections/run-script",
            {
                "conid": self.conid,
                "database": self.database,
                "sql": sql,
                "logMessage": "did-qa-load",
            },
            timeout=timeout,
        )

    def execute(self, sql: str, timeout: int = 600) -> dict:
        result = self.run_script(sql, timeout=timeout)
        err = result.get("errorMessage")
        if err:
            raise RuntimeError(err)
        return result

    def table_count(self, table: str) -> int:
        sql = f"""
        DO $body$
        BEGIN
          RAISE EXCEPTION 'count=%', (SELECT count(*) FROM {table});
        END
        $body$;
        """
        result = self.run_script(sql)
        err = result.get("errorMessage") or ""
        if err.startswith("count="):
            return int(err.split("=", 1)[1].split()[0].replace(",", ""))
        raise RuntimeError(f"Could not read count for {table}: {err or result}")

    def upload_file(self, path: Path) -> str:
        with path.open("rb") as fh:
            resp = self.session.post(
                f"{self.base}/uploads/upload",
                files={"data": (path.name, fh, "text/csv")},
                timeout=600,
            )
        resp.raise_for_status()
        info = resp.json()
        file_path = info.get("filePath")
        if not file_path:
            raise RuntimeError(f"Upload did not return filePath: {info}")
        return str(file_path)

    def import_csv(self, file_path: str, schema: str, table: str, timeout: int = 1800) -> None:
        script = {
            "type": "json",
            "commands": [
                {
                    "type": "assign",
                    "variableName": "var1",
                    "functionName": "reader@dbgate-plugin-csv",
                    "props": {"fileName": file_path},
                },
                {
                    "type": "assign",
                    "variableName": "var2",
                    "functionName": "tableWriter",
                    "props": {
                        "connection": {
                            "_id": self.conid,
                            "engine": "postgres@dbgate-plugin-postgres",
                            "database": self.database,
                        },
                        "schemaName": schema,
                        "pureName": table,
                        "createIfNotExists": False,
                        "truncate": False,
                        "progressName": table,
                    },
                },
                {
                    "type": "copyStream",
                    "sourceVar": "var1",
                    "targetVar": "var2",
                    "colmapVar": None,
                    "progressName": table,
                },
                {"type": "endline"},
            ],
            "packageNames": ["dbgate-plugin-csv", "dbgate-plugin-postgres"],
        }
        started = self.api("runners/start", {"script": script}, timeout=60)
        runid = started.get("runid")
        if not runid:
            raise RuntimeError(f"Import did not start: {started}")
        print(f"    import run {runid} -> {schema}.{table}")

    def query(self, sql: str, limit_rows: int = 200, timeout: int = 90) -> list[dict]:
        import queue
        import threading

        lines: queue.Queue[str] = queue.Queue()
        stop = threading.Event()
        sid = self.session.headers.get("x-api-session-id")

        def _read() -> None:
            try:
                with self.session.get(
                    f"{self.base}/stream",
                    params={"strmid": sid},
                    stream=True,
                    timeout=timeout + 15,
                ) as resp:
                    for raw in resp.iter_lines(decode_unicode=True):
                        if stop.is_set():
                            break
                        if raw:
                            lines.put(raw)
            except Exception:
                pass

        reader = threading.Thread(target=_read, daemon=True)
        reader.start()
        time.sleep(0.4)
        created = self.api("sessions/create", {"conid": self.conid, "database": self.database})
        sesid = created["sesid"]
        self.api("sessions/execute-query", {"sesid": sesid, "sql": sql.rstrip(";")})
        jslid = None
        deadline = time.time() + timeout
        event_name = ""
        while time.time() < deadline:
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and "session-recordset" in event_name:
                payload = json.loads(line.split(":", 1)[1].strip() or "null")
                if isinstance(payload, dict) and payload.get("jslid"):
                    jslid = payload["jslid"]
            elif line.startswith("event:") and event_name.startswith("session-done"):
                break
            elif "session-done" in event_name:
                break
        stop.set()
        if not jslid:
            raise RuntimeError("DbGate query finished without a result set (check SQL).")
        time.sleep(0.3)
        rows = self.api("jsldata/get-rows", {"jslid": jslid, "offset": 0, "limit": limit_rows})
        if not isinstance(rows, list):
            return []
        return [_unwrap_row(row) for row in rows if isinstance(row, dict)]

    def list_databases(self) -> list[str]:
        rows = self.api("server-connections/list-databases", {"conid": self.conid})
        if isinstance(rows, list):
            return [r.get("name") for r in rows if isinstance(r, dict)]
        return []

    def ensure_database(self) -> None:
        dbs = self.list_databases()
        if self.database not in dbs:
            self.api(
                "server-connections/create-database",
                {"conid": self.conid, "name": self.database},
            )


def _unwrap_value(value):
    if isinstance(value, dict):
        if "$decimal" in value:
            try:
                return float(value["$decimal"])
            except (TypeError, ValueError):
                return value["$decimal"]
        if "$date" in value:
            return value["$date"]
        return {k: _unwrap_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap_value(v) for v in value]
    return value


def _unwrap_row(row: dict) -> dict:
    return {k: _unwrap_value(v) for k, v in row.items()}


def sql_literal(value) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def insert_batch(client: DbGate, table: str, columns: list[str], rows: list[tuple]) -> None:
    if not rows:
        return
    col_sql = ", ".join(columns)
    values = []
    for row in rows:
        values.append("(" + ", ".join(sql_literal(v) for v in row) + ")")
    sql = f"INSERT INTO {table} ({col_sql}) VALUES\n" + ",\n".join(values) + ";"
    client.run_script(sql)


def main() -> int:
    env = load_env()
    login = env.get("DBGATE_LOGIN") or env.get("PGUSER") or "postgre"
    password = env.get("DBGATE_PASSWORD") or env.get("PGPASSWORD")
    if not password:
        raise SystemExit("Set PGPASSWORD or DBGATE_PASSWORD in .env")

    client = DbGate()
    print(f"Logging into DbGate at {client.base} as {login} ...")
    client.login(login, password)
    dbs = client.list_databases()
    print("Databases:", ", ".join(dbs) if dbs else "(none)")
    client.ensure_database()
    probe = client.run_script("SELECT 1;")
    print("run-script probe:", json.dumps(probe)[:300])
    print("DbGate SQL proxy is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
