"""Polymarket fee calculations.

Source: https://docs.polymarket.com/trading/fees (read 2026-11-17)

    fee = C × feeRate × p × (1 − p)

where C = number of shares traded and p = trade price. Fees are charged in
USDC, to the taker only (``feeSchedule.takerOnly``); makers pay nothing and the
resting maker receives ``rebateRate`` of the taker fee as a daily rebate.
Fees are rounded to 5 decimal places; anything below 0.00001 USDC is zero.

Crypto Up/Down markets (``feeType = crypto_fees_v2``) currently publish
``feeSchedule = {rate: 0.07, exponent: 1, takerOnly: true, rebateRate: 0.2}``.

The docs say ``exponent`` applies to "the price component of the fee curve"
but only publish the exponent = 1 formula. For any other exponent we apply
``C × rate × (p(1−p))^exponent`` and flag the fee as ESTIMATED.

Gas: CLOB order matching and settlement are gasless for the trader (Polymarket
relayer pays gas; see REFERENCE_BOT_ANALYSIS.md). Redemption of winning shares
is also relayed gas-free for proxy/deposit wallets. We therefore record
gas = 0 and network = 0, labelled as estimates.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CRYPTO_FEE_RATE = 0.07
DEFAULT_CRYPTO_FEE_EXPONENT = 1.0
FEE_DECIMALS = 5
MIN_FEE = 0.00001


@dataclass(frozen=True)
class FeeSchedule:
    rate: float = DEFAULT_CRYPTO_FEE_RATE
    exponent: float = DEFAULT_CRYPTO_FEE_EXPONENT
    taker_only: bool = True
    rebate_rate: float = 0.2
    fee_type: str | None = "crypto_fees_v2"
    verified: bool = False  # True when read from the live market's feeSchedule

    @property
    def formula_documented(self) -> bool:
        return abs(self.exponent - 1.0) < 1e-9

    @property
    def estimated(self) -> bool:
        return (not self.verified) or (not self.formula_documented)

    def describe(self) -> str:
        if self.formula_documented:
            return f"fee = shares x {self.rate} x p x (1 - p)  [docs.polymarket.com/trading/fees]"
        return f"fee = shares x {self.rate} x (p(1-p))^{self.exponent}  [ESTIMATED: exponent formula undocumented]"


def round_fee(x: float) -> float:
    v = round(x + 1e-12, FEE_DECIMALS)
    return 0.0 if v < MIN_FEE else v


def taker_fee(shares: float, price: float, schedule: FeeSchedule | None = None) -> float:
    """USDC taker fee for buying/selling ``shares`` at ``price``."""
    s = schedule or FeeSchedule()
    if shares <= 0 or price <= 0 or price >= 1:
        return 0.0
    pq = price * (1.0 - price)
    if s.formula_documented:
        raw = shares * s.rate * pq
    else:
        raw = shares * s.rate * (pq ** s.exponent)
    return round_fee(raw)


def maker_fee(shares: float, price: float, schedule: FeeSchedule | None = None) -> float:
    s = schedule or FeeSchedule()
    if s.taker_only:
        return 0.0
    return taker_fee(shares, price, s)


def schedule_from_market(raw_market: dict | None) -> FeeSchedule:
    """Build a FeeSchedule from a Gamma market payload (``feeSchedule`` field)."""
    if not raw_market:
        return FeeSchedule(verified=False)
    fs = raw_market.get("feeSchedule") or {}
    if not fs or not raw_market.get("feesEnabled", True):
        if raw_market.get("feesEnabled") is False:
            return FeeSchedule(rate=0.0, verified=True, fee_type=raw_market.get("feeType"))
        return FeeSchedule(verified=False, fee_type=raw_market.get("feeType"))
    return FeeSchedule(
        rate=float(fs.get("rate", DEFAULT_CRYPTO_FEE_RATE)),
        exponent=float(fs.get("exponent", DEFAULT_CRYPTO_FEE_EXPONENT)),
        taker_only=bool(fs.get("takerOnly", True)),
        rebate_rate=float(fs.get("rebateRate", 0.0)),
        fee_type=raw_market.get("feeType"),
        verified=True,
    )
