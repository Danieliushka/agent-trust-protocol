"""
TrustScore v0.1 — Behavioral reputation scoring for agents.

Computes a trust score based on:
- Attestation count and recency (from isnad Layer 1)
- Interaction success rate
- Peer endorsement weight
- Account age decay factor

Score range: 0.0 (untrusted) to 1.0 (fully trusted)
"""

import math
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Interaction:
    """A recorded interaction between two agents."""
    timestamp: float
    success: bool
    weight: float = 1.0  # importance of this interaction
    context: str = ""


@dataclass
class PeerEndorsement:
    """An endorsement from another agent."""
    endorser_id: str
    endorser_trust: float  # how much WE trust the endorser (0-1)
    timestamp: float
    strength: float = 1.0  # endorsement strength (0-1)


@dataclass
class AgentProfile:
    """Trust profile for an agent."""
    agent_id: str
    created_at: float = field(default_factory=time.time)
    interactions: list[Interaction] = field(default_factory=list)
    endorsements: list[PeerEndorsement] = field(default_factory=list)
    attestation_count: int = 0
    last_attestation: Optional[float] = None


# --- Scoring weights ---
W_INTERACTION = 0.35
W_ENDORSEMENT = 0.25
W_ATTESTATION = 0.25
W_AGE = 0.15

# Time decay: half-life in seconds (30 days)
HALF_LIFE = 30 * 24 * 3600


def _time_decay(timestamp: float, now: Optional[float] = None) -> float:
    """Exponential time decay with configurable half-life."""
    now = now or time.time()
    age = max(0, now - timestamp)
    return math.pow(0.5, age / HALF_LIFE)


def _interaction_score(interactions: list[Interaction], now: Optional[float] = None) -> float:
    """Score from interaction history (recency-weighted success rate)."""
    if not interactions:
        return 0.0
    
    weighted_sum = 0.0
    weight_total = 0.0
    
    for ix in interactions:
        decay = _time_decay(ix.timestamp, now)
        w = ix.weight * decay
        weighted_sum += w * (1.0 if ix.success else 0.0)
        weight_total += w
    
    if weight_total == 0:
        return 0.0
    return weighted_sum / weight_total


def _endorsement_score(endorsements: list[PeerEndorsement], now: Optional[float] = None) -> float:
    """Score from peer endorsements (trust-weighted, time-decayed)."""
    if not endorsements:
        return 0.0
    
    weighted_sum = 0.0
    weight_total = 0.0
    
    for e in endorsements:
        decay = _time_decay(e.timestamp, now)
        w = e.endorser_trust * e.strength * decay
        weighted_sum += w
        weight_total += max(e.endorser_trust * decay, 0.01)
    
    if weight_total == 0:
        return 0.0
    return min(1.0, weighted_sum / weight_total)


def _attestation_score(count: int, last_attestation: Optional[float] = None, now: Optional[float] = None) -> float:
    """Score from isnad attestation count and recency."""
    if count == 0:
        return 0.0
    
    # Logarithmic scaling: diminishing returns after ~10 attestations
    count_factor = min(1.0, math.log(1 + count) / math.log(11))
    
    # Recency bonus
    recency = 1.0
    if last_attestation is not None:
        recency = _time_decay(last_attestation, now)
    
    return count_factor * (0.7 + 0.3 * recency)


def _age_score(created_at: float, now: Optional[float] = None) -> float:
    """Score from account age (older = more trusted, with diminishing returns)."""
    now = now or time.time()
    age_days = max(0, (now - created_at)) / 86400
    # Sigmoid: reaches ~0.5 at 30 days, ~0.9 at 180 days
    return 1.0 / (1.0 + math.exp(-0.03 * (age_days - 30)))


def compute_trust_score(profile: AgentProfile, now: Optional[float] = None) -> dict:
    """
    Compute the TrustScore for an agent.
    
    Returns dict with overall score and component breakdown.
    """
    now = now or time.time()
    
    i_score = _interaction_score(profile.interactions, now)
    e_score = _endorsement_score(profile.endorsements, now)
    a_score = _attestation_score(profile.attestation_count, profile.last_attestation, now)
    age = _age_score(profile.created_at, now)
    
    overall = (
        W_INTERACTION * i_score +
        W_ENDORSEMENT * e_score +
        W_ATTESTATION * a_score +
        W_AGE * age
    )
    
    return {
        "agent_id": profile.agent_id,
        "trust_score": round(overall, 4),
        "components": {
            "interaction": round(i_score, 4),
            "endorsement": round(e_score, 4),
            "attestation": round(a_score, 4),
            "age": round(age, 4),
        },
        "weights": {
            "interaction": W_INTERACTION,
            "endorsement": W_ENDORSEMENT,
            "attestation": W_ATTESTATION,
            "age": W_AGE,
        },
        "interactions_count": len(profile.interactions),
        "endorsements_count": len(profile.endorsements),
        "attestation_count": profile.attestation_count,
        "computed_at": now,
    }
