"""Async wrapper for Ollama LLM API with structured output and retry logic."""

from __future__ import annotations

import asyncio

import ollama
import structlog
from pydantic import BaseModel

log = structlog.get_logger()


async def call_ollama_structured(
    messages: list[dict],
    schema_class: type[BaseModel],
    ollama_url: str,
    model: str = "llama3.1:8b",
    max_retries: int = 3,
) -> dict:
    """Call Ollama with structured JSON output enforced by a Pydantic schema.

    Returns dict with keys: content (str), eval_count (int), total_duration (int).
    Raises RuntimeError after max_retries exhausted.
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            client = ollama.AsyncClient(host=ollama_url)
            response = await client.chat(
                model=model,
                messages=messages,
                format=schema_class.model_json_schema(),
                options={"temperature": 0, "num_ctx": 8192, "num_predict": 4096},
            )
            await log.ainfo(
                "ollama_call_success",
                model=model,
                eval_count=getattr(response, "eval_count", None),
                total_duration=getattr(response, "total_duration", None),
            )
            return {
                "content": response.message.content,
                "eval_count": getattr(response, "eval_count", None),
                "total_duration": getattr(response, "total_duration", None),
            }
        except ollama.ResponseError as e:
            last_error = e
            if e.status_code == 404:
                await log.awarn("ollama_model_not_found", model=model)
                try:
                    client = ollama.AsyncClient(host=ollama_url)
                    await client.pull(model)
                    await log.ainfo("ollama_model_pulled", model=model)
                    continue
                except Exception as pull_err:
                    await log.aerror("ollama_pull_failed", error=str(pull_err))
            else:
                await log.awarn(
                    "ollama_error",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                )
        except Exception as e:
            last_error = e
            await log.awarn(
                "ollama_error",
                attempt=attempt + 1,
                max_retries=max_retries,
                error=str(e),
            )

        if attempt < max_retries - 1:
            delay = 2 ** (attempt + 1)
            await asyncio.sleep(delay)

    msg = f"Ollama call failed after {max_retries} attempts: {last_error}"
    raise RuntimeError(msg)
