import enum


class TrustTier(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FeedStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class ClusterStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class FactCheckStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    EXPIRED = "expired"


class ClaimVerdict(str, enum.Enum):
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


class ConfidenceLevel(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
