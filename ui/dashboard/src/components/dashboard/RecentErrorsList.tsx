import { AlertTriangle } from "lucide-react";

interface RecentErrorsListProps {
  errors: Array<{ model: string; error_count: string; timestamp: string }>;
}

export function RecentErrorsList({ errors }: RecentErrorsListProps) {
  if (errors.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-surface-400">
        No errors recorded
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {errors.map((err, i) => (
        <div
          key={`${err.model}-${i}`}
          className="flex items-center gap-3 rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 dark:border-red-900/30 dark:bg-red-900/10"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 text-red-500" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-surface-900 dark:text-surface-100">
              {err.model}
            </p>
          </div>
          <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-900/30 dark:text-red-400">
            {err.error_count} errors
          </span>
        </div>
      ))}
    </div>
  );
}
