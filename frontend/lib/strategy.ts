/** Plain-English one-liner for a Strategy Builder strategy's settings. */
export function strategySummary(p: Record<string, any>) {
  if (!p) return "";
  const side = ({ favourite: "favourite", underdog: "underdog", up: "UP", down: "DOWN" } as Record<string, string>)[p.side] || p.side;
  return `Buys the ${side} at ${Math.round((p.min_price ?? 0) * 100)}–${Math.round((p.max_price ?? 0) * 100)}¢ with ${p.entry_min_secs}–${p.entry_max_secs}s left` +
    `${p.z_min ? `, safety margin z ≥ ${p.z_min}` : ""}. Stake ${p.stake_mode === "fixed" ? `$${p.stake_value}` : `${p.stake_value}% of balance`}, ` +
    `max loss ${p.max_loss_pct}% per trade. ${p.take_profit_price ? `Sells at ${Math.round(p.take_profit_price * 100)}¢.` : "Holds to the end."}`;
}

/** Human labels for every setting a running bot can have (built-in strategies + custom). */
export const PARAM_LABELS: Record<string, string> = {
  side: "Side", min_price: "Lowest price", max_price: "Highest price", entry_min_secs: "Stop buying with … s left",
  entry_max_secs: "Start buying with … s left", z_min: "Min safety margin (z)", z_max: "Max safety margin (z)",
  min_model_edge: "Min model edge", min_edge: "Min edge", model_max: "Skip if model chance above", momentum_filter: "Skip fast moves against us",
  blackout: "News blackout 14:25–14:45", use_fast: "Fast exchange prices", stake_mode: "Stake type", stake_value: "Stake",
  stake_usd: "$ per trade", max_loss_pct: "Max loss per trade (% balance)", take_profit_price: "Sell early at (0 = hold)",
  stop_price: "Stop-loss price", z_stop: "…only if z below", max_open_positions: "Max open trades", max_trades_per_day: "Max trades/day",
  max_losses_per_day: "Stop after … losses/day", daily_loss_limit_pct: "Daily loss limit %", daily_profit_cap_pct: "Daily profit cap %",
  windows: "Markets", assets: "Coins", require_cross: "Only after crossing the line", limit_offset_ticks: "May pay … ticks more",
  custom_name: "Strategy", custom_id: "Strategy Builder id",
};
