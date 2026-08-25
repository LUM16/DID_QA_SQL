"""Pfizer Vox GenAI V2 client (OAuth + OpenAI-compatible chat)."""

from __future__ import annotations

import os
import time
from typing import Any

import requests
from openai import OpenAI

from config import load_env

_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def empty_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _usage_from_response(resp: Any) -> dict[str, int]:
    usage = empty_usage()
    raw = getattr(resp, "usage", None)
    if raw is None:
        return usage
    usage["prompt_tokens"] = int(getattr(raw, "prompt_tokens", 0) or 0)
    usage["completion_tokens"] = int(getattr(raw, "completion_tokens", 0) or 0)
    usage["total_tokens"] = int(
        getattr(raw, "total_tokens", 0)
        or (usage["prompt_tokens"] + usage["completion_tokens"])
    )
    return usage


def add_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {
        "prompt_tokens": a.get("prompt_tokens", 0) + b.get("prompt_tokens", 0),
        "completion_tokens": a.get("completion_tokens", 0) + b.get("completion_tokens", 0),
        "total_tokens": a.get("total_tokens", 0) + b.get("total_tokens", 0),
    }


def _vox_configured() -> bool:
    load_env()
    return bool(
        os.environ.get("VOX_GENAI_API")
        and os.environ.get("VOX_TOKEN_GEN_URL")
        and os.environ.get("VOX_CLIENT_ID")
        and os.environ.get("VOX_CLIENT_SECRET")
    )


def get_vox_access_token(force_refresh: bool = False) -> str:
    load_env()
    now = time.time()
    if (
        not force_refresh
        and _token_cache["access_token"]
        and now < float(_token_cache["expires_at"]) - 60
    ):
        return str(_token_cache["access_token"])

    resp = requests.post(
        os.environ["VOX_TOKEN_GEN_URL"],
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["VOX_CLIENT_ID"],
            "client_secret": os.environ["VOX_CLIENT_SECRET"],
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Vox token request failed ({resp.status_code}): {resp.text[:400]}")

    payload = resp.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise RuntimeError(f"Vox token response missing access_token: {payload}")

    expires_in = int(payload.get("expires_in", 1800))
    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = now + expires_in
    return access_token


def build_llm_client() -> tuple[OpenAI, str]:
    load_env()
    if _vox_configured():
        token = get_vox_access_token()
        base = os.environ["VOX_GENAI_API"].rstrip("/")
        client = OpenAI(api_key=token, base_url=f"{base}/v1")
        model = os.environ.get("VOX_MODEL") or "gpt-4o"
        return client, model
    raise ValueError(
        "Missing Vox GenAI config. Set VOX_GENAI_API, VOX_TOKEN_GEN_URL, "
        "VOX_CLIENT_ID, and VOX_CLIENT_SECRET in Connect Vars or .env."
    )


def chat(system: str, user: str, temperature: float = 0.1) -> tuple[str, dict[str, int]]:
    client, model = build_llm_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    except Exception as first_err:
        if _vox_configured() and "401" in str(first_err):
            get_vox_access_token(force_refresh=True)
            client, model = build_llm_client()
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
        else:
            raise
    text = (resp.choices[0].message.content or "").strip()
    return text, _usage_from_response(resp)
