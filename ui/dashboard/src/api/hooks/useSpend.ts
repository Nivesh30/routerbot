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
    queryFn: () =>
      api.get<SpendSummary>(endpoints.spendReport, params as Record<string, string>),
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
    queryFn: () =>
      api.get<{ items: SpendRecord[]; total: number }>(
        endpoints.spendLogs,
        params as Record<string, string>,
      ),
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
