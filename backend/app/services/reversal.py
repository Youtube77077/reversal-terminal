"""Reversal classification — four distinct, never-mixed event types.

A. Probability reversal   — the side with the higher implied probability at the
                            observation timestamp ultimately loses.
B. Price crossover        — UP and DOWN implied prices cross (leader changes) at
                            any point during the market's remaining lifetime.
C. Underlying reversal    — the underlying's short-term direction at the
                            observation (10 s momentum sign) is opposite to its
                            net move from the observation to the final observed
                            price before settlement.
D. Settlement reversal    — the official resolution differs from the market's
                            late-stage expectation (the favourite at the last
                            observation before close, typically T-1).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Classification:
    favourite_lost: bool | None
    underdog_won: bool | None
    price_crossover_after: bool | None
    underlying_reversal: bool | None
    settlement_reversal: bool | None


def _sign(x: float | None) -> int:
    if x is None or x == 0:
        return 0
    return 1 if x > 0 else -1


def leader(up_prob: float | None) -> str | None:
    if up_prob is None or up_prob == 0.5:
        return None
    return "UP" if up_prob > 0.5 else "DOWN"


def classify(
    favourite: str | None,
    winner: str | None,
    later_up_probs: list[float | None],
    spot_at_obs: float | None,
    mom10_at_obs: float | None,
    final_spot: float | None,
    late_favourite: str | None,
) -> Classification:
    valid_winner = winner in ("UP", "DOWN")
    fav_lost = (favourite != winner) if (favourite and valid_winner) else None
    crossover = None
    if favourite:
        leaders = [leader(p) for p in later_up_probs if p is not None]
        crossover = any(l is not None and l != favourite for l in leaders) if leaders else None
    und = None
    s_m, s_move = _sign(mom10_at_obs), _sign((final_spot - spot_at_obs) if (final_spot and spot_at_obs) else None)
    if s_m != 0 and s_move != 0:
        und = s_m != s_move
    settle = (late_favourite != winner) if (late_favourite and valid_winner) else None
    return Classification(
        favourite_lost=fav_lost,
        underdog_won=fav_lost,
        price_crossover_after=crossover,
        underlying_reversal=und,
        settlement_reversal=settle,
    )
