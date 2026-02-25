import { useQuery } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { SpendRecord, SpendSummary } from "../types";

export function useSpendSummary(params?: {
  period?: string;
  start_date?: string;
  end_date?: string;
  group_by?: string;
}) {
  return useQuery({
    queryKey: ["spend", "summary", params],
    queryFn: () =>
      api.get<SpendSummary>(endpoints.spendSummary, params as Record<string, string>),
  });
}

export function useSpendLogs(params?: {
  page?: number;
  per_page?: number;
  model?: string;
  team_id?: string;
  user_id?: string;
  start_date?: string;
  end_date?: string;
}) {
  return useQuery({
    queryKey: ["spend", "logs", params],
    queryFn: () =>
      api.get<{ items: SpendRecord[]; total: number }>(
        endpoints.spendLogs,
        params as Record<string, string>,
      ),
  });
}

export function useSpendExportUrl(params?: {
  format?: "csv" | "json";
  start_date?: string;
  end_date?: string;
}) {
  const searchParams = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v) searchParams.set(k, v);
    }
  }
  const qs = searchParams.toString();
  return `${endpoints.spendExport}${qs ? `?${qs}` : ""}`;
}
