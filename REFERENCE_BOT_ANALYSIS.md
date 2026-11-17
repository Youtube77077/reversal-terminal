# Reference Bot Analysis — "Polybot"

**Inspected:** `C:\Users\rojya\Downloads\polybot (1)\polybot` (read-only; nothing in that folder was modified or executed).
**Identity:** a copy of the open-source *polymarket-trade-engine / "early-bird-engine"* (TypeScript, Bun runtime). `deploy/setup-vm.sh` clones `github.com/KaustubhPatange/polymarket-trade-engine`. `instances/{btc,eth,sol,xrp,doge,hype,bnb}` are seven per-asset copies of the same engine, each with its own `.env`.

Only the **Polymarket integration and execution architecture** was studied. The bot's strategies (`engine/strategy/*`: early-bird, late-entry, snipe, simulation…), signals, market selection, UI, logging format and configuration were deliberately **not** reused.

---

## 0. Security findings (read first)

| Finding | Detail | Action taken |
|---|---|---|
| **Live wallet private keys on disk** | `.env` and every `instances/*/.env` contain a 66-character `PRIVATE_KEY` (a funded Polygon EOA, per the user's description), plus `POLY_FUNDER_ADDRESS`, `BUILDER_KEY`, `BUILDER_SECRET`, `BUILDER_PASSPHRASE`. | Values were **never printed, logged, copied or used**. Only key *names* and *lengths* were inspected to confirm presence. Nothing from those files exists in REVERSAL TERMINAL. |
| Secrets duplicated 8× | Same credential set copied into 7 instance folders. | Recommend: move funds out of that wallet or rotate the key, delete the `.env` copies, and revoke/rotate the Builder API key in Polymarket settings. Do **not** push that folder to GitHub. |
| `instances/*/.git` | Nested git repos; `.env` is git-ignored there, but the folder is easy to upload by mistake. | Noted. |
| Shell-outs | `utils/fetch-retry.ts` can spawn `curl` (`Bun.spawn`) for TLS-compat; `deploy/setup-vm.sh` pipes `curl … bun.sh/install | bash`. | Not used. REVERSAL TERMINAL never shells out for networking. |
| External hosts | Only Polymarket (gamma, clob, relayer-v2, data-api, ws-subscriptions, ws-live-data, polymarket.com/api), Polygon RPC (publicnode), Binance/Coinbase/OKX/Bybit public WS. No unexpected telemetry endpoints found in project source. | — |
| Dependencies | `@polymarket/clob-client`, `@polymarket/clob-client-v2`, `@polymarket/client` (beta), `@polymarket/builder-relayer-client`, `ethers@6`, `@ethersproject/wallet`, `viem`. All official/well-known packages; `@polymarket/client@0.1.0-beta.4` is a pre-release SDK. | Not installed in the new project (paper-only). |

---

## 1. How it connects to Polymarket

| Purpose | Endpoint (from source) | File |
|---|---|---|
| Market metadata by slug | `GET https://gamma-api.polymarket.com/events?slug={asset}-updown-{5m|15m}-{startTs}` | `tracker/api-queue.ts` |
| Open/close reference price | `GET https://polymarket.com/api/crypto/crypto-price?symbol=BTC&variant=fiveminute&eventStartTime=…&endDate=…` | `tracker/api-queue.ts` |
| Live order book | `wss://ws-subscriptions-clob.polymarket.com/ws/market`, subscribe `{"type":"market","assets_ids":[up,down]}` | `tracker/orderbook.ts` |
| Underlying price | `wss://ws-live-data.polymarket.com`, topic `crypto_prices_chainlink` (+ Binance/Coinbase/OKX/Bybit WS) | `tracker/ticker.ts` |
| Order placement / status / cancel | `https://clob.polymarket.com` via SDKs | `engine/client.ts` |
| Fill tracking | `wss://ws-subscriptions-frontend-clob.polymarket.com/ws/user` (authenticated) | `engine/user-channel.ts` |
| Gasless relay | `https://relayer-v2.polymarket.com` | `engine/client.ts` |
| Positions (redeemable) | `https://data-api.polymarket.com/positions?user=…&redeemable=true` | `engine/client.ts` |
| Polygon RPC | `https://polygon-bor-rpc.publicnode.com` | `engine/client.ts` |

**Market discovery** (`utils/slot.ts`): windows are computed deterministically — `slotTs = BASE + floor((now−BASE)/300)*300` — and the slug is `{prefix}-updown-5m-{slotTs}`. No search API is used.

**Outcome tokens** (`engine/market-lifecycle.ts`): `JSON.parse(market.clobTokenIds)` → index 0 = UP, index 1 = DOWN. The order is **assumed**, not checked against `outcomes`.

## 2. Libraries

`@polymarket/client` (new "secure client": `createSecureClient`, `placeMarketOrder`, `placeLimitOrder`, `fetchOrder`, `listOpenOrders`, `cancelOrder(s)`, `fetchBalanceAllowance`, `setupTradingApprovals`, `prepareGaslessTransaction`), `@polymarket/clob-client-v2` (legacy `ClobClient`, `Chain`), `@polymarket/builder-relayer-client` (`RelayClient`, PROXY tx type), `@polymarket/builder-signing-sdk` (`BuilderConfig`), `viem` (contract reads/writes, `encodeFunctionData`), `@ethersproject/wallet`.

## 3. Authentication

1. `PRIVATE_KEY` (EOA) → `privateKey()` signer from `@polymarket/client/viem`.
2. `createSecureClient({ signer, apiKey: builderApiKey({key, secret, passphrase}) })` — the SDK resolves the signer's deterministic **deposit wallet** (ERC-1967 proxy, the maker address the CLOB accepts) and creates/derives **L2 API credentials** (`key/secret/passphrase`) for it.
3. Those L2 creds authenticate the user websocket (`auth: {apiKey, secret, passphrase}`).
4. Builder API key authorises gasless relayer operations.

## 4. Polygon interaction

- Collateral: **pUSD** `0xC011a7E1…2DFB` (wrapped from USDC.e `0x2791…4174` via OnRamp `0x9307…f5B8ee`; unwrap via OffRamp `0x2957…5854`).
- Balance: `balanceOf(depositWallet)` on pUSD via a viem public client.
- Approvals: `setupTradingApprovals()` (deposit wallet → exchange), or direct `approve()` for plain EOAs (pays POL gas).
- Redemption: `redeemPositions(USDC.e, 0x0, conditionId, [1,2])` on the Gnosis CTF `0x4D97…6045`, executed **gaslessly** through `prepareGaslessTransaction` (sign typed data / messages step-by-step), then wrapping the USDC.e back to pUSD.

## 5. Order construction

`MultiOrderRequest {tokenId, action, price, shares, tickSize, negRisk, orderType}` → `postMultipleOrders`:
- **FOK buy** → `placeMarketOrder({side: BUY, amount: max(shares*price, 1), maxSpend: amount*1.2, orderType: FOK})` — floors at the **$1 minimum marketable notional**.
- **FOK sell** → `placeMarketOrder({side: SELL, shares})`.
- **GTC** → `placeLimitOrder({tokenId, price, size, side})`.
- Tick size comes from the book's `tick_size` / `tick_size_change` events (default 0.01). Signing is done inside the SDK (EIP-712 order struct for the CTF Exchange).

## 6. Order submission & 7. Fill tracking

`market-lifecycle.ts` locks funds in a local `WalletTracker`, calls `postMultipleOrders`, and on `"not enough balance"` parses the CLOB error (`balance: X … order amount: Y`) to resize and retry. Successful orders are registered with `UserChannel.trackOrder()`:
- `UPDATE` + `MATCHED` (maker) or `TRADE` + `MATCHED` (taker — takers never get an order-update MATCHED) marks the order matched;
- `TRADE` + `MINED` credits `matched_amount` per maker order; settlement fires `onFilled(gross)`; `FAILED` fires `onFailed`;
- buffers events that arrive before `trackOrder` (race-safe); `untrackOrder` refuses to drop matched-but-unmined orders.
Status mapping: `matched→filled`, `live/unmatched→live`, `delayed→delayed`, else `cancelled`. Partial fills come from `size_matched`.

## 8. Balances

`getUSDCBalance()` = on-chain pUSD of the deposit wallet; `getAvailableShares(tokenId)` = `fetchBalanceAllowance({assetType: CONDITIONAL, tokenId})/1e6`. A local `WalletTracker` mirrors reserved buys/sells to avoid over-committing between on-chain updates. In simulation the client returns `Infinity`.

## 9. Fees

Reads `market.feeSchedule.rate` from Gamma and applies, for FOK (taker) fills only:
`fee = gross_shares × rate × price × (1 − price)`, reducing received shares by `fee/price`. Maker (GTC) fills pay nothing. The orderbook also stores `fee_rate_bps` from `last_trade_price` events (default 1000 bps).

## 10. Suitable as technical reference

- Deterministic slug discovery and the `crypto-price` reference endpoint (both re-verified live on 2026-11-17).
- Public market websocket + Chainlink RTDS subscription formats.
- Fill lifecycle semantics (MATCHED vs MINED, taker vs maker signalling, early-event buffering).
- Exchange constraints encoded in practice: $1 min marketable notional, 5-share min, tick size changes, taker-only fees.
- Exponential-backoff reconnecting websocket pattern.

## 11. Outdated / not to reuse

| Item | Why |
|---|---|
| `data-api.polymarket.com/positions` (v1) | **Retired** — the API now returns `"Data API v1 has been retired"`; v2 is required. |
| Mixed SDKs (`clob-client`, `clob-client-v2`, `@polymarket/client` beta) | Code comments describe the v2 order path as "fundamentally rejected"; relies on a beta SDK. |
| Token ordering assumption (index 0 = UP) | Fragile — REVERSAL TERMINAL maps tokens by outcome label and records any deviation. |
| Settlement assumption | The bot predates/ignores the **60-second Chainlink TWAP** settlement now stated in market rules (`cryptoMarketConfig.twapLookbackSeconds = 60`). |
| Sim fill model (`isSimFilled`) | Fills an entire order if best-level liquidity > 2× cost — no book walk, no partial fills, no fees in sim. |
| Private keys in plain `.env` ×8 | Unsafe secret handling. |
| `process.exit()` on stale feeds | One failed feed kills the bot; REVERSAL TERMINAL isolates failures per asset/provider. |
| Fee default 1000 bps | Not the current crypto schedule (rate 0.07, `crypto_fees_v2`). |

## 12. How REVERSAL TERMINAL implements its own equivalent (paper)

| Concern | Reference bot | REVERSAL TERMINAL |
|---|---|---|
| Discovery | slug from slot math | same slug rule, verified each window via Gamma; unavailable markets shown as unavailable; substitutions recorded (`providers/polymarket/discovery.py`) |
| Outcome ids | positional | by label; Gamma `outcomePrices` re-ordered by label for the official winner |
| Book | WS market channel | same channel, full snapshot on (re)subscribe, dynamic subscribe/unsubscribe, PING heartbeat, silence watchdog (`market_ws.py`) |
| Underlying | multi-exchange WS | Chainlink via RTDS (all 7 symbols, one socket) + Binance cross-check (`rtds.py`, `spot/binance.py`) |
| Execution interface | `EarlyBirdClient` (sim + real) | `ExecutionAdapter` (`execution/base.py`) with `PaperExecutionAdapter` and an **inert** `PolymarketLiveAdapter` that always raises `LiveTradingUnavailable` |
| Paper fills | best-level ≥ 2× cost | latency-delayed (400 ms default) **book walk** against the live book, limit price respected, FAK/FOK, partial fills, min size/notional/tick validation, passive orders filled only on trade-through (`execution/simulator.py`, `paper.py`) |
| Fees | rate·p·(1−p) on taker | same documented formula, rate read per market, 5-dp rounding, flagged *estimated* when unverified (`providers/polymarket/fees.py`) |
| Balances | on-chain + local tracker | virtual cash/reserved per account with a full ledger; never negative (`execution/accounting.py`) |
| Settlement | redeem on-chain | official Gamma resolution only; crypto-price API as cross-check (`collector._resolve_one`) |
| Fill tracking | user WS MATCHED/MINED | simulated synchronously; order/fill/fee rows persisted with decision + execution book snapshots |
| Live mode | enabled with a Y prompt | optional, isolated `executor/` process with the same SDK path; gated by LIVE_TRADING_ENABLED, keys in server env only, password-armed, per-order + per-session caps, session stop loss |
