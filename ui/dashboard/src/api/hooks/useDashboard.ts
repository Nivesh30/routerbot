import { useQuery } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { DashboardMetrics, HealthStatus } from "../types";

export type DashboardPeriod = "1h" | "24h" | "7d" | "30d";

export function useDashboardStats(
  period: DashboardPeriod = "24h",
  refetchInterval: number | false = 30000,
) {
  return useQuery({
    queryKey: ["dashboard", "stats", period],
    queryFn: () =>
      api.get<DashboardMetrics>(endpoints.dashboardStats, { period }),
    refetchInterval,
    staleTime: 10000,
  });
}

export function useHealthStatus() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthStatus>(endpoints.dashboard),
    refetchInterval: 30000,
  });
}
