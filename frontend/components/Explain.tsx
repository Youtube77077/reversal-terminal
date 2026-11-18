"use client";
import clsx from "clsx";
import { ChevronDown, HelpCircle } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

type Doc = { what: string; points: [string, string][] };

/** Shared vocabulary used on almost every page. */
const BASICS: [string, string][] = [
  ["Market", "A 5-minute bet: will the coin (BTC, ETH…) be HIGHER (UP) or LOWER (DOWN) than its start price when the 5 minutes end?"],
  ["Price / %", "A share costs between 1¢ and 99¢ and pays $1 if it wins. The price is the chance Polymarket gives it: 97¢ = 97%."],
  ["Favourite", "The side most people think will win, so it is expensive (e.g. 97¢)."],
  ["Underdog / Cheap", "The other side. Cheap (e.g. 3¢) because it rarely wins, but pays $1 if it does."],
  ["Reversal / flip", "The favourite loses and the underdog wins."],
  ["T-60", "60 seconds before the market closes. T-10 = 10 seconds left."],
  ["n", "How many past markets a number is based on. Under 30 = too few to trust."],
];

const DOCS: Record<string, Doc> = {
  "/": { what: "Your money overview. The card shows the practice money of the wallet you picked at the top (Main 1, Testing 1…).",
    points: [["Balance", "Money in this wallet right now (practice money, not real)."], ["Today", "Profit or loss the bot made today."],
      ["Balance over time", "Graph of the wallet going up or down."], ["Funds", "Add, withdraw or set practice money for the picked wallet."]] },
  "/markets": { what: "Every coin's current 5-minute market, live. Each card shows who is winning right now and how sure Polymarket is.",
    points: [["UP / DOWN %", "The chance Polymarket gives each side right now."], ["FAV / CHEAP", "FAV = favourite (expected to win), CHEAP = underdog."],
      ["Chance the underdog wins", "Polymarket says = what the price implies. Really happens = how often the underdog actually won in past markets that looked the same (same % and time left)."],
      ["b / a", "b = best price someone will BUY at, a = best price you can BUY at right now."], ["spr", "Spread: gap between b and a. Small = good."],
      ["liq", "Liquidity: dollars of shares you can buy at that price."], ["spot", "The coin's live price."],
      ["threshold (open)", "The coin's price when the 5 minutes started. Above it at the end = UP wins, below = DOWN wins."],
      ["distance", "How far the coin is from the start price right now (bp = 0.01%)."], ["est. 60s TWAP", "The winner is decided by the average price of the last 60 seconds, not the last tick. This is that average so far."],
      ["Markets list", "Every market recorded. Tap one to see its full price history."]] },
  "/bot": { what: "Start or stop the bot for the wallet you picked. Practice uses fake money, Real uses your Polymarket wallet.",
    points: [["Strategy", "The rule the bot follows to decide what to buy (explained under each choice)."], ["How much may the bot use", "The most money the bot is allowed to spend in total."],
      ["Stop loss", "Stop the bot after losing this % of the budget. 100% = keep going until the budget is $0."], ["Take profit", "Stop the bot after winning this much."],
      ["Coins", "Which coins the bot may trade."]] },
  "/activity": { what: "Everything the bot did: each buy, and whether it won or lost.", points: [["Won / Lost", "Won = the side you bought paid $1. Lost = it paid $0."], ["P&L", "Profit and loss: what you made or lost on that trade, after fees."], ["Fee", "Polymarket's fee, taken on each buy."]] },
  "/analytics": { what: "How well the bot and the market have done over time, per coin.",
    points: [["How each coin moves", "For every coin: how much it normally moves in 5 minutes, in the last 60 and 10 seconds, and how often it crosses the price to beat near the end. 'Normal' = half of all markets, 'Big' = only 1 in 10 moves more."], ["Win rate", "% of trades that won."], ["P&L", "Total profit or loss."], ["Real odds vs price", "For each coin and time left: how often the underdog really won vs what Polymarket charged. If 'really' is lower than the price, buying the underdog loses money over time — buying the favourite is better."],
      ["Edge", "Really-wins % minus price minus fee. Positive = buying the underdog there made money; negative = it lost money."], ["CI / range", "The honest range the true number is probably in. Wide range = not enough data yet."]] },
  "/wallets": { what: "Your wallets. Each has its own practice money, its own bot and can have its own Polymarket keys, so you can test different strategies side by side.",
    points: [["Main 1", "Your main wallet, with your real Polymarket keys. Can't be deleted."], ["Add / Remove", "Put practice money in or take it out."], ["Set to", "Make the practice money exactly this amount."], ["API keys", "Connect a Polymarket account to this wallet for real trading."]] },
  "/report": { what: "Everything you need to judge a bot before using real money: every finished trade, what it predicted, what price it really got, fees, worst dip, losing streaks, and the trades it chose NOT to take.",
    points: [["Calibration", "Trades grouped by the win chance the bot predicted. If it's accurate, 'actually won' is close to 'predicted'."],
      ["Drawdown", "The biggest drop from a high point in profit."], ["Slippage", "How much more it paid than the price it decided on."],
      ["Near-miss", "A market the bot looked at closely but didn't trade, and what would have happened if it had."],
      ["Final avg vs price to beat", "Our Chainlink 60-second average at the end vs at the start — this decides the winner."]] },
  "/coins": { what: "Everything the bot has learned about each of the 7 coins from every recorded market, updated every minute (live prices every second). Tap a coin card for all its details.",
    points: [["Price to beat", "The 60-second average price at the start of the market. UP wins if the 60-second average at the end is at or above it."],
      ["Normal / Big move", "Normal = half of all markets moved less than this. Big = only 1 in 10 moved more."],
      ["Swing", "Highest minus lowest price during the 5 minutes."], ["Crossed the line", "The price went from one side of the price to beat to the other — a possible flip."],
      ["Really lost vs Polymarket said", "How often the favourite actually lost vs the chance Polymarket's price gave it."],
      ["bp", "Basis point = 0.01%."], ["Streak", "Most markets in a row that ended the same way."]] },
  "/scanner": { what: "Research: how often does the favourite lose? The top table is right now; the grid is history from every market recorded.",
    points: [["Live table", "Markets right now where the underdog is 20¢ or less."], ["Polymarket says underdog wins", "The underdog's price as a chance (5¢ = 5%)."], ["Really wins (history)", "How often the underdog actually won in past markets that looked the same. Lower than the price = underdog overpriced."],
      ["Fav prob", "How sure Polymarket is that the favourite wins."], ["Ask", "Price to buy the underdog now."], ["Size @ask / Liq $", "How many shares / dollars you can buy at that price."],
      ["Dist bp", "How far the coin is from its start price (1bp = 0.01%)."], ["Momentum", "Is the coin moving toward the underdog (could flip) or away?"], ["Exec.", "✓ = enough sellers to actually buy; thin = not enough."]] },
  "/dashboard": { what: "One-screen summary of everything running: data feeds, bots, open trades and recent results." , points: [] },
  "/trading": { what: "The engine behind the bot: every account, its safety limits and its orders. You normally don't need this — the Bot tab sets it up for you.",
    points: [["Account", "A pot of money a strategy trades with (each wallet has one)."], ["Risk limits", "Safety caps: max per trade, max at once, max loss per day."], ["Equity", "Cash plus the value of open trades."], ["Reserved", "Money locked in trades that haven't finished yet."]] },
  "/transactions": { what: "A full list of every money movement: buys, payouts, fees, deposits.", points: [["Type", "fill = a buy, settle = market finished and paid out, deposit/withdraw = money you added or removed."]] },
  "/replay": { what: "Watch a past market again second by second, to see how the prices moved before it finished.", points: [] },
  "/strategy-lab": { what: "Test a strategy on past markets to see how it would have done, without risking money.",
    points: [["Backtest", "Replays history with the strategy's rules and adds up the result."], ["EV", "Expected value: average profit per trade. Positive = good."]] },
  "/experiments": { what: "Long test runs (24–48 hours) of several strategies at once, with a report at the end.", points: [] },
  "/live": { what: "Connect a Polymarket account to the wallet you picked so the bot can trade real money.",
    points: [["API key / secret / passphrase", "Your Polymarket keys — they let the bot place orders for you. Stored encrypted on your server only."], ["Polymarket wallet", "Real USDC available in that account."]] },
  "/connections": { what: "Health of the data feeds the bot uses (Polymarket prices, coin prices). Green = working.", points: [] },
  "/settings": { what: "App settings: notifications and backups.", points: [] },
};

