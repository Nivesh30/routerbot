import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface SpendByModelChartProps {
  data: Record<string, number>;
  height?: number;
}

const COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
];

export function SpendByModelChart({ data, height = 280 }: SpendByModelChartProps) {
  const chartData = Object.entries(data)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([model, spend], i) => ({
      model: model.length > 20 ? model.slice(0, 18) + "…" : model,
      spend: +spend.toFixed(4),
      fill: COLORS[i % COLORS.length],
    }));

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-surface-400" style={{ height }}>
        No spend data yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={chartData} margin={{ bottom: 40 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis
          dataKey="model"
          tick={{ fontSize: 11 }}
          stroke="#94a3b8"
          angle={-35}
          textAnchor="end"
          height={60}
        />
        <YAxis
          tick={{ fontSize: 12 }}
          stroke="#94a3b8"
          tickFormatter={(v) => `$${v}`}
        />
        <Tooltip
          contentStyle={{
            borderRadius: "8px",
            border: "1px solid #e2e8f0",
            fontSize: "13px",
          }}
          formatter={(value) => [`$${Number(value).toFixed(4)}`, "Spend"]}
        />
        <Bar dataKey="spend" radius={[4, 4, 0, 0]} barSize={32} />
      </BarChart>
    </ResponsiveContainer>
  );
}
