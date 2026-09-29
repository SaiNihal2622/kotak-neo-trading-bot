/**
 * Zustand store for the trading UI.
 *
 * Holds:
 *   - snapshot: last known state from /api/state
 *   - events: rolling buffer of recent events from WS
 *
 * The UI subscribes to the snapshot for header/positions, and to events
 * for the live activity feed.
 */
import { create } from "zustand/vanilla";
import { useStore as useVanillaStore } from "zustand";

type Account = {
  cash: number;
  starting_capital: number;
  realized_pnl: number;
  is_paused: boolean;
  pause_reason: string;
};

type Position = {
  symbol: string;
  underlying: string;
  qty: number;
  avg_price: number;
  ltp: number;
  strike: number;
  option_type: string;
  expiry: string;
  exchange: string;
  pnl: number;
};

type Order = {
  order_id: string;
  client_order_id: string;
  broker_order_id: string;
  symbol: string;
  side: string;
  qty: number;
  filled_qty: number;
  order_type: string;
  avg_fill_price: number;
  status: string;
  tag: string;
  placed_at: string;
  filled_at: string;
  rejection_reason: string;
  plan_id: string;
};

type Rejection = {
  ts: string;
  order: Record<string, unknown>;
  reason: string;
  gate: string;
  actor: string;
};

type Event = {
  id: string;
  ts: string;
  type: string;
  actor: string;
  correlation_id: string;
  payload: Record<string, unknown>;
};

type Snapshot = {
  ts: string;
  account: Account;
  positions: Record<string, Position>;
  open_orders: Order[];
  open_plans: Array<Record<string, unknown>>;
  recent_rejections: Rejection[];
  risk_breaches_today: number;
  ticks_known: number;
};

type State = {
  snapshot: Snapshot | null;
  events: Event[];
  setSnapshot: (s: Snapshot) => void;
  appendEvents: (events: Event[]) => void;
  clear: () => void;
};

export const store = create<State>((set) => ({
  snapshot: null,
  events: [],
  setSnapshot: (s) => set({ snapshot: s }),
  appendEvents: (events) =>
    set((state) => ({
      events: [...events, ...state.events].slice(0, 200), // keep last 200
    })),
  clear: () => set({ snapshot: null, events: [] }),
}));

export function useStore<T>(selector: (state: State) => T): T {
  return useVanillaStore(store, selector);
}