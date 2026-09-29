import { useStore } from "../store";

const EVENT_TYPE_COLOR: Record<string, string> = {
  "order.proposed": "text-slate-400",
  "order.validated": "text-cyan-400",
  "order.placed": "text-amber-400",
  "order.filled": "text-emerald-400",
  "order.cancelled": "text-slate-500",
  "order.rejected": "text-rose-400",
  "plan.submitted": "text-violet-400",
  "plan.completed": "text-emerald-400",
  "plan.failed": "text-rose-400",
  "market.tick": "text-slate-300",
  "risk.limit_breached": "text-rose-400",
  "risk.circuit_breaker": "text-rose-400",
};

export function EventStream() {
  const events = useStore((s) => s.events);
  return (
    <div className="rounded border border-slate-800 p-4 bg-slate-900">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wide">Event Stream</h2>
        <span className="text-xs text-slate-500">{events.length} events</span>
      </div>
      {events.length === 0 ? (
        <div className="text-sm text-slate-500">No events yet — connect to core to see live activity</div>
      ) : (
        <div className="space-y-1 max-h-96 overflow-y-auto">
          {events.slice(0, 50).map((e) => (
            <div
              key={e.id}
              className="flex items-start gap-3 text-xs bg-slate-800/30 rounded p-2 hover:bg-slate-800/50"
            >
              <span className="text-slate-500 font-mono whitespace-nowrap">
                {e.ts.slice(11, 19)}
              </span>
              <span
                className={`font-mono whitespace-nowrap ${EVENT_TYPE_COLOR[e.type] || "text-slate-300"}`}
              >
                {e.type}
              </span>
              <span className="text-slate-500 whitespace-nowrap">{e.actor}</span>
              <span className="text-slate-400 truncate flex-1">
                {JSON.stringify(e.payload).slice(0, 100)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}