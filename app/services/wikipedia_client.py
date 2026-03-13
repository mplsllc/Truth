"""Wikipedia and Wikidata API clients for external evidence gathering."""

from __future__ import annotations

import structlog

log = structlog.get_logger()

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "TruthNewsAggregator/1.0 (https://truth.mp.ls; contact@truth.mp.ls)"


async def search_wikipedia(
    query: str,
    http_client,
    limit: int = 3,
) -> list[dict]:
    """Search Wikipedia and return extracts for matching articles.

    Returns list of dicts with keys: title, extract, pageid.
    Returns empty list on any failure.
    """
    try:
        # Search for pages
        search_resp = await http_client.get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
        )
        search_data = search_resp.json()
        page_ids = [str(r["pageid"]) for r in search_data.get("query", {}).get("search", [])]

        if not page_ids:
            return []

        # Get extracts for found pages
        extract_resp = await http_client.get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "pageids": "|".join(page_ids),
                "prop": "extracts",
                "exintro": "true",
                "explaintext": "true",
                "exsentences": "5",
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
        )
        extract_data = extract_resp.json()
        pages = extract_data.get("query", {}).get("pages", {})

        results = []
        for page_id, page in pages.items():
            if "extract" in page and page["extract"]:
                results.append({
                    "title": page.get("title", ""),
                    "extract": page["extract"],
                    "pageid": int(page_id),
                })

        await log.ainfo("wikipedia_search", query=query, results=len(results))
        return results

    except Exception as e:
        await log.awarn("wikipedia_search_failed", query=query, error=str(e))
        return []


async def query_wikidata(
    entity_name: str,
    http_client,
) -> list[dict]:
    """Query Wikidata for structured facts about an entity.

    Returns list of dicts with keys: property, value.
    Returns empty list on any failure.
    """
    try:
        sparql_query = f"""
        SELECT ?propertyLabel ?valueLabel WHERE {{
          ?entity rdfs:label "{entity_name}"@en .
          ?entity ?prop ?value .
          ?property wikibase:directClaim ?prop .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
        }}
        LIMIT 20
        """
        resp = await http_client.get(
            WIKIDATA_SPARQL,
            params={"query": sparql_query, "format": "json"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        data = resp.json()
        bindings = data.get("results", {}).get("bindings", [])

        results = [
            {
                "property": b["propertyLabel"]["value"],
                "value": b["valueLabel"]["value"],
            }
            for b in bindings
            if "propertyLabel" in b and "valueLabel" in b
        ]

        await log.ainfo("wikidata_query", entity=entity_name, results=len(results))
        return results

    except Exception as e:
        await log.awarn("wikidata_query_failed", entity=entity_name, error=str(e))
        return []
