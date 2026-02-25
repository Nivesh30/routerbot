import { Pause, Play, RefreshCw } from "lucide-react";

interface RefreshControlProps {
  isRefreshing: boolean;
  autoRefresh: boolean;
  onToggleAutoRefresh: () => void;
  onManualRefresh: () => void;
  intervalMs: number;
}

export function RefreshControl({
  isRefreshing,
  autoRefresh,
  onToggleAutoRefresh,
  onManualRefresh,
  intervalMs,
}: RefreshControlProps) {
  const intervalLabel = intervalMs >= 60000
    ? `${Math.round(intervalMs / 60000)}m`
    : `${Math.round(intervalMs / 1000)}s`;

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={onManualRefresh}
        disabled={isRefreshing}
        className="inline-flex items-center gap-1.5 rounded-lg border border-surface-200 px-2.5 py-1.5 text-xs font-medium text-surface-600 transition-colors hover:bg-surface-50 disabled:opacity-50 dark:border-surface-700 dark:text-surface-400 dark:hover:bg-surface-800"
        title="Refresh now"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
        Refresh
      </button>
      <button
        type="button"
        onClick={onToggleAutoRefresh}
        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
          autoRefresh
            ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-400"
            : "border-surface-200 text-surface-500 hover:bg-surface-50 dark:border-surface-700 dark:text-surface-400 dark:hover:bg-surface-800"
        }`}
        title={autoRefresh ? "Disable auto-refresh" : "Enable auto-refresh"}
      >
        {autoRefresh ? (
          <Pause className="h-3.5 w-3.5" />
        ) : (
          <Play className="h-3.5 w-3.5" />
        )}
        Auto ({intervalLabel})
      </button>
    </div>
  );
}
