"""
A2A Trust Extension — Layer 4 of the Agent Trust Protocol.

Bridges the Agent Trust Protocol with the A2A (Agent-to-Agent) protocol
by extending AgentCard metadata with cryptographic trust attestations,
behavioral reputation scores, and verification tiers.

Classes:
  TrustAgentCard  — AgentCard enriched with trust metadata
  TrustVerifier   — Validates trust cards (isnad chain, score, tier)
  TrustGatekeeper — Accept/reject A2A tasks based on trust requirements
"""

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

from .score import AgentProfile, compute_trust_score
from .tiers import Tier, TierPolicy, evaluate_tier, TierGrant
from .serialization import profile_to_dict, dict_to_profile, SCHEMA_VERSION


# ---------------------------------------------------------------------------
# TrustAgentCard
# ---------------------------------------------------------------------------

@dataclass
class TrustAgentCard:
    """
    A2A AgentCard extended with Agent Trust Protocol metadata.

    Compatible with A2A AgentCard's ``extensions`` field — the trust
    metadata serialises into a single JSON-safe dict keyed under
    ``"trust_protocol"``.
    """

    # -- Standard A2A AgentCard fields --
    agent_id: str
    name: str = ""
    description: str = ""
    url: str = ""
    capabilities: list[str] = field(default_factory=list)

    # -- Trust metadata --
    trust_score: Optional[float] = None
    trust_components: Optional[dict] = None
    tier: Optional[Tier] = None
    attestation_count: int = 0
    last_attestation: Optional[float] = None
    profile: Optional[AgentProfile] = None

    # bookkeeping
    issued_at: float = field(default_factory=time.time)
    schema_version: str = SCHEMA_VERSION

    # ----- builders -----

    @classmethod
    def from_profile(
        cls,
        profile: AgentProfile,
        *,
        name: str = "",
        description: str = "",
        url: str = "",
        capabilities: Optional[list[str]] = None,
        tier_policy: Optional[TierPolicy] = None,
        now: Optional[float] = None,
    ) -> "TrustAgentCard":
        """Build a TrustAgentCard from an existing AgentProfile."""
        now = now or time.time()
        score_result = compute_trust_score(profile, now=now)

        tier = None
        if tier_policy is not None:
            grant = evaluate_tier(score_result, tier_policy)
            tier = grant.granted_tier

        return cls(
            agent_id=profile.agent_id,
            name=name,
            description=description,
            url=url,
            capabilities=capabilities or [],
            trust_score=score_result["trust_score"],
            trust_components=score_result["components"],
            tier=tier,
            attestation_count=profile.attestation_count,
            last_attestation=profile.last_attestation,
            profile=profile,
            issued_at=now,
        )

    # ----- serialisation -----

    def to_dict(self, *, include_profile: bool = False) -> dict:
        """Serialise to a JSON-compatible dict."""
        d: dict = {
            "schema_version": self.schema_version,
            "type": "trust_agent_card",
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "capabilities": list(self.capabilities),
            "trust": {
                "score": self.trust_score,
                "components": self.trust_components,
                "tier": self.tier.value if self.tier else None,
                "attestation_count": self.attestation_count,
                "last_attestation": self.last_attestation,
            },
            "issued_at": self.issued_at,
        }
        if include_profile and self.profile is not None:
            d["profile"] = profile_to_dict(self.profile)
        return d

    def to_json(self, *, indent: int = 2, include_profile: bool = False) -> str:
        return json.dumps(self.to_dict(include_profile=include_profile), indent=indent)

    def to_a2a_extension(self) -> dict:
        """Return the trust block suitable for A2A AgentCard ``extensions``."""
        return {"trust_protocol": self.to_dict()["trust"]}

    @classmethod
    def from_dict(cls, data: dict) -> "TrustAgentCard":
        trust = data.get("trust", {})
        tier_val = trust.get("tier")
        tier = Tier(tier_val) if tier_val else None

        profile = None
        if "profile" in data:
            profile = dict_to_profile(data["profile"])

        return cls(
            agent_id=data["agent_id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            url=data.get("url", ""),
            capabilities=data.get("capabilities", []),
            trust_score=trust.get("score"),
            trust_components=trust.get("components"),
            tier=tier,
            attestation_count=trust.get("attestation_count", 0),
            last_attestation=trust.get("last_attestation"),
            profile=profile,
            issued_at=data.get("issued_at", 0),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "TrustAgentCard":
        return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# TrustVerifier
# ---------------------------------------------------------------------------

class VerificationResult(Enum):
    PASS = "pass"
    FAIL_SCORE = "fail_score"
    FAIL_TIER = "fail_tier"
    FAIL_ATTESTATIONS = "fail_attestations"
    FAIL_EXPIRED = "fail_expired"
    FAIL_MISSING = "fail_missing"


@dataclass
class VerificationReport:
    """Outcome of verifying a TrustAgentCard."""
    card_agent_id: str
    result: VerificationResult
    details: str = ""
    checked_at: float = field(default_factory=time.time)

    @property
    def passed(self) -> bool:
        return self.result == VerificationResult.PASS


@dataclass
class TrustVerifier:
    """
    Verifies a TrustAgentCard against configurable requirements.

    Checks:
    - Score meets a minimum threshold
    - Tier meets a minimum level
    - Attestation count is sufficient
    - Card is not expired (max age)
    """

    min_score: float = 0.0
    min_tier: Optional[Tier] = None
    min_attestations: int = 0
    max_card_age: Optional[float] = None  # seconds; None = no expiry

    _TIER_RANK = {
        Tier.UNVERIFIED: 0,
        Tier.BASIC: 1,
        Tier.VERIFIED: 2,
        Tier.TRUSTED: 3,
        Tier.SOVEREIGN: 4,
    }

    def verify(self, card: TrustAgentCard, now: Optional[float] = None) -> VerificationReport:
        now = now or time.time()

        # Missing score
        if card.trust_score is None:
            return VerificationReport(
                card_agent_id=card.agent_id,
                result=VerificationResult.FAIL_MISSING,
                details="Card has no trust score",
                checked_at=now,
            )

        # Expiry
        if self.max_card_age is not None:
            age = now - card.issued_at
            if age > self.max_card_age:
                return VerificationReport(
                    card_agent_id=card.agent_id,
                    result=VerificationResult.FAIL_EXPIRED,
                    details=f"Card expired: age {age:.0f}s > max {self.max_card_age:.0f}s",
                    checked_at=now,
                )

        # Score
        if card.trust_score < self.min_score:
            return VerificationReport(
                card_agent_id=card.agent_id,
                result=VerificationResult.FAIL_SCORE,
                details=f"Score {card.trust_score:.4f} < required {self.min_score:.4f}",
                checked_at=now,
            )

        # Tier
        if self.min_tier is not None:
            card_rank = self._TIER_RANK.get(card.tier, -1)
            required_rank = self._TIER_RANK[self.min_tier]
            if card_rank < required_rank:
                card_tier_label = card.tier.value if card.tier else "none"
                return VerificationReport(
                    card_agent_id=card.agent_id,
                    result=VerificationResult.FAIL_TIER,
                    details=f"Tier {card_tier_label} < required {self.min_tier.value}",
                    checked_at=now,
                )

        # Attestations
        if card.attestation_count < self.min_attestations:
            return VerificationReport(
                card_agent_id=card.agent_id,
                result=VerificationResult.FAIL_ATTESTATIONS,
                details=f"Attestations {card.attestation_count} < required {self.min_attestations}",
                checked_at=now,
            )

        return VerificationReport(
            card_agent_id=card.agent_id,
            result=VerificationResult.PASS,
            details="All checks passed",
            checked_at=now,
        )


# ---------------------------------------------------------------------------
# TrustGatekeeper
# ---------------------------------------------------------------------------

class GatekeeperDecision(Enum):
    ACCEPT = "accept"
    REJECT = "reject"


@dataclass
class GatekeeperResult:
    """Result of a gatekeeper evaluation."""
    decision: GatekeeperDecision
    agent_id: str
    reason: str = ""
    verification: Optional[VerificationReport] = None

    @property
    def accepted(self) -> bool:
        return self.decision == GatekeeperDecision.ACCEPT


@dataclass
class TrustGatekeeper:
    """
    Middleware-style gate that accepts or rejects A2A tasks
    based on the requesting agent's trust card.

    Usage::

        gk = TrustGatekeeper(min_score=0.4, min_tier=Tier.VERIFIED)
        result = gk.evaluate(incoming_card)
        if result.accepted:
            process_task(...)
    """

    min_score: float = 0.0
    min_tier: Optional[Tier] = None
    min_attestations: int = 0
    max_card_age: Optional[float] = None
    required_capabilities: list[str] = field(default_factory=list)
    allow_unknown_tier: bool = False

    def evaluate(
        self, card: TrustAgentCard, now: Optional[float] = None
    ) -> GatekeeperResult:
        now = now or time.time()

        # Capability check (before trust — cheap)
        if self.required_capabilities:
            missing = [c for c in self.required_capabilities if c not in card.capabilities]
            if missing:
                return GatekeeperResult(
                    decision=GatekeeperDecision.REJECT,
                    agent_id=card.agent_id,
                    reason=f"Missing capabilities: {', '.join(missing)}",
                )

        # Trust verification
        verifier = TrustVerifier(
            min_score=self.min_score,
            min_tier=self.min_tier,
            min_attestations=self.min_attestations,
            max_card_age=self.max_card_age,
        )
        report = verifier.verify(card, now=now)

        if not report.passed:
            return GatekeeperResult(
                decision=GatekeeperDecision.REJECT,
                agent_id=card.agent_id,
                reason=report.details,
                verification=report,
            )

        # Unknown tier handling
        if card.tier is None and self.min_tier is not None and not self.allow_unknown_tier:
            return GatekeeperResult(
                decision=GatekeeperDecision.REJECT,
                agent_id=card.agent_id,
                reason="Tier is unknown and allow_unknown_tier is False",
                verification=report,
            )

        return GatekeeperResult(
            decision=GatekeeperDecision.ACCEPT,
            agent_id=card.agent_id,
            reason="Trust requirements met",
            verification=report,
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def trust_card_to_json(card: TrustAgentCard, **kwargs) -> str:
    """Serialise a TrustAgentCard to JSON."""
    return card.to_json(**kwargs)


def trust_card_from_json(json_str: str) -> TrustAgentCard:
    """Deserialise a TrustAgentCard from JSON."""
    return TrustAgentCard.from_json(json_str)
