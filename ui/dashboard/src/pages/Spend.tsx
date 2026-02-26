import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { Download, TrendingUp, DollarSign, Zap } from "lucide-react";
import { useState } from "react";

import { Card } from "../components/common/Card";
import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";
import { LoadingSpinner } from "../components/common/LoadingSpinner";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import { useSpendReport, useSpendLogs } from "../api/hooks/useSpend";
import {
  formatCurrency,
  formatNumber,
  formatCompactNumber,
  formatTokens,
  formatDateTime,
} from "../utils/formatters";
import { PERIOD_OPTIONS } from "../utils/constants";

import type { Column } from "../components/common/Table";
import type { SpendRecord } from "../api/types";

// ─── helpers ──────────────────────────────────────────────────────────────────

const CHART_COLORS = [
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#ec4899",
  "#14b8a6",
];

function KpiCard({
  title,
  value,
  icon: Icon,
}: {
  title: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card>
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-full bg-blue-50 dark:bg-blue-900/30 flex items-center justify-center">
          <Icon className="h-5 w-5 text-blue-600 dark:text-blue-400" />
        </div>
        <div>
          <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">{title}</p>
          <p className="text-xl font-bold text-gray-900 dark:text-white">{value}</p>
        </div>
      </div>
    </Card>
  );
}

// ─── Export helper ────────────────────────────────────────────────────────────

