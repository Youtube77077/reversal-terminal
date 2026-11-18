// REVERSAL TERMINAL — live order executor (multi-wallet).
//
// The ONLY process that holds Polymarket credentials. One Polymarket client per wallet
// ("main", "w2", …). Exposes a token-protected HTTP API on 127.0.0.1 to the Python backend.
// Order path = the user's previously working reference bot (Polybot engine/client.ts):
//   @polymarket/client createSecureClient(privateKey signer [+ relayer/builder key] [, wallet])
//   -> placeLimitOrder / fetchOrder / cancelOrder; gasless CTF redeem; wrap USDC.e -> pUSD.
// Safety: refuses orders unless live is enabled; per-order cap; BUY-only price-capped limit
// orders whose unfilled remainder is cancelled.

import http from "node:http";
import { createSecureClient, OrderSide, relayerApiKey } from "@polymarket/client";
import { prepareGaslessTransaction } from "@polymarket/client/actions";
import { privateKey } from "@polymarket/client/viem";
import { builderApiKey } from "@polymarket/client/node";
import { createPublicClient, encodeFunctionData, http as viemHttp, parseAbi, zeroHash } from "viem";
import { polygon } from "viem/chains";

const env = (k, ...alts) => [k, ...alts].map((x) => process.env[x]).find((v) => v && v.length) || "";
const PORT = Number(env("EXECUTOR_PORT") || 8787);
const HOST = env("EXECUTOR_HOST") || "127.0.0.1";
const TOKEN = env("EXECUTOR_TOKEN");
const ENV_LIVE = env("LIVE_TRADING_ENABLED").toLowerCase() === "true";
let LIVE = ENV_LIVE;
const MAX_ORDER_USD = Number(env("EXECUTOR_MAX_ORDER_USD", "LIVE_MAX_ORDER_USD") || 5);
const RPC = env("POLYGON_RPC") || "https://polygon-bor-rpc.publicnode.com";

const USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB";
const CONDITIONAL_TOKENS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045";
const ONRAMP = "0x93070a847efEf7F70739046A929D47a521F5B8ee";
const ERC20 = parseAbi(["function approve(address spender, uint256 amount) returns (bool)",
  "function balanceOf(address owner) view returns (uint256)"]);
const RAMP = parseAbi(["function wrap(address _asset, address _to, uint256 _amount)"]);
const CTF = parseAbi(["function redeemPositions(address collateralToken, bytes32 parentCollectionId, bytes32 conditionId, uint256[] indexSets)"]);

const pub = createPublicClient({ chain: polygon, transport: viemHttp(RPC) });
const startedAt = Date.now();
const wallets = new Map();   // key -> { secure, signer, ready, error, wallet, walletType, gasless, source, orders, rejects, redeemed:Set }
const log = (...a) => console.log(new Date().toISOString(), "[executor]", ...a);

function slot(key) {
  if (!wallets.has(key)) wallets.set(key, { secure: null, signer: null, ready: false, error: "no Polymarket keys yet — add them in the app",
    wallet: null, walletType: null, gasless: false, source: null, orders: 0, rejects: 0, redeemed: new Set() });
  return wallets.get(key);
}

function envCreds() {
  const pk = env("POLYMARKET_PRIVATE_KEY", "PRIVATE_KEY");
  if (!pk) return null;
  return {
    private_key: pk, wallet_address: env("POLYMARKET_WALLET_ADDRESS", "POLY_FUNDER_ADDRESS"),
    relayer_key: env("POLYMARKET_RELAYER_KEY"), relayer_address: env("POLYMARKET_RELAYER_ADDRESS"),
    builder_key: env("POLYMARKET_BUILDER_KEY", "BUILDER_KEY"), builder_secret: env("POLYMARKET_BUILDER_SECRET", "BUILDER_SECRET"),
    builder_passphrase: env("POLYMARKET_BUILDER_PASSPHRASE", "BUILDER_PASSPHRASE"),
  };
}

