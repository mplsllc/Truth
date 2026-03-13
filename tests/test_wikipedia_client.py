"""Tests for Wikipedia and Wikidata API clients."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.wikipedia_client import query_wikidata, search_wikipedia


def _mock_response(json_data):
    resp = MagicMock()
    resp.json.return_value = json_data
    return resp


@pytest.mark.asyncio
async def test_search_wikipedia_returns_extracts():
    client = AsyncMock()
    client.get.side_effect = [
        _mock_response({
            "query": {"search": [{"pageid": 123, "title": "Test"}]}
        }),
        _mock_response({
            "query": {"pages": {"123": {"title": "Test", "extract": "Some info about test."}}}
        }),
    ]
    results = await search_wikipedia("test query", client, limit=1)
    assert len(results) == 1
    assert results[0]["title"] == "Test"
    assert "Some info" in results[0]["extract"]


@pytest.mark.asyncio
async def test_search_wikipedia_empty_results():
    client = AsyncMock()
    client.get.return_value = _mock_response({"query": {"search": []}})
    results = await search_wikipedia("nonexistent", client)
    assert results == []


@pytest.mark.asyncio
async def test_search_wikipedia_handles_error():
    client = AsyncMock()
    client.get.side_effect = Exception("Network error")
    results = await search_wikipedia("test", client)
    assert results == []


@pytest.mark.asyncio
async def test_query_wikidata_returns_facts():
    client = AsyncMock()
    client.get.return_value = _mock_response({
        "results": {
            "bindings": [
                {
                    "propertyLabel": {"value": "population"},
                    "valueLabel": {"value": "8000000"},
                }
            ]
        }
    })
    results = await query_wikidata("New York City", client)
    assert len(results) == 1
    assert results[0]["property"] == "population"


@pytest.mark.asyncio
async def test_query_wikidata_handles_error():
    client = AsyncMock()
    client.get.side_effect = Exception("Timeout")
    results = await query_wikidata("test", client)
    assert results == []
