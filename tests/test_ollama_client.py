"""Tests for the Ollama client wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import ollama
import pytest

from app.schemas.fact_check import ClaimExtractionResult
from app.services.ollama_client import call_ollama_structured


@pytest.mark.asyncio
async def test_successful_call():
    """Successful Ollama call returns content and metrics."""
    mock_response = MagicMock()
    mock_response.message.content = '{"claims":[],"cluster_summary":{"title":"t","summary":"s"}}'
    mock_response.eval_count = 42
    mock_response.total_duration = 1000000

    mock_client = AsyncMock()
    mock_client.chat.return_value = mock_response

    with patch("app.services.ollama_client.ollama.AsyncClient", return_value=mock_client):
        result = await call_ollama_structured(
            messages=[{"role": "user", "content": "test"}],
            schema_class=ClaimExtractionResult,
            ollama_url="http://localhost:11434",
        )

    assert result["content"] == mock_response.message.content
    assert result["eval_count"] == 42
    assert result["total_duration"] == 1000000
    mock_client.chat.assert_called_once()


@pytest.mark.asyncio
async def test_retry_on_error():
    """Retries on generic errors with exponential backoff."""
    mock_response = MagicMock()
    mock_response.message.content = '{"claims":[],"cluster_summary":{"title":"t","summary":"s"}}'
    mock_response.eval_count = 10
    mock_response.total_duration = 500

    mock_client = AsyncMock()
    mock_client.chat.side_effect = [
        Exception("connection refused"),
        Exception("timeout"),
        mock_response,
    ]

    with (
        patch("app.services.ollama_client.ollama.AsyncClient", return_value=mock_client),
        patch("app.services.ollama_client.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await call_ollama_structured(
            messages=[{"role": "user", "content": "test"}],
            schema_class=ClaimExtractionResult,
            ollama_url="http://localhost:11434",
        )

    assert result["content"] == mock_response.message.content
    assert mock_client.chat.call_count == 3


@pytest.mark.asyncio
async def test_model_pull_on_404():
    """Pulls model when Ollama returns 404, then retries."""
    mock_response = MagicMock()
    mock_response.message.content = '{"claims":[],"cluster_summary":{"title":"t","summary":"s"}}'
    mock_response.eval_count = 5
    mock_response.total_duration = 200

    mock_client = AsyncMock()
    mock_client.chat.side_effect = [
        ollama.ResponseError("model not found", status_code=404),
        mock_response,
    ]
    mock_client.pull.return_value = None

    with patch("app.services.ollama_client.ollama.AsyncClient", return_value=mock_client):
        result = await call_ollama_structured(
            messages=[{"role": "user", "content": "test"}],
            schema_class=ClaimExtractionResult,
            ollama_url="http://localhost:11434",
        )

    assert result["content"] == mock_response.message.content
    mock_client.pull.assert_called_once_with("llama3.1:8b")


@pytest.mark.asyncio
async def test_raises_after_max_retries():
    """Raises RuntimeError after exhausting retries."""
    mock_client = AsyncMock()
    mock_client.chat.side_effect = Exception("persistent failure")

    with (
        patch("app.services.ollama_client.ollama.AsyncClient", return_value=mock_client),
        patch("app.services.ollama_client.asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(RuntimeError, match="persistent failure"):
            await call_ollama_structured(
                messages=[{"role": "user", "content": "test"}],
                schema_class=ClaimExtractionResult,
                ollama_url="http://localhost:11434",
                max_retries=3,
            )

    assert mock_client.chat.call_count == 3
