import { useStore } from "../store";

export function Audit() {
  const rejections = useStore((s) => s.snapshot?.recent_rejections ?? []);
  const breaches = useStore((s) => s.snapshot?.risk_breaches_today ?? 0);
  return (
    <div className="rounded border border-slate-800 p-4 bg-slate-900">
      <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wide mb-3">Audit</h2>
      <div className="space-y-3 text-sm">
        <div>
          <div className="flex justify-between">
            <span className="text-slate-400">Risk breaches (today)</span>
            <span className={`font-mono ${breaches > 0 ? "text-rose-400" : "text-emerald-400"}`}>
              {breaches}
            </span>
          </div>
        </div>
        <div>
          <div className="text-slate-400 mb-1">Recent rejections</div>
          {rejections.length === 0 ? (
            <div className="text-xs text-slate-500">None</div>
          ) : (
            <ul className="space-y-1">
              {rejections.slice(0, 5).map((r, i) => (
                <li key={i} className="text-xs bg-slate-800/50 rounded p-2">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-rose-400">{r.gate}</span>
                    <span className="text-slate-500">{r.ts.slice(11, 19)}</span>
                  </div>
                  <div className="text-slate-300 mt-1">{r.reason}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}