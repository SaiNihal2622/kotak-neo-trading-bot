import { useStore } from "../store";

export function Positions() {
  const positions = useStore((s) => s.snapshot?.positions ?? {});
  const entries = Object.entries(positions);
  return (
    <div className="rounded border border-slate-800 p-4 bg-slate-900">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wide">Positions</h2>
        <span className="text-xs text-slate-500">{entries.length} open</span>
      </div>
      {entries.length === 0 ? (
        <div className="text-sm text-slate-500">No open positions</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-slate-500 text-xs uppercase">
            <tr className="border-b border-slate-800">
              <th className="text-left py-1">Symbol</th>
              <th className="text-right">Qty</th>
              <th className="text-right">Avg</th>
              <th className="text-right">LTP</th>
              <th className="text-right">P&L</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([sym, p]) => {
              const pnlColor = p.pnl >= 0 ? "text-emerald-400" : "text-rose-400";
              return (
                <tr key={sym} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="py-2 font-mono text-xs">{sym}</td>
                  <td className="text-right font-mono">{p.qty}</td>
                  <td className="text-right font-mono">{p.avg_price.toFixed(2)}</td>
                  <td className="text-right font-mono">{p.ltp.toFixed(2)}</td>
                  <td className={`text-right font-mono ${pnlColor}`}>
                    {p.pnl >= 0 ? "+" : ""}
                    {p.pnl.toFixed(0)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}