async function init(key, creds, source) {
  const st = slot(key);
  Object.assign(st, { secure: null, signer: null, ready: false, wallet: null, walletType: null, gasless: false, source: source || null });
  if (!creds || !creds.private_key) { st.error = "no Polymarket keys yet — add them in the app"; return st; }
  let pk = String(creds.private_key).trim();
  if (!pk.startsWith("0x")) pk = "0x" + pk;
  if (!/^0x[0-9a-fA-F]{64}$/.test(pk)) { st.error = "private key must be 64 hex characters"; return st; }
  try {
    st.signer = privateKey(pk);
    let apiKey;
    if (creds.relayer_key) {
      apiKey = relayerApiKey({ key: creds.relayer_key, address: creds.relayer_address || creds.wallet_address || (await st.signer.getAddress()) });
    } else if (creds.builder_key && creds.builder_secret && creds.builder_passphrase) {
      apiKey = builderApiKey({ key: creds.builder_key, secret: creds.builder_secret, passphrase: creds.builder_passphrase });
    }
    const opts = { signer: st.signer };
    if (apiKey) opts.apiKey = apiKey;
    if (creds.wallet_address) opts.wallet = creds.wallet_address;
    st.secure = await createSecureClient(opts);
    st.wallet = st.secure.account?.wallet ?? creds.wallet_address ?? null;
    st.walletType = st.secure.account?.walletType ?? null;
    st.gasless = !!apiKey;
    if (apiKey) { try { const h = await st.secure.setupTradingApprovals(); if (h?.wait) await h.wait(); } catch { /* already set */ } }
    st.ready = true; st.error = null;
    log(`[${key}] ready; wallet ${st.wallet} gasless ${st.gasless}`);
  } catch (e) {
    st.error = `could not connect to Polymarket with these keys: ${e?.message ?? e}`;
    log(`[${key}]`, st.error);
  }
  return st;
}

async function usdcBalance(st) {
  if (!st.wallet) return 0;
  const bal = await pub.readContract({ address: PUSD, abi: ERC20, functionName: "balanceOf", args: [st.wallet] });
  return Number(bal) / 1e6;
}

async function fetchOrder(st, orderId) {
  const o = await st.secure.fetchOrder({ orderId });
  if (!o) return null;
  return { id: o.id, status: String(o.status ?? "").toLowerCase(), price: Number(o.price ?? 0),
    size: Number(o.original_size ?? o.originalSize ?? o.size ?? 0), sizeMatched: Number(o.size_matched ?? o.sizeMatched ?? 0) };
}

async function placeLimitFak(st, { tokenId, price, size, waitMs = 2500 }) {
  if (!LIVE) return { ok: false, error: "live trading is switched off" };
  if (!st.ready) return { ok: false, error: st.error || "wallet not connected" };
  price = Number(price); size = Number(size);
  if (!tokenId || !(price > 0 && price < 1) || !(size > 0)) return { ok: false, error: "invalid order parameters" };
  if (price * size > MAX_ORDER_USD + 1e-9) return { ok: false, error: `notional $${(price * size).toFixed(2)} > cap $${MAX_ORDER_USD}` };
  st.orders++;
  let resp;
  try { resp = await st.secure.placeLimitOrder({ tokenId, price, size, side: OrderSide.BUY }); }
  catch (e) { st.rejects++; return { ok: false, error: e?.message ?? String(e) }; }
  const orderId = resp?.orderId;
  if (resp?.ok === false || !orderId) { st.rejects++; return { ok: false, error: String(resp?.error ?? resp?.errorMsg ?? "rejected") }; }
  await new Promise((r) => setTimeout(r, Math.min(10_000, Math.max(500, waitMs))));
  let o = await fetchOrder(st, orderId).catch(() => null);
  let note = null;
  if (!o || o.sizeMatched < size - 1e-6) {
    try { await st.secure.cancelOrder({ orderId }); } catch { /* already done */ }
    await new Promise((r) => setTimeout(r, 800));
    o = (await fetchOrder(st, orderId).catch(() => null)) || o;
    note = "unfilled remainder cancelled";
  }
  const matched = o?.sizeMatched ?? 0;
  log(`order ${orderId} BUY ${size}@${price} matched ${matched}`);
  return { ok: true, orderId, status: o?.status ?? resp?.status ?? "unknown", sizeMatched: matched, avgPrice: price, note };
}

async function runGasless(st, calls, metadata) {
  const wf = await prepareGaslessTransaction(st.secure, { calls, metadata });
  let step = await wf.next();
  while (!step.done) {
    const req = step.value;
    let answer;
    if (req.kind === "requestAddress") answer = await st.signer.getAddress();
    else if (req.kind === "signGaslessTypedData") answer = await st.signer.signTypedData(req.payload);
    else if (req.kind === "signGaslessMessage") answer = await st.signer.signMessage(req.payload);
    else throw new Error(`unexpected gasless step: ${req.kind}`);
    step = await wf.next(answer);
  }
  if (step.value?.wait) await step.value.wait();
}

