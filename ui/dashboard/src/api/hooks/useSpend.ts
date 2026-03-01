import { useQuery } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { SpendRecord, SpendSummary } from "../types";

export function useSpendReport(params?: {
  start_date?: string;
  end_date?: string;
  group_by?: string;
}) {
  return useQuery({
    queryKey: ["spend", "report", params],
    queryFn: async () => {
      const resp = await api.get<{ report: { model: string; total_cost: number }[] }>(
        endpoints.spendReport,
        params as Record<string, string>,
      );
      const report = resp.report ?? [];
      const by_model: Record<string, number> = {};
      let total_spend = 0;
      for (const r of report) {
        by_model[r.model] = r.total_cost;
        total_spend += r.total_cost;
      }
      return {
        total_spend,
        total_requests: 0,
        total_tokens: 0,
        period_start: "",
        period_end: "",
        by_model,
        by_provider: {},
        by_team: {},
        by_user: {},
      } as SpendSummary;
    },
  });
}

export function useSpendLogs(params?: {
  page?: number;
  per_page?: number;
  model?: string;
  team_id?: string;
  user_id?: string;
  key_id?: string;
  start_date?: string;
  end_date?: string;
}) {
  return useQuery({
    queryKey: ["spend", "logs", params],
    queryFn: async () => {
      const resp = await api.get<{ logs: SpendRecord[] }>(
        endpoints.spendLogs,
        params as Record<string, string>,
      );
      return { items: resp.logs ?? [], total: (resp.logs ?? []).length };
    },
  });
}

export function useSpendByKey(keyId: string) {
  return useQuery({
    queryKey: ["spend", "keys", keyId],
    queryFn: () =>
      api.get<SpendSummary>(endpoints.spendKeys, { key_id: keyId }),
    enabled: !!keyId,
  });
}
