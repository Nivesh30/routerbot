import { RefreshCw, Info, Key } from "lucide-react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { Card } from "../components/common/Card";
import { EmptyState } from "../components/common/EmptyState";
import { LoadingSpinner } from "../components/common/LoadingSpinner";
import { PageContainer } from "../components/layout/PageContainer";
import { useConfig, useReloadConfig, useSSOProviders, useAuditLogs } from "../api/hooks/useSettings";
import { formatDateTime } from "../utils/formatters";

// ─── Audit Logs Section ───────────────────────────────────────────────────────

function AuditLogsSection() {
  const { data, isLoading } = useAuditLogs({ per_page: 50 });
  const items = data?.items ?? [];

  if (isLoading) return <LoadingSpinner />;
  if (items.length === 0)
    return <EmptyState title="No audit logs" description="Admin actions will appear here." />;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 dark:border-gray-700">
            {["Time", "Actor", "Action", "Target"].map((h) => (
              <th key={h} className="text-left py-2 px-3 text-gray-500 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((entry) => (
            <tr key={entry.id} className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50">
              <td className="py-2 px-3 text-gray-500 whitespace-nowrap">{formatDateTime(entry.timestamp)}</td>
              <td className="py-2 px-3 font-mono text-xs">{entry.actor}</td>
              <td className="py-2 px-3"><Badge variant="info">{entry.action}</Badge></td>
              <td className="py-2 px-3 font-mono text-xs text-gray-500">{entry.target}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Config display ───────────────────────────────────────────────────────────

function ConfigSection() {
  const { data, isLoading, error } = useConfig();
  const reload = useReloadConfig();

  if (isLoading) return <LoadingSpinner />;
  if (error) return <p className="text-red-500 text-sm">Failed to load configuration.</p>;
  if (!data) return null;

  const entries = Object.entries(data).filter(
    ([k]) => !k.toLowerCase().includes("key") && !k.toLowerCase().includes("secret") && !k.toLowerCase().includes("password"),
  );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {entries.slice(0, 12).map(([k, v]) => (
          <div key={k} className="flex items-start gap-2 bg-gray-50 dark:bg-gray-800 rounded-md p-2">
            <span className="text-xs font-mono text-gray-500 min-w-[140px] flex-shrink-0">{k}</span>
            <span className="text-xs font-mono text-gray-800 dark:text-gray-200 truncate">
              {typeof v === "object" ? JSON.stringify(v) : String(v ?? "—")}
            </span>
          </div>
        ))}
      </div>
      <Button variant="secondary" size="sm" onClick={() => reload.mutate()} loading={reload.isPending}>
        <RefreshCw className="h-3 w-3 mr-1" />Reload config
      </Button>
    </div>
  );
}

// ─── SSO Providers Section ────────────────────────────────────────────────────

function SSOSection() {
  const { data, isLoading } = useSSOProviders();
  const providers = data ?? [];

  if (isLoading) return <LoadingSpinner />;

  return (
    <div>
      {providers.length === 0 ? (
        <EmptyState title="No SSO providers" description="SSO providers configured in routerbot_config.yaml will appear here." />
      ) : (
        <div className="space-y-2">
          {providers.map((p) => (
            <div key={p.id} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
              <div className="flex items-center gap-2">
                <Key className="h-4 w-4 text-gray-400" />
                <span className="font-medium text-sm">{p.name}</span>
                <Badge variant="neutral">{p.type}</Badge>
              </div>
              <Badge variant={p.enabled ? "success" : "neutral"}>
                {p.enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function Settings() {
  return (
    <PageContainer title="Settings" description="System configuration and administration">
      <div className="space-y-6">
        <div className="flex items-center gap-2 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
          <Info className="h-5 w-5 text-amber-500 flex-shrink-0" />
          <p className="text-sm text-amber-700 dark:text-amber-300">
            Server configuration is managed via <code className="bg-amber-100 dark:bg-amber-800 px-1 rounded">routerbot_config.yaml</code>.
            This page shows the current running configuration (read-only).
          </p>
        </div>

        <Card title="Running Configuration">
          <ConfigSection />
        </Card>

        <Card title="SSO Providers">
          <SSOSection />
        </Card>

        <Card title="Audit Log">
          <AuditLogsSection />
        </Card>
      </div>
    </PageContainer>
  );
}