async function redeem(st, conditionId) {
  if (!st.ready) return { ok: false, error: "wallet not connected" };
  if (!st.gasless) return { ok: false, error: "automatic redemption needs a Relayer or Builder API key; claim on polymarket.com" };
  if (!/^0x[0-9a-fA-F]{64}$/.test(conditionId || "")) return { ok: false, error: "invalid conditionId" };
  if (st.redeemed.has(conditionId)) return { ok: true, note: "already redeemed" };
  let last;
  for (let attempt = 1; attempt <= 4; attempt++) {
    try {
      const data = encodeFunctionData({ abi: CTF, functionName: "redeemPositions", args: [USDC_E, zeroHash, conditionId, [1n, 2n]] });
      await runGasless(st, [{ to: CONDITIONAL_TOKENS, data, value: 0n }], "Redeem positions");
      const amt = await pub.readContract({ address: USDC_E, abi: ERC20, functionName: "balanceOf", args: [st.wallet] });
      if (amt > 0n) {
        await runGasless(st, [
          { to: USDC_E, data: encodeFunctionData({ abi: ERC20, functionName: "approve", args: [ONRAMP, amt] }), value: 0n },
          { to: ONRAMP, data: encodeFunctionData({ abi: RAMP, functionName: "wrap", args: [USDC_E, st.wallet, amt] }), value: 0n },
        ], "Wrap USDC.e to pUSD");
      }
      st.redeemed.add(conditionId);
      return { ok: true };
    } catch (e) { last = e; await new Promise((r) => setTimeout(r, attempt * 2000)); }
  }
  return { ok: false, error: last?.message ?? String(last) };
}

// ---------------------------------------------------------------- HTTP
const send = (res, code, body) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(body)); };
const readBody = (req) => new Promise((resolve) => {
  let d = ""; req.on("data", (c) => { d += c; if (d.length > 1e5) req.destroy(); });
  req.on("end", () => { try { resolve(d ? JSON.parse(d) : {}); } catch { resolve({}); } });
});
const summary = (k, st) => ({ wallet: k, ok: st.ready, address: st.wallet, walletType: st.walletType, gasless: st.gasless,
  source: st.source, error: st.error, orders: st.orders, rejects: st.rejects });

const server = http.createServer(async (req, res) => {
  if (TOKEN && (req.headers.authorization || "") !== `Bearer ${TOKEN}`) return send(res, 401, { ok: false, error: "unauthorized" });
  const url = new URL(req.url, "http://x");
  const qkey = url.searchParams.get("wallet") || "main";
  try {
    if (req.method === "GET" && url.pathname === "/health") {
      const st = slot(qkey);
      return send(res, 200, { ok: st.ready, liveEnabled: LIVE, wallet: st.wallet, walletType: st.walletType, gasless: st.gasless,
        source: st.source, error: st.error, maxOrderUsd: MAX_ORDER_USD, uptimeS: (Date.now() - startedAt) / 1000,
        wallets: [...wallets.entries()].filter(([, s]) => s.source).map(([k]) => k),
        all: [...wallets.entries()].map(([k, s]) => summary(k, s)) });
    }
    if (req.method === "GET" && url.pathname === "/balance") {
      const st = slot(qkey);
      if (!st.ready) return send(res, 503, { ok: false, error: st.error });
      return send(res, 200, { ok: true, usdc: await usdcBalance(st), wallet: st.wallet });
    }
    if (req.method === "POST" && url.pathname === "/configure") {
      const b = await readBody(req);
      const key = b.wallet || "main";
      LIVE = ENV_LIVE || !!b.liveEnabled;
      const ec = key === "main" ? envCreds() : null;
      const st = ec ? await init(key, ec, "environment") : await init(key, b.credentials || null, b.credentials ? "app" : null);
      return send(res, 200, { ok: st.ready, liveEnabled: LIVE, ...summary(key, st) });
    }
    const b = req.method === "POST" ? await readBody(req) : {};
    const st = slot(b.wallet || qkey);
    if (req.method === "POST" && url.pathname === "/order") return send(res, 200, await placeLimitFak(st, b));
    if (req.method === "POST" && url.pathname === "/cancel") {
      if (!st.ready) return send(res, 503, { ok: false, error: st.error });
      await st.secure.cancelOrder({ orderId: b.orderId });
      return send(res, 200, { ok: true });
    }
    if (req.method === "POST" && url.pathname === "/redeem") return send(res, 200, await redeem(st, b.conditionId));
    return send(res, 404, { ok: false, error: "not found" });
  } catch (e) {
    return send(res, 500, { ok: false, error: e?.message ?? String(e) });
  }
});

server.listen(PORT, HOST, () => log(`listening on ${HOST}:${PORT}`));
const ec = envCreds();
if (ec) init("main", ec, "environment");
