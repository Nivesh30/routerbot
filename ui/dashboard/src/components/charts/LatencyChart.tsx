import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface LatencyChartProps {
  data: Array<{ timestamp: string; p50: number; p95: number; p99: number }>;
  height?: number;
}

export function LatencyChart({ data, height = 300 }: LatencyChartProps) {
  const formatted = data.map((d) => ({
    ...d,
    time: new Date(d.timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={formatted}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="time" tick={{ fontSize: 12 }} stroke="#94a3b8" />
        <YAxis tick={{ fontSize: 12 }} stroke="#94a3b8" unit="ms" />
        <Tooltip
          contentStyle={{
            borderRadius: "8px",
            border: "1px solid #e2e8f0",
            fontSize: "13px",
          }}
          formatter={(value) => [`${value}ms`]}
        />
        <Legend />
        <Line type="monotone" dataKey="p50" stroke="#10b981" strokeWidth={2} dot={false} name="P50" />
        <Line type="monotone" dataKey="p95" stroke="#f59e0b" strokeWidth={2} dot={false} name="P95" />
        <Line type="monotone" dataKey="p99" stroke="#ef4444" strokeWidth={2} dot={false} name="P99" />
      </LineChart>
    </ResponsiveContainer>
  );
}
