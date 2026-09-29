/**
 * Real-time web UI for the Kotak trading core.
 *
 * Connects to:
 *   - GET  /api/state       for current snapshot
 *   - WS   /ws              for live event stream
 *
 * Renders:
 *   - Account summary (cash, P&L, pause state)
 *   - Open positions table (qty, avg, LTP, P&L)
 *   - Recent orders
 *   - Risk audit (rejections, breaches)
 *   - Plan activity (open plans)
 *
 * The UI is intentionally minimal — read-only by default. Trade actions
 * are still routed through the brain / API (the UI is observation, not
 * control).
 */
import { useEffect, useState } from "react";
import { useStore } from "./store";
import { Positions } from "./components/Positions";
import { Account } from "./components/Account";
import { Orders } from "./components/Orders";
import { Audit } from "./components/Audit";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { EventStream } from "./components/EventStream";

const CORE_API = import.meta.env.VITE_CORE_API ?? "http://127.0.0.1:8510";

export function App() {
  const [connected, setConnected] = useState(false);
  const setSnapshot = useStore((s) => s.setSnapshot);
  const setEvents = useStore((s) => s.appendEvents);

  useEffect(() => {
    // Initial snapshot via REST
    fetch(`${CORE_API}/api/state`)
      .then((r) => r.json())
      .then(setSnapshot)
      .catch((e) => console.error("snapshot fetch failed", e));

    // Live updates via WebSocket
    const ws = new WebSocket(`${CORE_API.replace(/^http/, "ws")}/ws`);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "snapshot") {
          setSnapshot(msg.data);
        } else if (msg.type === "events") {
          setEvents(msg.data);
        }
      } catch (e) {
        console.error("ws parse failed", e);
      }
    };
    const heartbeat = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 30000);
    return () => {
      clearInterval(heartbeat);
      ws.close();
    };
  }, [setSnapshot, setEvents]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Kotak Trading Core</h1>
        <ConnectionStatus connected={connected} />
      </header>
      <main className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <Account />
          <Audit />
        </div>
        <div className="lg:col-span-2 space-y-6">
          <Positions />
          <Orders />
          <EventStream />
        </div>
      </main>
    </div>
  );
}