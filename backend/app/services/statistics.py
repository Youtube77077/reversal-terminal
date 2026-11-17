"""Statistical helpers: Wilson intervals, Brier score, log loss, EV, tests."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from scipy import stats as _st

from ..constants import MIN_SAMPLE_SOLID, MIN_SAMPLE_WARNING


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float | None, float | None]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (None, None)
    z = _st.norm.ppf(1 - (1 - confidence) / 2)
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    lo, hi = centre - half, centre + half
    return (0.0 if lo < 1e-12 else lo, 1.0 if hi > 1 - 1e-12 else hi)


def sample_flag(n: int) -> str:
    if n < MIN_SAMPLE_WARNING:
        return "insufficient"
    if n < MIN_SAMPLE_SOLID:
        return "small"
    return "ok"


@dataclass
class RateStat:
    n: int
    k: int
    rate: float | None
    ci_low: float | None
    ci_high: float | None
    sample: str

    def dict(self) -> dict:
        return asdict(self)


def rate_stat(k: int, n: int) -> RateStat:
    lo, hi = wilson_interval(k, n)
    return RateStat(n=n, k=k, rate=(k / n) if n else None, ci_low=lo, ci_high=hi, sample=sample_flag(n))


def brier_score(probs: list[float], outcomes: list[int]) -> float | None:
    if not probs:
        return None
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def log_loss(probs: list[float], outcomes: list[int], eps: float = 1e-6) -> float | None:
    if not probs:
        return None
    tot = 0.0
    for p, o in zip(probs, outcomes):
        p = min(max(p, eps), 1 - eps)
        tot += -(o * math.log(p) + (1 - o) * math.log(1 - p))
    return tot / len(probs)


def calibration_error(probs: list[float], outcomes: list[int]) -> float | None:
    """Mean implied probability minus realised frequency (positive = overconfident)."""
    if not probs:
        return None
    return sum(probs) / len(probs) - sum(outcomes) / len(outcomes)


def break_even_probability(price: float, fee_per_share: float = 0.0, slippage_per_share: float = 0.0,
                           other_per_share: float = 0.0) -> float:
    """Win probability at which buying one $1-payout share at ``price`` has zero EV."""
    return price + fee_per_share + slippage_per_share + other_per_share


def expected_value(p_win: float, net_if_win: float, net_if_loss: float) -> float:
    return p_win * net_if_win + (1 - p_win) * net_if_loss


def binomial_p_value_greater(k: int, n: int, p0: float) -> float | None:
    """One-sided p-value for H1: true win rate > p0."""
    if n <= 0 or p0 <= 0 or p0 >= 1:
        return None
    return float(_st.binomtest(k, n, p0, alternative="greater").pvalue)


def max_drawdown(equity_curve: list[float]) -> tuple[float, float]:
    """Returns (max drawdown in $, max drawdown as fraction of peak)."""
    peak = -math.inf
    mdd = 0.0
    mdd_pct = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        dd = peak - v
        if dd > mdd:
            mdd = dd
            mdd_pct = dd / peak if peak > 0 else 0.0
    return mdd, mdd_pct


def mean_ci(values: list[float], confidence: float = 0.95) -> tuple[float | None, float | None, float | None]:
    n = len(values)
    if n == 0:
        return (None, None, None)
    m = sum(values) / n
    if n < 2:
        return (m, None, None)
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    t = _st.t.ppf(1 - (1 - confidence) / 2, n - 1)
    half = t * sd / math.sqrt(n)
    return (m, m - half, m + half)
