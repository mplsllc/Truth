"""Multi-provider LLM client with round-robin fallback.

Provider chain: Groq → Gemini → OpenRouter → Ollama (local fallback).
Each provider is tried in order; on failure or rate-limit, the next is tried.
All providers return structured JSON matching a Pydantic schema.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

log = structlog.get_logger(__name__)

# Rate limit tracking per provider
_rate_limit_until: dict[str, float] = {}


@dataclass
class ProviderConfig:
    name: str
    api_key: str
    base_url: str
    model: str
    rpm_limit: int
    headers: dict[str, str] = field(default_factory=dict)


def _is_rate_limited(provider: str) -> bool:
    until = _rate_limit_until.get(provider, 0)
    return time.time() < until


def _mark_rate_limited(provider: str, backoff_seconds: int = 60) -> None:
    _rate_limit_until[provider] = time.time() + backoff_seconds


def _build_providers(
    groq_api_key: str | None = None,
    gemini_api_key: str | None = None,
    together_api_key: str | None = None,
    openrouter_api_key: str | None = None,
) -> list[ProviderConfig]:
    providers = []
    if groq_api_key:
        providers.append(ProviderConfig(
            name="groq",
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.3-70b-versatile",
            rpm_limit=30,
            headers={"Authorization": f"Bearer {groq_api_key}"},
        ))
    if gemini_api_key:
        providers.append(ProviderConfig(
            name="gemini",
            api_key=gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.0-flash",
            rpm_limit=15,
            headers={},
        ))
    if together_api_key:
        providers.append(ProviderConfig(
            name="together",
            api_key=together_api_key,
            base_url="https://api.together.xyz/v1",
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
            rpm_limit=60,
            headers={"Authorization": f"Bearer {together_api_key}"},
        ))
    if openrouter_api_key:
        providers.append(ProviderConfig(
            name="openrouter",
            api_key=openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            model="meta-llama/llama-3.3-70b-instruct:free",
            rpm_limit=10,
            headers={"Authorization": f"Bearer {openrouter_api_key}"},
        ))
    return providers


def _inline_schema(schema: dict) -> dict:
    """Resolve $defs/$ref in a JSON schema to produce a flat inline schema.

    Also strips 'title' keys which some providers (Gemini) reject.
    """
    defs = schema.pop("$defs", {})

    def _resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].split("/")[-1]
                return _resolve(dict(defs.get(ref_name, {})))
            # Strip "title" only when it's a schema annotation (sibling of "type"/"properties"),
            # not when it's an actual property name inside a "properties" dict.
            skip_title = "type" in node or "properties" in node or "$ref" in node
            result = {k: _resolve(v) for k, v in node.items() if not (k == "title" and skip_title)}
            return result
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return _resolve(schema)


async def _call_groq(
    provider: ProviderConfig,
    messages: list[dict],
    schema_class: type[BaseModel],
) -> dict:
    """Call Groq via OpenAI-compatible API with JSON output."""
    schema = _inline_schema(schema_class.model_json_schema())
    schema_hint = f"\n\nRespond with JSON matching this schema:\n{json.dumps(schema, indent=2)}"
    patched_messages = [
        {**m, "content": m["content"] + schema_hint} if m["role"] == "system" else m
        for m in messages
    ]
    payload = {
        "model": provider.model,
        "messages": patched_messages,
        "temperature": 0,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{provider.base_url}/chat/completions",
            headers={**provider.headers, "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code == 429:
            _mark_rate_limited(provider.name)
            raise RuntimeError(f"Groq rate limited: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {
            "content": content,
            "provider": "groq",
            "model": provider.model,
            "usage": data.get("usage"),
        }


async def _call_gemini(
    provider: ProviderConfig,
    messages: list[dict],
    schema_class: type[BaseModel],
) -> dict:
    """Call Google Gemini API with structured output."""
    # Convert messages to Gemini format
    contents = []
    system_instruction = None
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = msg["content"]
        else:
            contents.append({
                "role": "user" if msg["role"] == "user" else "model",
                "parts": [{"text": msg["content"]}],
            })

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "responseSchema": _inline_schema(schema_class.model_json_schema()),
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    url = (
        f"{provider.base_url}/models/{provider.model}:generateContent"
        f"?key={provider.api_key}"
    )
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code == 429:
            _mark_rate_limited(provider.name)
            raise RuntimeError(f"Gemini rate limited: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return {
            "content": content,
            "provider": "gemini",
            "model": provider.model,
            "usage": data.get("usageMetadata"),
        }


async def _call_together(
    provider: ProviderConfig,
    messages: list[dict],
    schema_class: type[BaseModel],
) -> dict:
    """Call Together AI via OpenAI-compatible API with JSON schema."""
    schema = _inline_schema(schema_class.model_json_schema())
    payload = {
        "model": provider.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 8192,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_class.__name__,
                "schema": schema,
                "strict": False,
            },
        },
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{provider.base_url}/chat/completions",
            headers={**provider.headers, "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code == 429:
            _mark_rate_limited(provider.name)
            raise RuntimeError(f"Together rate limited: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {
            "content": content,
            "provider": "together",
            "model": provider.model,
            "usage": data.get("usage"),
        }


async def _call_openrouter(
    provider: ProviderConfig,
    messages: list[dict],
    schema_class: type[BaseModel],
) -> dict:
    """Call OpenRouter via OpenAI-compatible API."""
    payload = {
        "model": provider.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    # Add schema hint in system message
    schema_hint = (
        f"\n\nYou MUST respond with valid JSON matching this schema:\n"
        f"{json.dumps(schema_class.model_json_schema(), indent=2)}"
    )
    payload["messages"] = [
        {**m, "content": m["content"] + schema_hint} if m["role"] == "system" else m
        for m in messages
    ]

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{provider.base_url}/chat/completions",
            headers={
                **provider.headers,
                "Content-Type": "application/json",
                "HTTP-Referer": "https://truth.mp.ls",
                "X-Title": "Truth News Aggregator",
            },
            json=payload,
        )
        if resp.status_code == 429:
            _mark_rate_limited(provider.name, backoff_seconds=120)
            raise RuntimeError(f"OpenRouter rate limited: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {
            "content": content,
            "provider": "openrouter",
            "model": provider.model,
            "usage": data.get("usage"),
        }


_CALLERS = {
    "groq": _call_groq,
    "gemini": _call_gemini,
    "together": _call_together,
    "openrouter": _call_openrouter,
}


async def call_llm_structured(
    messages: list[dict],
    schema_class: type[BaseModel],
    ollama_url: str = "http://ollama:11434",
    ollama_model: str = "llama3.1:8b",
    groq_api_key: str | None = None,
    gemini_api_key: str | None = None,
    together_api_key: str | None = None,
    openrouter_api_key: str | None = None,
) -> dict:
    """Call LLM with structured output, trying providers in order.

    Returns dict with keys: content (str), provider (str), model (str).
    Falls back to local Ollama if all cloud providers fail.
    """
    providers = _build_providers(groq_api_key, gemini_api_key, together_api_key, openrouter_api_key)

    # Try cloud providers first
    for provider in providers:
        if _is_rate_limited(provider.name):
            await log.ainfo("llm_provider_rate_limited", provider=provider.name)
            continue

        caller = _CALLERS.get(provider.name)
        if not caller:
            continue

        try:
            result = await caller(provider, messages, schema_class)
            await log.ainfo(
                "llm_call_success",
                provider=result["provider"],
                model=result["model"],
            )
            return result
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500] if e.response else ""
            await log.awarn(
                "llm_provider_failed",
                provider=provider.name,
                status=e.response.status_code if e.response else None,
                error=str(e),
                response_body=body,
            )
            continue
        except Exception as e:
            await log.awarn(
                "llm_provider_failed",
                provider=provider.name,
                error=str(e),
            )
            continue

    # Fallback to local Ollama
    await log.ainfo("llm_fallback_ollama", model=ollama_model)
    from app.services.ollama_client import call_ollama_structured
    result = await call_ollama_structured(
        messages=messages,
        schema_class=schema_class,
        ollama_url=ollama_url,
        model=ollama_model,
    )
    result["provider"] = "ollama"
    result["model"] = ollama_model
    return result
