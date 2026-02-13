"""
Verification Tiers — Layer 3 of the Agent Trust Protocol.

Maps TrustScore values to actionable access levels.
Services define tier requirements; agents earn tiers through behavior.

Tier system:
  UNVERIFIED (0.0-0.2)  — No trust history. Read-only access.
  BASIC      (0.2-0.4)  — Some interactions. Limited actions.
  VERIFIED   (0.4-0.6)  — Consistent track record. Standard access.
  TRUSTED    (0.6-0.8)  — Strong reputation. Extended privileges.
  SOVEREIGN  (0.8-1.0)  — Exceptional trust. Full autonomy.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Tier(Enum):
    UNVERIFIED = "unverified"
    BASIC = "basic"
    VERIFIED = "verified"
    TRUSTED = "trusted"
    SOVEREIGN = "sovereign"


# Default thresholds (services can override)
DEFAULT_THRESHOLDS = {
    Tier.UNVERIFIED: 0.0,
    Tier.BASIC: 0.2,
    Tier.VERIFIED: 0.4,
    Tier.TRUSTED: 0.6,
    Tier.SOVEREIGN: 0.8,
}


@dataclass
class TierRequirement:
    """What a service requires for a given tier."""
    min_score: float
    min_interactions: int = 0
    min_attestations: int = 0
    min_endorsements: int = 0
    min_age_days: float = 0.0
    required_components: dict = field(default_factory=dict)
    # e.g. {"interaction": 0.5} means interaction component must be >= 0.5


@dataclass
class TierPolicy:
    """A service's tier configuration."""
    service_id: str
    tiers: dict[Tier, TierRequirement] = field(default_factory=dict)
    default_tier: Tier = Tier.UNVERIFIED
    
    @classmethod
    def default(cls, service_id: str) -> "TierPolicy":
        """Create a policy with default thresholds."""
        policy = cls(service_id=service_id)
        for tier, threshold in DEFAULT_THRESHOLDS.items():
            policy.tiers[tier] = TierRequirement(min_score=threshold)
        return policy
    
    @classmethod
    def strict(cls, service_id: str) -> "TierPolicy":
        """Strict policy: higher thresholds + component requirements."""
        policy = cls(service_id=service_id)
        policy.tiers = {
            Tier.UNVERIFIED: TierRequirement(min_score=0.0),
            Tier.BASIC: TierRequirement(
                min_score=0.3, min_interactions=5, min_attestations=1
            ),
            Tier.VERIFIED: TierRequirement(
                min_score=0.5, min_interactions=20, min_attestations=3,
                min_endorsements=2, min_age_days=7,
                required_components={"interaction": 0.4}
            ),
            Tier.TRUSTED: TierRequirement(
                min_score=0.7, min_interactions=50, min_attestations=5,
                min_endorsements=5, min_age_days=30,
                required_components={"interaction": 0.6, "endorsement": 0.4}
            ),
            Tier.SOVEREIGN: TierRequirement(
                min_score=0.9, min_interactions=100, min_attestations=10,
                min_endorsements=10, min_age_days=90,
                required_components={"interaction": 0.7, "endorsement": 0.6}
            ),
        }
        return policy


@dataclass
class TierGrant:
    """Result of evaluating an agent against a tier policy."""
    agent_id: str
    service_id: str
    granted_tier: Tier
    trust_score: float
    met_requirements: dict[str, bool] = field(default_factory=dict)
    next_tier: Optional[Tier] = None
    next_tier_gap: Optional[dict] = None  # what's missing for next tier


def _tier_order() -> list[Tier]:
    return [Tier.UNVERIFIED, Tier.BASIC, Tier.VERIFIED, Tier.TRUSTED, Tier.SOVEREIGN]


def _check_requirement(
    req: TierRequirement,
    score_result: dict,
) -> dict[str, bool]:
    """Check all requirements for a tier. Returns {check_name: passed}."""
    checks = {}
    checks["min_score"] = score_result["trust_score"] >= req.min_score
    checks["min_interactions"] = score_result["interactions_count"] >= req.min_interactions
    checks["min_attestations"] = score_result["attestation_count"] >= req.min_attestations
    checks["min_endorsements"] = score_result["endorsements_count"] >= req.min_endorsements
    
    # Age check
    if req.min_age_days > 0:
        age_secs = score_result["computed_at"] - score_result.get("created_at", score_result["computed_at"])
        checks["min_age"] = (age_secs / 86400) >= req.min_age_days
    else:
        checks["min_age"] = True
    
    # Component requirements
    for comp, min_val in req.required_components.items():
        checks[f"component_{comp}"] = score_result["components"].get(comp, 0.0) >= min_val
    
    return checks


def _compute_gap(
    req: TierRequirement,
    score_result: dict,
    checks: dict[str, bool],
) -> dict:
    """Compute what's missing to meet a requirement."""
    gap = {}
    if not checks.get("min_score", True):
        gap["score"] = round(req.min_score - score_result["trust_score"], 4)
    if not checks.get("min_interactions", True):
        gap["interactions"] = req.min_interactions - score_result["interactions_count"]
    if not checks.get("min_attestations", True):
        gap["attestations"] = req.min_attestations - score_result["attestation_count"]
    if not checks.get("min_endorsements", True):
        gap["endorsements"] = req.min_endorsements - score_result["endorsements_count"]
    for comp, min_val in req.required_components.items():
        if not checks.get(f"component_{comp}", True):
            gap[f"component_{comp}"] = round(min_val - score_result["components"].get(comp, 0.0), 4)
    return gap


def evaluate_tier(
    score_result: dict,
    policy: TierPolicy,
) -> TierGrant:
    """
    Evaluate which tier an agent qualifies for under a given policy.
    
    Args:
        score_result: Output from compute_trust_score()
        policy: The service's tier policy
        
    Returns:
        TierGrant with the highest qualified tier and gap to next
    """
    order = _tier_order()
    granted = policy.default_tier
    granted_checks = {}
    
    for tier in order:
        if tier not in policy.tiers:
            continue
        req = policy.tiers[tier]
        checks = _check_requirement(req, score_result)
        if all(checks.values()):
            granted = tier
            granted_checks = checks
    
    # Find next tier
    next_tier = None
    next_gap = None
    found_current = False
    for tier in order:
        if tier == granted:
            found_current = True
            continue
        if found_current and tier in policy.tiers:
            next_tier = tier
            req = policy.tiers[tier]
            checks = _check_requirement(req, score_result)
            next_gap = _compute_gap(req, score_result, checks)
            break
    
    return TierGrant(
        agent_id=score_result["agent_id"],
        service_id=policy.service_id,
        granted_tier=granted,
        trust_score=score_result["trust_score"],
        met_requirements=granted_checks,
        next_tier=next_tier,
        next_tier_gap=next_gap,
    )


def format_tier_grant(grant: TierGrant) -> str:
    """Human-readable tier grant summary."""
    lines = [
        f"Agent: {grant.agent_id}",
        f"Service: {grant.service_id}",
        f"Trust Score: {grant.trust_score:.4f}",
        f"Granted Tier: {grant.granted_tier.value.upper()}",
    ]
    if grant.next_tier:
        lines.append(f"Next Tier: {grant.next_tier.value.upper()}")
        if grant.next_tier_gap:
            gaps = ", ".join(f"{k}: {v}" for k, v in grant.next_tier_gap.items())
            lines.append(f"Gap: {gaps}")
    return "\n".join(lines)
