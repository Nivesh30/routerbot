import { Download } from "lucide-react";
import { useState } from "react";

import { Card } from "../components/common/Card";
import { Button } from "../components/common/Button";
import { SpendChart } from "../components/charts/SpendChart";
import { PageContainer } from "../components/layout/PageContainer";
import { formatCurrency, formatCompactNumber, formatTokens } from "../utils/formatters";
import { PERIOD_OPTIONS } from "../utils/constants";

const mockSummary = {
  total_spend: 1248.72,
  total_requests: 45_230,
  total_tokens: 12_500_000,
  by_model: {
    "gpt-4o": 680.45,
    "claude-sonnet-4-20250514": 412.30,
    "gemini-2.0-flash": 82.14,
    "gpt-4o-mini": 73.83,
  },
  by_provider: {
    openai: 754.28,
    anthropic: 412.30,
    google: 82.14,
  },
};

const mockSpendTimeline = Array.from({ length: 30 }, (_, i) => ({
  timestamp: new Date(Date.now() - (29 - i) * 86_400_000).toISOString(),
  value: +(Math.random() * 60 + 20).toFixed(2),
}));

export function Spend() {
  const [period, setPeriod] = useState("30d");

  return (
    <PageContainer
      title="Spend Analytics"
      description="Monitor costs across models, teams, and users"
      actions={
        <Button variant="secondary" icon={<Download className="h-4 w-4" />}>
          Export CSV
        </Button>
      }
    >
      {/* Period selector */}
      <div className="mb-6 flex items-center gap-2">
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setPeriod(opt.value)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              period === opt.value
                ? "bg-primary-600 text-white"
                : "text-surface-600 hover:bg-surface-100 dark:text-surface-400 dark:hover:bg-surface-800"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Summary cards */}
      <div className="mb-6 grid grid-cols-3 gap-4">
        <Card>
          <p className="text-sm text-surface-500">Total Spend</p>
          <p className="text-2xl font-bold text-surface-900 dark:text-surface-100">
            {formatCurrency(mockSummary.total_spend)}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-surface-500">Total Requests</p>
          <p className="text-2xl font-bold text-surface-900 dark:text-surface-100">
            {formatCompactNumber(mockSummary.total_requests)}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-surface-500">Total Tokens</p>
          <p className="text-2xl font-bold text-surface-900 dark:text-surface-100">
            {formatTokens(mockSummary.total_tokens)}
          </p>
        </Card>
      </div>

      {/* Spend chart */}
      <Card title="Spend Over Time" className="mb-6">
        <SpendChart data={mockSpendTimeline} height={320} />
      </Card>

      {/* Breakdown tables */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Spend by Model">
          <div className="space-y-3">
            {Object.entries(mockSummary.by_model)
              .sort(([, a], [, b]) => b - a)
              .map(([model, spend]) => (
                <div key={model} className="flex items-center justify-between">
                  <span className="text-sm text-surface-700 dark:text-surface-300">
                    {model}
                  </span>
                  <div className="flex items-center gap-3">
                    <div className="h-2 w-32 overflow-hidden rounded-full bg-surface-200 dark:bg-surface-700">
                      <div
                        className="h-full rounded-full bg-primary-500"
                        style={{
                          width: `${(spend / mockSummary.total_spend) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="w-20 text-right text-sm font-medium text-surface-900 dark:text-surface-100">
                      {formatCurrency(spend)}
                    </span>
                  </div>
                </div>
              ))}
          </div>
        </Card>

        <Card title="Spend by Provider">
          <div className="space-y-3">
            {Object.entries(mockSummary.by_provider)
              .sort(([, a], [, b]) => b - a)
              .map(([provider, spend]) => (
                <div key={provider} className="flex items-center justify-between">
                  <span className="text-sm capitalize text-surface-700 dark:text-surface-300">
                    {provider}
                  </span>
                  <div className="flex items-center gap-3">
                    <div className="h-2 w-32 overflow-hidden rounded-full bg-surface-200 dark:bg-surface-700">
                      <div
                        className="h-full rounded-full bg-emerald-500"
                        style={{
                          width: `${(spend / mockSummary.total_spend) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="w-20 text-right text-sm font-medium text-surface-900 dark:text-surface-100">
                      {formatCurrency(spend)}
                    </span>
                  </div>
                </div>
              ))}
          </div>
        </Card>
      </div>
    </PageContainer>
  );
}
