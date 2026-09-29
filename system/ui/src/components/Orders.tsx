import { useStore } from "../store";

const STATUS_COLORS: Record<string, string> = {
  PROPOSED: "text-slate-400",
  VALIDATED: "text-cyan-400",
  PLACED: "text-amber-400",
  FILLED: "text-emerald-400",
  CANCELLED: "text-slate-500",
  REJECTED: "text-rose-400",
};

export function Orders() {
  const orders = useStore((s) => s.snapshot?.open_orders ?? []);
  if (orders.length === 0) {
    return (
      <div className="rounded border border-slate-800 p-4 bg-slate-900">
        <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wide mb-3">Open Orders</h2>
        <div className="text-sm text-slate-500">No open orders</div>
      </div>
    );
  }
  return (
    <div className="rounded border border-slate-800 p-4 bg-slate-900">
      <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wide mb-3">
        Open Orders ({orders.length})
      </h2>
      <table className="w-full text-sm">
        <thead className="text-slate-500 text-xs uppercase">
          <tr className="border-b border-slate-800">
            <th className="text-left py-1">Status</th>
            <th className="text-left">Symbol</th>
            <th className="text-left">Side</th>
            <th className="text-right">Qty</th>
            <th className="text-left">Tag</th>
          </tr>
        </thead>
        <tbody>
          {orders.slice(0, 20).map((o) => (
            <tr key={o.order_id} className="border-b border-slate-800/50">
              <td className={`py-1 font-mono text-xs ${STATUS_COLORS[o.status] || "text-slate-300"}`}>
                {o.status}
              </td>
              <td className="font-mono text-xs">{o.symbol}</td>
              <td className="font-mono text-xs">{o.side}</td>
              <td className="text-right font-mono">{o.qty}</td>
              <td className="font-mono text-xs text-slate-400">{o.tag}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}