function exportCsv(rows: SpendRecord[], filename: string) {
  const headers = ["timestamp", "model", "provider", "tokens_used", "cost", "user_id", "team_id", "request_id"];
  const lines = [
    headers.join(","),
    ...rows.map((r) =>
      [
        r.timestamp,
        r.model,
        r.provider,
        r.tokens_used,
        r.cost,
        r.user_id ?? "",
        r.team_id ?? "",
        r.request_id,
      ].join(","),
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Spend logs table ─────────────────────────────────────────────────────────

function SpendLogsTable({
  period,
  modelFilter,
}: {
  period: { start_date?: string; end_date?: string };
  modelFilter: string;
}) {
  const [page, setPage] = useState(1);
  const PER_PAGE = 20;

  const { data, isLoading } = useSpendLogs({
    page,
    per_page: PER_PAGE,
    start_date: period.start_date,
    end_date: period.end_date,
    ...(modelFilter ? { model: modelFilter } : {}),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.ceil(total / PER_PAGE);

  const columns: Column<SpendRecord>[] = [
    { key: "timestamp", header: "Time", sortable: true, render: (r: SpendRecord) => formatDateTime(r.timestamp) },
    { key: "model", header: "Model", sortable: true, render: (r: SpendRecord) => <span className="font-mono text-xs">{r.model}</span> },
    { key: "provider", header: "Provider", sortable: true, render: (r: SpendRecord) => r.provider },
    {
      key: "tokens_used",
      header: "Tokens",
      sortable: true,
      render: (r: SpendRecord) => formatTokens(r.tokens_used),
    },
    { key: "cost", header: "Cost", sortable: true, render: (r: SpendRecord) => formatCurrency(r.cost) },
    { key: "user_id", header: "User", render: (r: SpendRecord) => r.user_id ? <span className="font-mono text-xs">{r.user_id.slice(0, 8)}…</span> : "—" },
    { key: "team_id", header: "Team", render: (r: SpendRecord) => r.team_id ? <span className="font-mono text-xs">{r.team_id.slice(0, 8)}…</span> : "—" },
    {
      key: "tags",
      header: "Tags",
      render: (r: SpendRecord) =>
        r.tags.length ? (
          <div className="flex gap-1">
            {r.tags.slice(0, 2).map((t) => <Badge key={t} variant="neutral">{t}</Badge>)}
          </div>
        ) : null,
    },
  ];

  if (isLoading) return <LoadingSpinner />;

  return (
    <div>
      {items.length === 0 ? (
        <EmptyState title="No spend records" description="No spend data found for the selected period." />
      ) : (
        <>
          <Table data={items} columns={columns} keyFn={(r) => r.id} />
          {pages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * PER_PAGE + 1}–{Math.min(page * PER_PAGE, total)} of {formatNumber(total)}
              </p>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
                <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function Spend() {
  const [period, setPeriod] = useState("24h");
  const [modelFilter, setModelFilter] = useState("");
  const [groupBy, setGroupBy] = useState<"model" | "provider" | "team" | "user">("model");
  const [activeTab, setActiveTab] = useState<"overview" | "logs">("overview");

  const { data: report, isLoading: reportLoading } = useSpendReport({
    group_by: groupBy,
  });

  const { data: logsData } = useSpendLogs({ per_page: 200 });

  function handleExport() {
    const rows = logsData?.items ?? [];
    exportCsv(rows, `spend-${period}-${new Date().toISOString().slice(0, 10)}.csv`);
  }

  // Build chart data from report
  const breakdownData = report
    ? Object.entries(
        groupBy === "model"
          ? report.by_model
          : groupBy === "provider"
          ? report.by_provider
          : groupBy === "team"
          ? report.by_team
          : report.by_user,
      )
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .map(([name, value]) => ({ name, value }))
    : [];

  const actions = (
    <div className="flex gap-2">
      <select
        className="border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-sm bg-white dark:bg-gray-800"
        value={period}
        onChange={(e) => setPeriod(e.target.value)}
      >
        {PERIOD_OPTIONS.map((p) => (
          <option key={p.value} value={p.value}>{p.label}</option>
        ))}
      </select>
      <Button variant="secondary" onClick={handleExport}>
        <Download className="h-4 w-4 mr-1" />Export CSV
      </Button>
    </div>
  );

  return (
    <PageContainer title="Spend Analytics" description="Track costs across models, teams, and users" actions={actions}>
      {/* Tab bar */}
      <div className="flex gap-1 mb-6 border-b border-gray-200 dark:border-gray-700">
        {(["overview", "logs"] as const).map((t) => (
          <button
            key={t}
            className={`px-4 py-2 text-sm font-medium capitalize -mb-px border-b-2 transition-colors ${
              activeTab === t
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
            onClick={() => setActiveTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {activeTab === "overview" ? (
        reportLoading ? (
          <LoadingSpinner />
        ) : !report ? (
          <EmptyState title="No spend data" description="No spending data for the selected period." />
        ) : (
          <div className="space-y-6">
            {/* KPIs */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <KpiCard title="Total Spend" value={formatCurrency(report.total_spend)} icon={DollarSign} />
              <KpiCard title="Total Requests" value={formatCompactNumber(report.total_requests)} icon={TrendingUp} />
              <KpiCard title="Total Tokens" value={formatTokens(report.total_tokens)} icon={Zap} />
            </div>

            {/* Group-by selector + breakdown chart */}
            <Card
              title="Spend Breakdown"
              actions={
                <div className="flex gap-2">
                  {(["model", "provider", "team", "user"] as const).map((g) => (
                    <button
                      key={g}
                      className={`px-3 py-1 text-xs rounded-full capitalize ${
                        groupBy === g ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300" : "text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700"
                      }`}
                      onClick={() => setGroupBy(g)}
                    >
                      {g}
                    </button>
                  ))}
                </div>
              }
            >
              {breakdownData.length === 0 ? (
                <EmptyState title="No data" description="No breakdown data available." />
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Bar chart */}
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={breakdownData} layout="vertical" margin={{ left: 20, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
                      <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 12 }} />
                      <Tooltip formatter={(v: unknown) => formatCurrency(v as number)} />
                      <Bar dataKey="value" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>

                  {/* Pie chart */}
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie data={breakdownData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} isAnimationActive={false}>
                        {breakdownData.map((_, i) => (
                          <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                        ))}
                      </Pie>
                      <Legend />
                      <Tooltip formatter={(v: unknown) => formatCurrency(v as number)} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
          </div>
        )
      ) : (
        <div>
          <div className="mb-4">
            <input
              type="text"
              placeholder="Filter by model…"
              className="border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 w-64"
              value={modelFilter}
              onChange={(e) => setModelFilter(e.target.value)}
            />
          </div>
          <SpendLogsTable period={{}} modelFilter={modelFilter} />
        </div>
      )}
    </PageContainer>
  );
}
