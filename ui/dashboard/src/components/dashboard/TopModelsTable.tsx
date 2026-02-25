import { formatCompactNumber, formatCurrency } from "../../utils/formatters";

interface TopModelsTableProps {
  models: Array<{ model: string; requests: number; spend: number }>;
}

export function TopModelsTable({ models }: TopModelsTableProps) {
  if (models.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-surface-400">
        No model activity yet
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-200 dark:border-surface-700">
            <th className="pb-2 font-medium text-surface-500">Model</th>
            <th className="pb-2 text-right font-medium text-surface-500">Requests</th>
            <th className="pb-2 text-right font-medium text-surface-500">Spend</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr
              key={m.model}
              className="border-b border-surface-100 last:border-0 dark:border-surface-800"
            >
              <td className="py-2 font-medium text-surface-900 dark:text-surface-100">
                {m.model}
              </td>
              <td className="py-2 text-right tabular-nums text-surface-600 dark:text-surface-400">
                {formatCompactNumber(m.requests)}
              </td>
              <td className="py-2 text-right tabular-nums text-surface-600 dark:text-surface-400">
                {formatCurrency(m.spend)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
