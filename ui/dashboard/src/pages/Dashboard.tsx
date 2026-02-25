import { Activity, Brain, DollarSign, Key, TrendingUp, Zap } from "lucide-react";

import { Card } from "../components/common/Card";
import { RequestsChart } from "../components/charts/RequestsChart";
import { SpendChart } from "../components/charts/SpendChart";
import { PageContainer } from "../components/layout/PageContainer";
import { formatCompactNumber, formatCurrency, formatLatency, formatPercentage } from "../utils/formatters";

// Placeholder data — will be replaced with real API hooks
const mockMetrics = {
  total_requests_24h: 12_847,
  total_spend_24h: 48.32,
  active_keys: 23,
  active_models: 8,
  error_rate: 0.012,
  latency_p50: 340,
  latency_p95: 890,
  latency_p99: 2100,
};

const mockRequestsOverTime = Array.from({ length: 24 }, (_, i) => ({
  timestamp: new Date(Date.now() - (23 - i) * 3600_000).toISOString(),
  value: Math.floor(Math.random() * 800 + 200),
}));

const mockSpendOverTime = Array.from({ length: 24 }, (_, i) => ({
  timestamp: new Date(Date.now() - (23 - i) * 3600_000).toISOString(),
  value: +(Math.random() * 3 + 0.5).toFixed(4),
}));

const kpiCards = [
  {
    label: "Requests (24h)",
    value: formatCompactNumber(mockMetrics.total_requests_24h),
    icon: Activity,
    color: "text-primary-600",
    bgColor: "bg-primary-50 dark:bg-primary-900/20",
  },
  {
    label: "Spend (24h)",
    value: formatCurrency(mockMetrics.total_spend_24h),
    icon: DollarSign,
    color: "text-emerald-600",
    bgColor: "bg-emerald-50 dark:bg-emerald-900/20",
  },
  {
    label: "Active Keys",
    value: String(mockMetrics.active_keys),
    icon: Key,
    color: "text-amber-600",
    bgColor: "bg-amber-50 dark:bg-amber-900/20",
  },
  {
    label: "Active Models",
    value: String(mockMetrics.active_models),
    icon: Brain,
    color: "text-violet-600",
    bgColor: "bg-violet-50 dark:bg-violet-900/20",
  },
  {
    label: "Error Rate",
    value: formatPercentage(mockMetrics.error_rate),
    icon: Zap,
    color: "text-red-500",
    bgColor: "bg-red-50 dark:bg-red-900/20",
  },
  {
    label: "P95 Latency",
    value: formatLatency(mockMetrics.latency_p95),
    icon: TrendingUp,
    color: "text-sky-600",
    bgColor: "bg-sky-50 dark:bg-sky-900/20",
  },
];

export function Dashboard() {
  return (
    <PageContainer title="Dashboard" description="Overview of your RouterBot instance">
      {/* KPI Cards */}
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        {kpiCards.map((kpi) => (
          <div
            key={kpi.label}
            className="rounded-xl border border-surface-200 bg-white p-4 dark:border-surface-700 dark:bg-surface-800"
          >
            <div className="flex items-center gap-3">
              <div className={`rounded-lg p-2 ${kpi.bgColor}`}>
                <kpi.icon className={`h-5 w-5 ${kpi.color}`} />
              </div>
              <div>
                <p className="text-xs text-surface-500">{kpi.label}</p>
                <p className="text-lg font-bold text-surface-900 dark:text-surface-100">
                  {kpi.value}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Requests Over Time">
          <RequestsChart data={mockRequestsOverTime} height={280} />
        </Card>
        <Card title="Spend Over Time">
          <SpendChart data={mockSpendOverTime} height={280} />
        </Card>
      </div>
    </PageContainer>
  );
}
