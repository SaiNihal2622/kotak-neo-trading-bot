interface Props {
  connected: boolean;
}

export function ConnectionStatus({ connected }: Props) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <div
        className={`w-2 h-2 rounded-full ${
          connected ? "bg-emerald-400 animate-pulse" : "bg-rose-400"
        }`}
      />
      <span className={connected ? "text-emerald-400" : "text-rose-400"}>
        {connected ? "Connected" : "Disconnected"}
      </span>
    </div>
  );
}