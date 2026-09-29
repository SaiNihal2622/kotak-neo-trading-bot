import { useStore } from "../store";

export function Account() {
  const account = useStore((s) => s.snapshot?.account);
  if (!account) {
    return (
      <div className="rounded border border-slate-800 p-4 bg-slate-900">
        <div className="text-sm text-slate-400">Account — loading...</div>
      </div>
    );
  }
  const pnlPct = (account.realized_pnl / account.starting_capital) * 100;
  const pnlColor = account.realized_pnl >= 0 ? "text-emerald-400" : "text-rose-400";
  return (
    <div className="rounded border border-slate-800 p-4 bg-slate-900">
      <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wide mb-3">Account</h2>
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-slate-400">Cash</span>
          <span className="font-mono">Rs.{account.cash.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Starting</span>
          <span className="font-mono">Rs.{account.starting_capital.toFixed(2)}</span>
        </div>
        <div className="flex justify-between border-t border-slate-800 pt-2 mt-2">
          <span className="text-slate-400">Realized P&L</span>
          <span className={`font-mono ${pnlColor}`}>
            Rs.{account.realized_pnl.toFixed(2)} ({pnlPct.toFixed(2)}%)
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Status</span>
          <span className={account.is_paused ? "text-rose-400" : "text-emerald-400"}>
            {account.is_paused ? `PAUSED: ${account.pause_reason || "manual"}` : "Running"}
          </span>
        </div>
      </div>
    </div>
  );
}