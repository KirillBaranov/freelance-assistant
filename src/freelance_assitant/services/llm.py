"""OpenAI-compatible LLM client wrapper."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from openai import AsyncOpenAI

from freelance_assitant.config import settings

logger = logging.getLogger("fa.llm")

DEFAULT_KBLABS_CREDENTIALS_PATH = Path.home() / ".kb" / "freelance-assistant-agent.json"

_client: AsyncOpenAI | None = None
_client_token: str | None = None
_gateway_access_token: str | None = None
_gateway_access_token_exp: int = 0


def normalize_llm_base_url(base_url: str) -> str:
    """Map known KB Labs gateway roots to the OpenAI-compatible LLM path."""
    normalized = base_url.rstrip("/")
    if not normalized:
        return normalized

    if "api.kblabs.ru" not in normalized:
        return normalized

    parts = urlsplit(normalized)
    path = parts.path.rstrip("/")
    if path in ("", "/v1", "/llm", "/llm/v1"):
        path = "/llm/v1"

    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def gateway_root_url(base_url: str) -> str:
    """Return gateway root URL without the OpenAI-compatible suffix."""
    normalized = base_url.rstrip("/")
    for suffix in ("/llm/v1", "/v1"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def normalize_llm_model(base_url: str, model: str) -> str:
    """Map local model names to KB Labs gateway tiers when needed."""
    if "api.kblabs.ru" not in base_url:
        return model

    aliases = {
        "gpt-4o-mini": "small",
        "gpt-4.1-mini": "small",
        "gpt-4o": "medium",
        "gpt-4.1": "medium",
        "gpt-5": "large",
    }
    return aliases.get(model, model)


def resolve_kblabs_credentials_path() -> Path:
    configured = settings.llm_credentials_path.strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_KBLABS_CREDENTIALS_PATH


def jwt_exp(token: str) -> int:
    try:
        payload = token.split(".")[1]
        padding = "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload + padding).decode())
        exp = data.get("exp")
        return int(exp) if exp is not None else 0
    except Exception:
        return 0


def load_kblabs_credentials() -> tuple[str, str] | None:
    if settings.llm_client_id and settings.llm_client_secret:
        return settings.llm_client_id, settings.llm_client_secret

    path = resolve_kblabs_credentials_path()
    if not path.exists():
        return None

    data = json.loads(path.read_text())
    client_id = data.get("clientId", "").strip()
    client_secret = data.get("clientSecret", "").strip()
    if not client_id or not client_secret:
        return None

    return client_id, client_secret


async def refresh_kblabs_access_token() -> str:
    global _gateway_access_token, _gateway_access_token_exp

    now = int(__import__("time").time())
    if _gateway_access_token and _gateway_access_token_exp > now + 60:
        return _gateway_access_token

    creds = load_kblabs_credentials()
    if not creds:
        raise RuntimeError("KB Labs credentials not configured")

    client_id, client_secret = creds
    gateway_url = gateway_root_url(settings.llm_base_url)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{gateway_url}/auth/token",
            json={"clientId": client_id, "clientSecret": client_secret},
        )
        response.raise_for_status()
        data = response.json()

    token = str(data.get("accessToken") or "").strip()
    if not token:
        raise RuntimeError("KB Labs auth returned empty access token")
    _gateway_access_token = token
    _gateway_access_token_exp = jwt_exp(token)
    return token


async def get_llm_client() -> AsyncOpenAI:
    global _client, _client_token

    if settings.llm_api_key:
        if _client is None or _client_token != settings.llm_api_key:
            _client_token = settings.llm_api_key
            _client = AsyncOpenAI(
                base_url=normalize_llm_base_url(settings.llm_base_url),
                api_key=_client_token,
            )
        return _client

    if "api.kblabs.ru" not in settings.llm_base_url:
        raise RuntimeError("LLM API key is not configured")

    access_token = await refresh_kblabs_access_token()
    if _client is None or _client_token != access_token:
        _client_token = access_token
        _client = AsyncOpenAI(
            base_url=normalize_llm_base_url(settings.llm_base_url),
            api_key=access_token,
        )
    return _client


async def chat_completion(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    response_format: dict[str, str] | None = None,
) -> str:
    """Simple wrapper for chat completions."""
    client = await get_llm_client()
    kwargs: dict[str, Any] = {
        "model": normalize_llm_model(settings.llm_base_url, model or settings.llm_model),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    logger.debug("LLM response (%s chars)", len(content))
    return content
