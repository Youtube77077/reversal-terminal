// REVERSAL TERMINAL — live order executor.
//
// The ONLY process that holds Polymarket credentials. It exposes a tiny HTTP API on
// 127.0.0.1 to the Python backend (bearer-token protected). Order placement follows the
// exact path of the user's previously working reference bot (Polybot engine/client.ts):
//   @polymarket/client createSecureClient(privateKey signer + builder API key)
//   -> deterministic deposit wallet (the maker the CLOB accepts for self-custody API trading)
//   -> placeLimitOrder / fetchOrder / cancelOrder
//   -> gasless CTF redeemPositions for resolved markets, then wrap USDC.e -> pUSD.
//
// Safety: refuses orders unless LIVE_TRADING_ENABLED=true; per-order hard cap
// EXECUTOR_MAX_ORDER_USD; BUY-only price-capped limit orders whose remainder is cancelled.

import http from "node:http";
import { createSecureClient, OrderSide } from "@polymarket/client";
import { prepareGaslessTransaction } from "@polymarket/client/actions";
import { privateKey } from "@polymarket/client/viem";
import { builderApiKey } from "@polymarket/client/node";
import { createPublicClient, encodeFunctionData, http as viemHttp, parseAbi, zeroHash } from "viem";
import { polygon } from "viem/chains";

const env = (k, ...alts) => [k, ...alts].map((x) => process.env[x]).find((v) => v && v.length) || "";
const PORT = Number(env("EXECUTOR_PORT") || 8787);
const HOST = env("EXECUTOR_HOST") || "127.0.0.1";
const TOKEN = env("EXECUTOR_TOKEN");
const LIVE = env("LIVE_TRADING_ENABLED").toLowerCase() === "true";
const MAX_ORDER_USD = Number(env("EXECUTOR_MAX_ORDER_USD", "LIVE_MAX_ORDER_USD") || 5);
const RPC = env("POLYGON_RPC") || "https://polygon-bor-rpc.publicnode.com";

// Polygon contracts (same as the reference bot)
const USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB";
const CONDITIONAL_TOKENS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045";
const ONRAMP = "0x93070a847efEf7F70739046A929D47a521F5B8ee";
const ERC20 = parseAbi(["function approve(address spender, uint256 amount) returns (bool)",
  "function balanceOf(address owner) view returns (uint256)"]);
const RAMP = parseAbi(["function wrap(address _asset, address _to, uint256 _amount)"]);
const CTF = parseAbi(["function redeemPositions(address collateralToken, bytes32 parentCollectionId, bytes32 conditionId, uint256[] indexSets)"]);

const state = { ready: false, error: null, wallet: null, startedAt: Date.now(), orders: 0, rejects: 0 };
let secure = null;
let signer = null;
const pub = createPublicClient({ chain: polygon, transport: viemHttp(RPC) });
const redeemed = new Set();

function log(...a) { console.log(new Date().toISOString(), "[executor]", ...a); }

async function init() {
  const pk = env("POLYMARKET_PRIVATE_KEY", "PRIVATE_KEY");
  const bk = env("POLYMARKET_BUILDER_KEY", "BUILDER_KEY");
  const bs = env("POLYMARKET_BUILDER_SECRET", "BUILDER_SECRET");
  const bp = env("POLYMARKET_BUILDER_PASSPHRASE", "BUILDER_PASSPHRASE");
  if (!pk || !bk || !bs || !bp) {
    state.error = "credentials not configured (POLYMARKET_PRIVATE_KEY + POLYMARKET_BUILDER_KEY/SECRET/PASSPHRASE)";
    log(state.error);
    return;
  }
  if (!pk.startsWith("0x") || pk.length !== 66) {
    state.error = "POLYMARKET_PRIVATE_KEY must be a 0x-prefixed 32-byte hex key";
    log(state.error);
    return;
  }
  try {
    signer = privateKey(pk);
    secure = await createSecureClient({ signer, apiKey: builderApiKey({ key: bk, secret: bs, passphrase: bp }) });
    state.wallet = secure.account?.wallet ?? null;
    try { const h = await secure.setupTradingApprovals(); if (h?.wait) await h.wait(); } catch { /* already set */ }
    state.ready = true;
    state.error = null;
    log("ready; deposit wallet", state.wallet, "live orders", LIVE ? "ENABLED" : "disabled");
  } catch (e) {
    state.error = `init failed: ${e?.message ?? e}`;
    log(state.error);
    setTimeout(init, 30_000);
  }
}

async function usdcBalance() {
  if (!state.wallet) return 0;
  const bal = await pub.readContract({ address: PUSD, abi: ERC20, functionName: "balanceOf", args: [state.wallet] });
  return Number(bal) / 1e6;
}

async function fetchOrder(orderId) {
  const o = await secure.fetchOrder({ orderId });
  if (!o) return null;
  return {
    id: o.id, status: String(o.status ?? "").toLowerCase(), price: Number(o.price ?? 0),
    size: Number(o.original_size ?? o.originalSize ?? o.size ?? 0),
    sizeMatched: Number(o.size_matched ?? o.sizeMatched ?? 0),
  };
}

