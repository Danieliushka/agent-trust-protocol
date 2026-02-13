"""
isnad→TrustScore Bridge — connects provenance attestations to behavioral reputation.

Attestations ARE interactions. When agent A witnesses agent B's work,
that's a cryptographically signed endorsement. Chain length = reputation depth.
"""

import sys
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# Add isnad to path
ISNAD_PATH = os.path.expanduser("~/projects/isnad-ref-impl")
if ISNAD_PATH not in sys.path:
    sys.path.insert(0, ISNAD_PATH)

from isnad import Attestation, TrustChain, AgentIdentity
from trustscore.score import (
    Interaction, PeerEndorsement, AgentProfile, compute_trust_score
)


def _iso_to_epoch(ts: str) -> float:
    """Convert ISO timestamp to epoch seconds."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return time.time()


@dataclass
class BridgeConfig:
    """Configuration for attestation→trust conversion."""
    attestation_weight: float = 1.5
    endorsement_strength: float = 0.8
    default_endorser_trust: float = 0.5
    freshness_window: float = 86400 * 30  # 30 days
    min_attestations_for_endorsement: int = 2


class IsnadBridge:
    """Bridge between isnad TrustChain and TrustScore profiles."""

    def __init__(self, config: Optional[BridgeConfig] = None):
        self.config = config or BridgeConfig()
        self._trust_cache: dict[str, float] = {}

    def set_endorser_trust(self, agent_id: str, trust: float):
        """Set known trust level for an endorsing agent."""
        self._trust_cache[agent_id] = max(0.0, min(1.0, trust))

    def _get_endorser_trust(self, agent_id: str) -> float:
        return self._trust_cache.get(agent_id, self.config.default_endorser_trust)

    def attestation_to_interaction(
        self, attestation: Attestation, verified: Optional[bool] = None
    ) -> Interaction:
        """Convert attestation → Interaction.

        verified=None means auto-verify via attestation.verify().
        """
        if verified is None:
            verified = attestation.verify()

        epoch = _iso_to_epoch(attestation.timestamp)
        age = time.time() - epoch
        freshness = max(0.0, 1.0 - (age / self.config.freshness_window))
        weight = self.config.attestation_weight * (0.5 + 0.5 * freshness)

        return Interaction(
            timestamp=epoch,
            success=verified,
            weight=weight,
            context=f"isnad:{attestation.attestation_id[:12]}",
        )

    def attestations_to_endorsements(
        self, attestations: list[Attestation]
    ) -> list[PeerEndorsement]:
        """Extract peer endorsements from attestation list.

        Each witness endorses the subject. Multiple attestations from
        different witnesses = stronger endorsement signal.
        """
        if len(attestations) < self.config.min_attestations_for_endorsement:
            return []

        endorsements = []
        seen_witnesses = set()

        for i, att in enumerate(attestations):
            if not att.verify():
                continue
            if att.witness in seen_witnesses:
                continue  # one endorsement per witness
            seen_witnesses.add(att.witness)

            depth_factor = min((i + 1) / 5.0, 1.0)
            endorsements.append(
                PeerEndorsement(
                    endorser_id=att.witness,
                    endorser_trust=self._get_endorser_trust(att.witness),
                    timestamp=_iso_to_epoch(att.timestamp),
                    strength=self.config.endorsement_strength * depth_factor,
                )
            )

        return endorsements

    def chain_to_profile(
        self, chain: TrustChain, agent_id: str
    ) -> AgentProfile:
        """Build AgentProfile from a TrustChain for a specific agent."""
        # Get attestations where agent is subject (work they did)
        subject_atts = chain._by_subject.get(agent_id, [])
        # Get attestations where agent is witness (their endorsements of others)
        witness_atts = chain._by_witness.get(agent_id, [])

        # Interactions = attestations about this agent's work
        interactions = [self.attestation_to_interaction(att) for att in subject_atts]

        # Endorsements = other agents witnessing this agent's work
        endorsements = self.attestations_to_endorsements(subject_atts)

        # Also count witness activity as interactions (agent actively participating)
        for att in witness_atts:
            interactions.append(Interaction(
                timestamp=_iso_to_epoch(att.timestamp),
                success=att.verify(),
                weight=self.config.attestation_weight * 0.5,  # witnessing = lower weight
                context=f"isnad-witness:{att.attestation_id[:12]}",
            ))

        all_atts = subject_atts + witness_atts
        timestamps = [_iso_to_epoch(a.timestamp) for a in all_atts]

        return AgentProfile(
            agent_id=agent_id,
            created_at=min(timestamps) if timestamps else time.time(),
            interactions=interactions,
            endorsements=endorsements,
            attestation_count=len(all_atts),
            last_attestation=max(timestamps) if timestamps else None,
        )

    def compute_trust_from_chain(
        self, chain: TrustChain, agent_id: str
    ) -> dict:
        """End-to-end: TrustChain → trust score dict with full breakdown."""
        profile = self.chain_to_profile(chain, agent_id)
        return compute_trust_score(profile)

    def compare_agents(
        self, chain: TrustChain, agent_ids: list[str]
    ) -> list[dict]:
        """Compare trust scores for multiple agents from the same chain."""
        results = []
        for aid in agent_ids:
            score = self.compute_trust_from_chain(chain, aid)
            results.append(score)
        return sorted(results, key=lambda x: x["trust_score"], reverse=True)
