"""
Sanctum RL — Learned behavior policy for Frank's Inner Sanctum.

Replaces LLM-driven discrete decisions (move, silence, entity spawn) with
a tiny PPO-trained neural network (~8K params). LLM only generates narrative.
"""

_policy = None


def get_sanctum_policy():
    """Singleton accessor for the trained SanctumPolicy."""
    global _policy
    if _policy is None:
        from .integration import SanctumPolicy
        _policy = SanctumPolicy()
    return _policy