async function placeLimitFak({ tokenId, price, size, waitMs = 2500 }) {
  if (!LIVE) return { ok: false, error: "LIVE_TRADING_ENABLED is not true on the executor" };
  if (!state.ready) return { ok: false, error: state.error || "executor not ready" };
  price = Number(price); size = Number(size);
  if (!tokenId || !(price > 0 && price < 1) || !(size > 0)) return { ok: false, error: "invalid order parameters" };
  if (price * size > MAX_ORDER_USD + 1e-9) return { ok: false, error: `notional $${(price * size).toFixed(2)} > cap $${MAX_ORDER_USD}` };
  state.orders++;
  let resp;
  try {
    resp = await secure.placeLimitOrder({ tokenId, price, size, side: OrderSide.BUY });
  } catch (e) {
    state.rejects++;
    return { ok: false, error: e?.message ?? String(e) };
  }
  const orderId = resp?.orderId;
  if (resp?.ok === false || !orderId) {
    state.rejects++;
    return { ok: false, error: String(resp?.error ?? resp?.errorMsg ?? "rejected") };
  }
  await new Promise((r) => setTimeout(r, Math.min(10_000, Math.max(500, waitMs))));
  let o = await fetchOrder(orderId).catch(() => null);
  let note = null;
  if (!o || o.sizeMatched < size - 1e-6) {
    try { await secure.cancelOrder({ orderId }); } catch { /* already done */ }
    await new Promise((r) => setTimeout(r, 800));
    o = (await fetchOrder(orderId).catch(() => null)) || o;
    note = "unfilled remainder cancelled";
  }
  const matched = o?.sizeMatched ?? 0;
  log(`order ${orderId} BUY ${size}@${price} matched ${matched}`);
  return { ok: true, orderId, status: o?.status ?? resp?.status ?? "unknown", sizeMatched: matched,
           avgPrice: price, note };
}

async function runGasless(calls, metadata) {
  const wf = await prepareGaslessTransaction(secure, { calls, metadata });
  let step = await wf.next();
  while (!step.done) {
    const req = step.value;
    let answer;
    if (req.kind === "requestAddress") answer = await signer.getAddress();
    else if (req.kind === "signGaslessTypedData") answer = await signer.signTypedData(req.payload);
    else if (req.kind === "signGaslessMessage") answer = await signer.signMessage(req.payload);
    else throw new Error(`unexpected gasless step: ${req.kind}`);
    step = await wf.next(answer);
  }
  if (step.value?.wait) await step.value.wait();
}

async function redeem(conditionId) {
  if (!state.ready) return { ok: false, error: "executor not ready" };
  if (!/^0x[0-9a-fA-F]{64}$/.test(conditionId || "")) return { ok: false, error: "invalid conditionId" };
  if (redeemed.has(conditionId)) return { ok: true, note: "already redeemed" };
  let last;
  for (let attempt = 1; attempt <= 4; attempt++) {
    try {
      const data = encodeFunctionData({ abi: CTF, functionName: "redeemPositions",
        args: [USDC_E, zeroHash, conditionId, [1n, 2n]] });
      await runGasless([{ to: CONDITIONAL_TOKENS, data, value: 0n }], "Redeem positions");
      const amt = await pub.readContract({ address: USDC_E, abi: ERC20, functionName: "balanceOf", args: [state.wallet] });
      if (amt > 0n) {
        await runGasless([
          { to: USDC_E, data: encodeFunctionData({ abi: ERC20, functionName: "approve", args: [ONRAMP, amt] }), value: 0n },
          { to: ONRAMP, data: encodeFunctionData({ abi: RAMP, functionName: "wrap", args: [USDC_E, state.wallet, amt] }), value: 0n },
        ], "Wrap USDC.e to pUSD");
      }
      redeemed.add(conditionId);
      log("redeemed", conditionId);
      return { ok: true };
    } catch (e) {
      last = e;
      await new Promise((r) => setTimeout(r, attempt * 2000));
    }
  }
  return { ok: false, error: last?.message ?? String(last) };
}

// ---------------------------------------------------------------- HTTP
function send(res, code, body) {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve) => {
    let d = "";
    req.on("data", (c) => { d += c; if (d.length > 1e5) req.destroy(); });
    req.on("end", () => { try { resolve(d ? JSON.parse(d) : {}); } catch { resolve({}); } });
  });
}

const server = http.createServer(async (req, res) => {
  const auth = req.headers.authorization || "";
  if (TOKEN && auth !== `Bearer ${TOKEN}`) return send(res, 401, { ok: false, error: "unauthorized" });
  const url = new URL(req.url, "http://x");
  try {
    if (req.method === "GET" && url.pathname === "/health") {
      return send(res, 200, { ok: state.ready, liveEnabled: LIVE, wallet: state.wallet, error: state.error,
        maxOrderUsd: MAX_ORDER_USD, orders: state.orders, rejects: state.rejects, uptimeS: (Date.now() - state.startedAt) / 1000 });
    }
    if (req.method === "GET" && url.pathname === "/balance") {
      if (!state.ready) return send(res, 503, { ok: false, error: state.error });
      return send(res, 200, { ok: true, usdc: await usdcBalance(), wallet: state.wallet });
    }
    if (req.method === "POST" && url.pathname === "/order") return send(res, 200, await placeLimitFak(await readBody(req)));
    if (req.method === "GET" && url.pathname.startsWith("/order/")) {
      if (!state.ready) return send(res, 503, { ok: false, error: state.error });
      return send(res, 200, { ok: true, order: await fetchOrder(url.pathname.split("/")[2]) });
    }
    if (req.method === "POST" && url.pathname === "/cancel") {
      if (!state.ready) return send(res, 503, { ok: false, error: state.error });
      const { orderId } = await readBody(req);
      await secure.cancelOrder({ orderId });
      return send(res, 200, { ok: true });
    }
    if (req.method === "POST" && url.pathname === "/redeem") return send(res, 200, await redeem((await readBody(req)).conditionId));
    return send(res, 404, { ok: false, error: "not found" });
  } catch (e) {
    return send(res, 500, { ok: false, error: e?.message ?? String(e) });
  }
});

server.listen(PORT, HOST, () => log(`listening on ${HOST}:${PORT}`));
init();
