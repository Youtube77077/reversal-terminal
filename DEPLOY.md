# DEPLOY — run Reversal 24/7 without your PC

The bot (data collector, paper and live trading, website) runs on a small cloud server. You use it from
your **iPhone app** or **any browser**, protected by your password.

```
iPhone app ─┐
Phone/PC browser ─┼─ HTTPS ─▶ Caddy ─▶ Reversal container (web UI · API · collector · engine · executor)
                                                     └─ Polymarket public data + (optional) live orders
```

## 1. Get a server — free option first

### Free: Oracle Cloud "Always Free" (recommended, €0/month)
1. Sign up at **cloud.oracle.com/free**. A card is needed only for identity verification, and Always Free resources aren't charged.
   Choose **Home Region: Netherlands Northwest (Amsterdam)**. You can't change this later, and it keeps orders
   coming from NL, where Polymarket's API isn't restricted.
2. **Create a VM instance**: Image *Ubuntu 24.04*, Shape *Ampere A1 Flex* (ARM). Up to 4 OCPU / 24 GB is
   free; 1 OCPU / 6 GB is plenty. Add your SSH key and create it.
3. **Networking → Virtual Cloud Network → Security List → Add Ingress Rules**: TCP **80** and **443**, source `0.0.0.0/0`.
4. Note the public IP and continue with step 2 below (user `ubuntu`).

### Why not Cloudflare / Vercel / Render free?
Cloudflare Workers/Pages and Vercel only run short request handlers, but this bot must run nonstop: live
websockets, a 1-second collector and a database. Render's free tier sleeps after 15 minutes, which would stop the collector.
Cloudflare **Tunnel** (free) *can* give the server a secure link without opening ports. Run
`cloudflared tunnel --url http://localhost:8000` on the server for an instant `https://….trycloudflare.com` address.

### Paid alternative (≈ $5–6 / month)
Any Ubuntu 24.04 VPS with 1 vCPU / 1–2 GB RAM in **Amsterdam** works, for example DigitalOcean AMS3, Vultr Amsterdam or Hetzner. Don't
pick US/UK/FR/DE regions, because Polymarket rejects API orders from those countries.

## 2. One-command install

SSH into the server, copy `deploy/setup-server.sh` over (the repo is private), and run it:

```bash
scp deploy/setup-server.sh ubuntu@SERVER_IP:~     # Oracle user is "ubuntu"; other VPS often "root"
ssh ubuntu@SERVER_IP
bash setup-server.sh
```

It installs Docker and clones your private repo, using a GitHub token you paste once; the token isn't stored. It then
asks for your app password and generates the session secret and executor token. It builds the container and gets a free HTTPS
certificate for `SERVER-IP.sslip.io`, or for your own domain if you have one.

Then open `https://<your-domain>` and log in.

## 3. Where your API keys go

**Easiest: in the app.** Website or iPhone app → **More → Live trading → API keys**. The page explains where to
find each value. Keys are encrypted on the server (AES-256), never shown again, and never stored in Git.

What Polymarket needs (from their docs):
| Value | Required? | Where to find it |
|---|---|---|
| Private key | **yes** | Email/Google account: reveal.magic.link/polymarket → *Export Private Key*. Wallet account: your wallet app → *Show private key* |
| Wallet address | recommended | polymarket.com → profile picture → the `0x…` address |
| Relayer API key + address | optional | polymarket.com → Settings → API Keys → Relayer API Keys (enables auto-approvals & auto-redeem) |
| *or* Builder key/secret/passphrase | optional | polymarket.com/settings?tab=builder (what Polybot used) |
| Funds | yes | Deposit on polymarket.com; trades use pUSD, at least $1 per order, $10+ recommended |

The trading API credentials themselves are generated automatically from your private key.

**Alternative: server env** (`nano ~/reversal-terminal/.env`), with `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_WALLET_ADDRESS`,
`POLYMARKET_RELAYER_KEY`, `POLYMARKET_RELAYER_ADDRESS` (or the `POLYMARKET_BUILDER_*` trio) and `LIVE_TRADING_ENABLED=true`.
Server env values take precedence over keys entered in the app.

## 4. Going live (real money)

1. Website → **More → Live trading**: the checklist must be all green (switch on, executor connected, server location accepted).
2. **Create live account**, choose a strategy.
3. **Arm live trading** with your password, after acknowledging the risk and the ToS conflict.
4. **$ tab** → pick the live account → set the risk (% or $), stop loss and take profit → **Start bot · REAL MONEY**.

Safety layers on every order:
- The executor refuses orders unless `LIVE_TRADING_ENABLED=true`.
- Caps apply per order and per session.
- Orders are price-capped limit buys, and any unfilled remainder is cancelled.
- Live accounts can't trade without a session.
- The stop loss counts open positions as fully at risk.
- Disarming or **PAUSE ALL** stops new orders immediately.

## 5. iPhone app (.ipa)

iPhone apps can only be compiled with **Xcode on a Mac**. Your PC is Windows, so the build runs on a cloud Mac:

- **GitHub Actions** (`.github/workflows/ios.yml`): runs automatically on every push that changes `ios/`. Private repos
  need working GitHub billing (Settings → Billing & plans). The `.ipa` then appears under **Releases**.
- **Codemagic, free** (`codemagic.yaml`): sign in at codemagic.io with GitHub, add the repo, run the
  **ios-unsigned** workflow, and download `Reversal.ipa` from Artifacts. The free tier includes 500 Mac minutes/month, about 3 min per build.

Install: on your iPhone, open the `.ipa` with your sideloading app (SideStore, AltStore, Feather, ESign or Sideloadly), which re-signs it.
First launch: enter `https://<your-domain>` and log in. UI updates come from the server automatically.

## 6. Updating the server

```bash
cd ~/reversal-terminal && git pull && docker compose --env-file .compose.env up -d --build
```

Data lives in the `reversal-data` Docker volume and survives updates. Backups are written every 6 h inside
it (`/app/backend/data/backups`).

## 7. Run it on your PC instead (optional)

Put `APP_PASSWORD` in `.env`, then double-click `start.bat`. On the same Wi-Fi, the app or phone browser can use
`http://<PC-IP>:8000` (start the backend with `--host 0.0.0.0`). This only works while the PC is on.
