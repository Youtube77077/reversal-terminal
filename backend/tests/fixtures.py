"""Simulated market fixtures (shapes copied from live Gamma / CLOB payloads, values synthetic)."""
import json

GAMMA_EVENT = {
    "id": "1403032",
    "slug": "btc-updown-5m-1794933300",
    "title": "Bitcoin Up or Down - November 17, 11:35AM-11:40AM ET",
    "startTime": "2026-11-17T16:35:00Z",
    "endDate": "2026-11-17T16:40:00Z",
    "restricted": True,
    "markets": [{
        "id": "7096645",
        "question": "Bitcoin Up or Down - November 17, 11:35AM-11:40AM ET",
        "conditionId": "0xabc",
        "questionID": "0xdef",
        "slug": "btc-updown-5m-1794933300",
        "resolutionSource": "https://data.chain.link/streams/btc-usd-twap-60s-streams",
        "endDate": "2026-11-17T16:40:00Z",
        "eventStartTime": "2026-11-17T16:35:00Z",
        "outcomes": json.dumps(["Up", "Down"]),
        "outcomePrices": json.dumps(["0.505", "0.495"]),
        "clobTokenIds": json.dumps(["111", "222"]),
        "active": True, "closed": False, "acceptingOrders": True,
        "orderPriceMinTickSize": 0.01, "orderMinSize": 5, "negRisk": False,
        "feesEnabled": True, "feeType": "crypto_fees_v2",
        "feeSchedule": {"exponent": 1, "rate": 0.07, "takerOnly": True, "rebateRate": 0.2},
        "cryptoMarketConfig": {"id": "btc-5m-twap-60", "asset": "btc", "duration": "5m", "twapEnabled": True,
                               "twapLookbackSeconds": 60},
        "resolutionMechanism": "oracle",
    }],
}


def resolved_event(winner: str = "DOWN", swap_outcomes: bool = False) -> dict:
    ev = json.loads(json.dumps(GAMMA_EVENT))
    m = ev["markets"][0]
    m["closed"] = True
    m["umaResolutionStatus"] = "resolved"
    m["outcomePrices"] = json.dumps(["1", "0"] if winner == "UP" else ["0", "1"])
    if swap_outcomes:
        m["outcomes"] = json.dumps(["Down", "Up"])
        m["clobTokenIds"] = json.dumps(["222", "111"])
        m["outcomePrices"] = json.dumps(list(reversed(json.loads(m["outcomePrices"]))))
    return ev


BOOK_THIN_UNDERDOG = [(0.02, 40.0), (0.03, 100.0), (0.05, 500.0)]  # asks for a cheap outcome
