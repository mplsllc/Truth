"""Pass 2: Verify extracted claims against gathered evidence using Ollama LLM."""

from __future__ import annotations

import structlog

from app.schemas.fact_check import ClaimVerificationResult, ExtractedClaim
from app.services.evidence_gatherer import EvidenceBundle
from app.services.ollama_client import call_ollama_structured

log = structlog.get_logger()

VERIFICATION_SYSTEM_PROMPT = """\
You are a fact-check analyst. Your job is to verify claims against provided evidence.

For each claim, determine:
- verdict: "confirmed" (evidence supports), "contradicted" (evidence refutes), or "unverifiable" (insufficient evidence)
- confidence: "high" (multiple strong sources agree), "medium" (some evidence, partial), or "low" (weak or single source)
- reasoning: Brief explanation of your verdict (1-2 sentences)
- supporting_sources: List of source names that support the claim
- contradicting_sources: List of source names that contradict the claim

Rules:
- Only use the provided evidence. Do NOT use your own knowledge.
- If no evidence addresses a claim, mark it "unverifiable" with "low" confidence.
- When sources disagree, weight HIGH trust tier sources more heavily.
- Be conservative: if evidence is ambiguous, prefer "unverifiable" over wrong verdicts.

Respond with valid JSON matching the required schema."""

VERIFICATION_USER_TEMPLATE = """\
## Claims to verify:
{claims_text}

## Evidence:
{evidence_text}

Verify each claim against the evidence above."""


def format_claims(claims: list[ExtractedClaim]) -> str:
    """Format claims as numbered list for the verification prompt."""
    lines = []
    for i, claim in enumerate(claims, 1):
        lines.append(f"{i}. [{claim.claim_type}] {claim.claim_text}")
    return "\n".join(lines)


def format_evidence(bundle: EvidenceBundle) -> str:
    """Format evidence items as numbered passages with source and trust tier."""
    if not bundle.items:
        return "No evidence available."
    lines = []
    for i, item in enumerate(bundle.items, 1):
        lines.append(
            f"[Source {i}] {item.source_name} ({item.trust_tier} trust, {item.tier_source}):\n"
            f"{item.text}\n"
        )
    return "\n".join(lines)


async def verify_claims(
    claims: list[ExtractedClaim],
    evidence: EvidenceBundle,
    ollama_url: str,
) -> ClaimVerificationResult:
    """Verify all extracted claims against gathered evidence via Ollama LLM.

    Returns ClaimVerificationResult with verdict, confidence, and reasoning for each claim.
    Raises RuntimeError on Ollama failure, ValidationError on parse failure.
    """
    if not claims:
        return ClaimVerificationResult(verified_claims=[])

    claims_text = format_claims(claims)
    evidence_text = format_evidence(evidence)

    user_message = VERIFICATION_USER_TEMPLATE.format(
        claims_text=claims_text,
        evidence_text=evidence_text,
    )

    messages = [
        {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    result = await call_ollama_structured(
        messages=messages,
        schema_class=ClaimVerificationResult,
        ollama_url=ollama_url,
    )

    parsed = ClaimVerificationResult.model_validate_json(result["content"])

    await log.ainfo(
        "claims_verified",
        claim_count=len(claims),
        verified_count=len(parsed.verified_claims),
        eval_count=result.get("eval_count"),
    )

    return parsed