export default function Explain() {
  const path = (usePathname() || "/").replace(/\/$/, "") || "/";
  const key = DOCS[path] ? path : "/" + path.split("/")[1];
  const doc = DOCS[key];
  const [open, setOpen] = useState(false);
  const [basics, setBasics] = useState(false);
  useEffect(() => { setOpen(false); setBasics(false); }, [key]);   // always starts closed
  if (!doc) return null;
  const toggle = () => setOpen(!open);
  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 pt-3 lg:px-8">
      <div className="panel overflow-hidden">
        <button onClick={toggle} className="flex w-full items-center gap-3 px-5 py-3.5 text-left active:opacity-70">
          <HelpCircle size={18} className="shrink-0 text-accent" />
          <span className="flex-1 text-[15px] font-semibold">What am I looking at?</span>
          <ChevronDown size={18} className={clsx("text-faint transition-transform duration-300", open && "rotate-180")} />
        </button>
        <div className={clsx("grid transition-[grid-template-rows] duration-500 ease-apple", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
          <div className="overflow-hidden">
            <div className="space-y-3 px-5 pb-5 text-[14px] leading-relaxed">
              <p className="text-ink">{doc.what}</p>
              {doc.points.length > 0 && (
                <dl className="space-y-1.5">
                  {doc.points.map(([k, v]) => <div key={k}><dt className="inline font-bold text-ink">{k}: </dt><dd className="inline text-dim">{v}</dd></div>)}
                </dl>
              )}
              <button onClick={() => setBasics(!basics)} className="text-[13px] font-semibold text-accent">{basics ? "Hide the basics" : "New to this? The basics →"}</button>
              {basics && (
                <dl className="space-y-1.5 rounded-2xl bg-panel2/60 p-4 animate-rise">
                  {BASICS.map(([k, v]) => <div key={k}><dt className="inline font-bold text-ink">{k}: </dt><dd className="inline text-dim">{v}</dd></div>)}
                </dl>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
