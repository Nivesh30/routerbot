import type { DashboardPeriod } from "../../api/hooks/useDashboard";

interface PeriodSelectorProps {
  value: DashboardPeriod;
  onChange: (period: DashboardPeriod) => void;
}

const PERIODS: Array<{ value: DashboardPeriod; label: string }> = [
  { value: "1h", label: "1 Hour" },
  { value: "24h", label: "24 Hours" },
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
];

export function PeriodSelector({ value, onChange }: PeriodSelectorProps) {
  return (
    <div className="inline-flex rounded-lg border border-surface-200 bg-surface-50 p-0.5 dark:border-surface-700 dark:bg-surface-800">
      {PERIODS.map((p) => (
        <button
          key={p.value}
          type="button"
          onClick={() => onChange(p.value)}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            value === p.value
              ? "bg-white text-surface-900 shadow-sm dark:bg-surface-700 dark:text-surface-100"
              : "text-surface-500 hover:text-surface-700 dark:text-surface-400 dark:hover:text-surface-200"
          }`}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
