"""Shared .env loader for the DID Q&A RSC app."""

from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
ENV_FILE = APP_ROOT / ".env"


def load_env() -> None:
    """Load APP_ROOT/.env into os.environ.

    Local .env wins when present. On Posit Connect, omit .env and set Vars.
    """
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")
