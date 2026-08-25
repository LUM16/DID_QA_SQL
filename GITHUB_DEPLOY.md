# DID_QA_SQL — GitHub → Posit Connect

Git-backed Streamlit app (SQL-first DID Q&A). Push this folder to GitHub, then **Import from Git** on `https://rsc.pfizer.com`.

Reference (Neo4j-only app, do not overwrite): `https://github.com/LUM16/DID_QA.git`  
This repo: **`DID_QA_SQL`**.

Do not commit `.env`. Do not set `PG_VIA_DBGATE` on Connect.

---

## 1. Files that belong in GitHub

| File | Role |
|------|------|
| `manifest.json` | **Required.** Connect uses it to detect Streamlit and install deps |
| `app.py` | Streamlit entrypoint |
| `agent.py` | Intent router + NL2SQL / Cypher / glossary |
| `config.py` | `.env` / Connect Vars loader |
| `pg_client.py` | PostgreSQL read-only queries |
| `neo4j_client.py` | Neo4j read-only queries |
| `vox_client.py` | Vox GenAI OAuth + chat |
| `requirements.txt` | Python dependencies |
| `.python-version` | Python 3.11.1 |
| `.gitignore` | Keep secrets and local files out of Git |
| `.rscignore` | Keep `etl/`, `sql/`, `.env` out of the Connect bundle |
| `.env.example` | Variable names only |
| `README.md` | Project notes |
| `GITHUB_DEPLOY.md` | This guide |
| `start-local.bat` | Optional local run |
| `docs/DATA_SPEC.md` | Table / column lineage |
| `etl/` `sql/` | Load scripts and schema (in Git; excluded from Connect by `.rscignore`) |

```
DID_QA_SQL/                 # GitHub repository root
├── manifest.json
├── app.py
├── agent.py
├── config.py
├── pg_client.py
├── neo4j_client.py
├── vox_client.py
├── requirements.txt
├── .python-version
├── .gitignore
├── .rscignore
├── .env.example
├── README.md
├── GITHUB_DEPLOY.md
├── start-local.bat
├── docs/
├── etl/
└── sql/
```

---

## 2. Never push these

| Path | Why |
|------|-----|
| `.env` | PostgreSQL, Neo4j, and Vox secrets |
| `.posit/` | Local Publisher records |
| `.venv/` | Virtualenv |
| `__pycache__/` | Cache |

`.gitignore` already excludes them. Before every push:

```powershell
git status
# .env must not appear
```

---

## 3. GitHub repository

- Name: `DID_QA_SQL`
- Visibility: **Private**
- HTTPS remote: `https://github.com/LUM16/DID_QA_SQL.git`
- Branch: `main`

---

## 4. Import from Git on Posit Connect

Needs **Publisher** (or higher).

1. Open `https://rsc.pfizer.com`
2. **Content** → **Publish** → **Import from Git**
3. **Git repo URL** (https only, no username/password in the URL):
   ```
   https://github.com/LUM16/DID_QA_SQL.git
   ```
4. Branch: `main`
5. Directory with `manifest.json`: repository root (`.`)
6. Title: `DID_QA_SQL` (or similar). This is a **new** content item — do not replace the old DID_Q&A.
7. **Deploy Content** and wait for the build log

If the repo is private, Connect must already have Git credentials for `github.com` (admin setting). Do not put a token in the repo URL.

Git-backed content cannot later be overwritten by Posit Publisher on the same content item.

---

## 5. Connect Vars

Set after the first successful build. **Do not** add `PG_VIA_DBGATE`.

| Variable | Example |
|----------|---------|
| `PGHOST` | `10.109.17.64` |
| `PGPORT` | `15432` |
| `PGDATABASE` | `did_qa` |
| `PGUSER` | `postgres` (prefer a read-only role) |
| `PGPASSWORD` | secret |
| `PGSSLMODE` | `prefer` |
| `NEO4J_URI` | `bolt://10.109.17.64:7687` |
| `NEO4J_USERNAME` | `neo4j` |
| `NEO4J_PASSWORD` | secret |
| `NEO4J_DATABASE` | `neo4j` |
| `VOX_GENAI_API` | `https://mule4api-comm-amer.pfizer.com/vox-genai-api-v2` |
| `VOX_TOKEN_GEN_URL` | `https://prodfederate.pfizer.com/as/token.oauth2` |
| `VOX_CLIENT_ID` | secret |
| `VOX_CLIENT_SECRET` | secret |
| `VOX_MODEL` | `gpt-4o` |

Connect must reach PostgreSQL `10.109.17.64:15432`, Neo4j `10.109.17.64:7687`, and the Vox hosts.

After code changes: `git push origin main`, then wait for Connect refresh (~15 min) or **Settings → Info → Update Now**.

---

## 6. Regenerating `manifest.json`

Needed when you add/remove deployed files or change `requirements.txt`.

```powershell
cd "C:\Users\lum16\Documents\Neo4j\DID Agent\rsc-app2"
$rs = "C:\Program Files\Python311\Scripts\rsconnect.exe"
$tmp = Join-Path $env:TEMP "rsc-app2-manifest"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp | Out-Null
Copy-Item app.py,agent.py,config.py,pg_client.py,neo4j_client.py,vox_client.py,requirements.txt,README.md,GITHUB_DEPLOY.md,.rscignore,.gitignore,.env.example,.python-version,start-local.bat $tmp
& $rs write-manifest streamlit --entrypoint app.py --overwrite $tmp
Copy-Item (Join-Path $tmp "manifest.json") .\manifest.json -Force
```

Commit the updated `manifest.json` with the code change.

---

## 7. Checklist

- [ ] `manifest.json` exists and `entrypoint` is `app.py`
- [ ] `git status` has no `.env`
- [ ] Repo is Private
- [ ] Remote URL has no embedded credentials
- [ ] Import from Git build succeeded (new content, not old DID_Q&A)
- [ ] Vars set, including `PGPORT=15432`
- [ ] PostgreSQL row-count check works, then ask a test question
