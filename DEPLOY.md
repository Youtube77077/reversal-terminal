# DEPLOY — run Reversal 24/7 without your PC

The bot (data collector, paper and live trading, website) runs on a small cloud server. You use it from
your **iPhone app** or **any browser**, protected by your password.

```
iPhone app ─┐
Phone/PC browser ─┼─ HTTPS ─▶ Caddy ─▶ Reversal container (web UI · API · collector · engine · executor)
                                                     └─ Polymarket public data + (optional) live orders
```

## 1. Get a server (≈ $5–6 / month)

Pick any Ubuntu 24.04 VPS with **1 vCPU / 1–2 GB RAM / 25 GB disk**. Recommended region: **Amsterdam**,
for example a DigitalOcean "AMS3" droplet, Vultr Amsterdam, or Hetzner. Hosting in the Netherlands keeps orders
coming from your own jurisdiction: Polymarket's API is not restricted for NL, and it avoids any
VPN-style routing that their Terms of Use prohibit. Don't pick a US/UK/FR/DE region, because Polymarket
rejects API orders from those countries.

You create the account and pay the provider yourself. Add your SSH key while creating the server.

## 2. One-command install

SSH into the server, copy `deploy/setup-server.sh` over (the repo is private), and run it:

```bash
scp deploy/setup-server.sh root@SERVER_IP:~
ssh root@SERVER_IP
bash setup-server.sh
```

It installs Docker and clones your private repo, using a GitHub token you paste once; the token isn't stored. It then
asks for your app password and generates the session secret and executor token. It builds the container and gets a free HTTPS
certificate for `SERVER-IP.sslip.io`, or for your own domain if you have one.

Then open `https://<your-domain>` and log in.

## 3. Where your API keys go

**Only** in the server's `.env` file (`chmod 600`), never in Git, the website, the app or chat:

```bash
ssh root@SERVER_IP
nano ~/reversal-terminal/.env
```

```
LIVE_TRADING_ENABLED=true
POLYMARKET_PRIVATE_KEY=0x...            # wallet key that controls your Polymarket deposit wallet
POLYMARKET_BUILDER_KEY=...              # polymarket.com → Settings → Builder / API keys
POLYMARKET_BUILDER_SECRET=...
POLYMARKET_BUILDER_PASSPHRASE=...
LIVE_MAX_ORDER_USD=5
LIVE_MAX_SESSION_BUDGET_USD=100
```

Then restart: `cd ~/reversal-terminal && docker compose --env-file .compose.env up -d`.

These are the same four values Polybot used (`PRIVATE_KEY`, `BUILDER_KEY`, `BUILDER_SECRET`,
`BUILDER_PASSPHRASE`). Polybot's old `.env` keys are still on your PC; consider rotating them and use fresh
ones here.

**GitHub Secrets** (repo → Settings → Secrets and variables → Actions): not needed for running the bot. GitHub
only builds the iPhone app and the server image. Keep trading keys on the server only.

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

## 5. iPhone app

- Every push to `main` that changes `ios/` builds **Reversal.ipa** on GitHub: Actions tab, or Releases → latest.
- On your iPhone, open GitHub (signed in), download the `.ipa` from the latest release, and *Share → open in* your
  sideloading app (SideStore / AltStore / Feather / ESign / Sideloadly). It re-signs and installs.
- On first launch, enter `https://<your-domain>` and log in with your password.
- The app is a native shell around the mobile web UI. UI updates arrive automatically when the server updates,
  so you only re-sideload for native changes, such as the icon or Face ID.

## 6. Updating the server

```bash
cd ~/reversal-terminal && git pull && docker compose --env-file .compose.env up -d --build
```

Data lives in the `reversal-data` Docker volume and survives updates. Backups are written every 6 h inside
it (`/app/backend/data/backups`).

## 7. Run it on your PC instead (optional)

Put `APP_PASSWORD` in `.env`, then double-click `start.bat`. On the same Wi-Fi, the app or phone browser can use
`http://<PC-IP>:8000` (start the backend with `--host 0.0.0.0`). This only works while the PC is on.
