import { CheckCircle, XCircle } from "lucide-react";

interface ProviderHealthProps {
  health: Record<string, { status: string; value: number }>;
}

export function ProviderHealth({ health }: ProviderHealthProps) {
  const entries = Object.entries(health);

  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-surface-400">
        No provider data available
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map(([provider, info]) => (
        <div
          key={provider}
          className="flex items-center justify-between rounded-lg border border-surface-200 px-3 py-2 dark:border-surface-700"
        >
          <span className="font-medium text-surface-900 dark:text-surface-100">
            {provider}
          </span>
          <span className="flex items-center gap-1.5">
            {info.status === "healthy" ? (
              <>
                <CheckCircle className="h-4 w-4 text-emerald-500" />
                <span className="text-sm text-emerald-600 dark:text-emerald-400">
                  Healthy
                </span>
              </>
            ) : (
              <>
                <XCircle className="h-4 w-4 text-red-500" />
                <span className="text-sm text-red-600 dark:text-red-400">
                  Unhealthy
                </span>
              </>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}
