from pydantic import BaseModel


class ExtractedClaim(BaseModel):
    claim_text: str
    claim_type: str
    original_quote: str


class ClusterSummary(BaseModel):
    title: str
    summary: str


class ClaimExtractionResult(BaseModel):
    claims: list[ExtractedClaim]
    cluster_summary: ClusterSummary


class VerifiedClaim(BaseModel):
    claim_text: str
    verdict: str
    confidence: str
    reasoning: str
    supporting_sources: list[str]
    contradicting_sources: list[str]


class ClaimVerificationResult(BaseModel):
    verified_claims: list[VerifiedClaim]
