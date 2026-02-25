import { useState, useCallback } from "react";
import {
  Activity,
  AlertTriangle,
  Brain,
  Clock,
  DollarSign,
  Key,
  Loader2,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";

import { Card } from "../components/common/Card";
import { RequestsChart } from "../components/charts/RequestsChart";
import { SpendChart } from "../components/charts/SpendChart";
import { SpendByModelChart } from "../components/charts/SpendByModelChart";
import { TopModelsTable } from "../components/dashboard/TopModelsTable";
import { ProviderHealth } from "../components/dashboard/ProviderHealth";
import { RecentErrorsList } from "../components/dashboard/RecentErrorsList";
import { PeriodSelector } from "../components/dashboard/PeriodSelector";
import { RefreshControl } from "../components/dashboard/RefreshControl";
import { PageContainer } from "../components/layout/PageContainer";
import {
  formatCompactNumber,
  formatCurrency,
  formatLatency,
  formatPercentage,
} from "../utils/formatters";
import { useDashboardStats } from "../api/hooks/useDashboard";
import type { DashboardPeriod } from "../api/hooks/useDashboard";

const DEFAULT_REFRESH_MS = 30000;

export function Dashboard() {
  const [period, setPeriod] = useState<DashboardPeriod>("24h");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const refreshInterval = autoRefresh ? DEFAULT_REFRESH_MS : false;

  const {
    data: metrics,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useDashboardStats(period, refreshInterval);

  const handleManualRefresh = useCallback(() => {
    void refetch();
  }, [refetch]);

  if (isLoading) {
    return (
      <PageContainer title="Dashboard" description="Overview of your RouterBot instance">
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-8 w-8 animate-spin text-primary-500" />
          <span className="ml-3 text-surface-500">Loading dashboard…</span>
        </div>
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer title="Dashboard" description="Overview of your RouterBot instance">
        <div className="flex flex-col items-center justify-center py-24">
          <AlertTriangle className="h-10 w-10 text-red-400" />
          <p className="mt-3 text-surface-600 dark:text-surface-400">
            Failed to load dashboard metrics
          </p>
          <p className="mt-1 text-sm text-surface-400">
            {error instanceof Error ? error.message : "Unknown error"}
          </p>
          <button
            type="button"
            onClick={handleManualRefresh}
            className="mt-4 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          >
            Retry
          </button>
        </div>
      </PageContainer>
    );
  }

  const m = metrics;

  const kpiCards = [
    {
      label: `Requests (${period})`,
      value: m ? formatCompactNumber(m.total_requests) : "—",
      icon: Activity,
      color: "text-primary-600",
      bgColor: "bg-primary-50 dark:bg-primary-900/20",
    },
    {
      label: `Spend (${period})`,
      value: m ? formatCurrency(m.total_spend) : "—",
      icon: DollarSign,
      color: "text-emerald-600",
      bgColor: "bg-emerald-50 dark:bg-emerald-900/20",
    },
    {
      label: "Active Keys",
      value: m ? String(m.active_keys) : "—",
      icon: Key,
      color: "text-amber-600",
      bgColor: "bg-amber-50 dark:bg-amber-900/20",
    },
    {
      label: "Active Models",
      value: m ? String(m.active_models) : "—",
      icon: Brain,
      color: "text-violet-600",
      bgColor: "bg-violet-50 dark:bg-violet-900/20",
    },
    {
      label: "Error Rate",
      value: m ? formatPercentage(m.error_rate) : "—",
      icon: Zap,
      color: m && m.error_rate > 0.05 ? "text-red-500" : "text-emerald-500",
      bgColor: m && m.error_rate > 0.05
        ? "bg-red-50 dark:bg-red-900/20"
        : "bg-emerald-50 dark:bg-emerald-900/20",
    },
    {
      label: "P95 Latency",
      value: m ? formatLatency(m.latency_p95) : "—",
      icon: TrendingUp,
      color: "text-sky-600",
      bgColor: "bg-sky-50 dark:bg-sky-900/20",
    },
    {
      label: "Teams",
      value: m ? String(m.active_teams) : "—",
      icon: Users,
      color: "text-indigo-600",
      bgColor: "bg-indigo-50 dark:bg-indigo-900/20",
    },
    {
      label: "Uptime",
      value: m ? formatUptime(m.uptime_seconds) : "—",
      icon: Clock,
      color: "text-teal-600",
      bgColor: "bg-teal-50 dark:bg-teal-900/20",
    },
  ];

  // Prepare time series for charts
  const requestsTimeSeries = m?.time_series.map((p) => ({
    timestamp: p.timestamp,
    value: p.requests,
  })) ?? [];

  const spendTimeSeries = m?.time_series.map((p) => ({
    timestamp: p.timestamp,
    value: p.spend,
  })) ?? [];

  return (
    <PageContainer
      title="Dashboard"
      description="Overview of your RouterBot instance"
      actions={
        <div className="flex items-center gap-3">
          <PeriodSelector value={period} onChange={setPeriod} />
          <RefreshControl
            isRefreshing={isFetching}
            autoRefresh={autoRefresh}
            onToggleAutoRefresh={() => setAutoRefresh((v) => !v)}
            onManualRefresh={handleManualRefresh}
            intervalMs={DEFAULT_REFRESH_MS}
          />
        </div>
      }
    >
      {/* KPI Cards */}
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-8">
        {kpiCards.map((kpi) => (
          <div
            key={kpi.label}
            className="rounded-xl border border-surface-200 bg-white p-4 dark:border-surface-700 dark:bg-surface-800"
          >
            <div className="flex items-center gap-3">
              <div className={`rounded-lg p-2 ${kpi.bgColor}`}>
                <kpi.icon className={`h-5 w-5 ${kpi.color}`} />
              </div>
              <div className="min-w-0">
                <p className="truncate text-xs text-surface-500">{kpi.label}</p>
                <p className="text-lg font-bold text-surface-900 dark:text-surface-100">
                  {kpi.value}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Row 1: Requests + Spend time series */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card title="Requests Over Time">
          <RequestsChart data={requestsTimeSeries} height={280} />
        </Card>
        <Card title="Spend Over Time">
          <SpendChart data={spendTimeSeries} height={280} />
        </Card>
      </div>

      {/* Row 2: Spend by Model + Latency */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card title="Spend by Model">
          <SpendByModelChart data={m?.spend_by_model ?? {}} height={280} />
        </Card>
        <Card title="Latency Distribution">
          <LatencyBars p50={m?.latency_p50 ?? 0} p95={m?.latency_p95 ?? 0} p99={m?.latency_p99 ?? 0} />
        </Card>
      </div>

      {/* Row 3: Top Models + Provider Health + Recent Errors */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Top Models">
          <TopModelsTable models={m?.top_models ?? []} />
        </Card>
        <Card title="Provider Health">
          <ProviderHealth health={m?.provider_health ?? {}} />
        </Card>
        <Card title="Recent Errors">
          <RecentErrorsList errors={m?.recent_errors ?? []} />
        </Card>
      </div>
    </PageContainer>
  );
}

// ---------------------------------------------------------------------------
// Inline latency bars (simple, no heavy chart dep)
// ---------------------------------------------------------------------------

function LatencyBars({
  p50,
  p95,
  p99,
}: {
  p50: number;
  p95: number;
  p99: number;
}) {
  const max = Math.max(p50, p95, p99, 1);
  const bars = [
    { label: "P50", value: p50, color: "bg-emerald-500" },
    { label: "P95", value: p95, color: "bg-amber-500" },
    { label: "P99", value: p99, color: "bg-red-500" },
  ];

  if (max === 1 && p50 === 0 && p95 === 0 && p99 === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-surface-400">
        No latency data yet
      </div>
    );
  }

  return (
    <div className="space-y-4 py-4">
      {bars.map((bar) => (
        <div key={bar.label} className="space-y-1">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-surface-700 dark:text-surface-300">
              {bar.label}
            </span>
            <span className="tabular-nums text-surface-500">{formatLatency(bar.value)}</span>
          </div>
          <div className="h-3 w-full overflow-hidden rounded-full bg-surface-100 dark:bg-surface-700">
            <div
              className={`h-full rounded-full transition-all ${bar.color}`}
              style={{ width: `${Math.max((bar.value / max) * 100, 2)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return `${days}d ${hours}h`;
}

