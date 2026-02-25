import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { AuditEntry, PaginatedResponse, SSOProvider } from "../types";

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<Record<string, unknown>>(endpoints.settings),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.put(endpoints.settings, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useSSOProviders() {
  return useQuery({
    queryKey: ["sso-providers"],
    queryFn: () => api.get<SSOProvider[]>(endpoints.ssoProviders),
  });
}

export function useAuditLogs(params?: {
  page?: number;
  per_page?: number;
  actor?: string;
  action?: string;
  start_date?: string;
  end_date?: string;
}) {
  return useQuery({
    queryKey: ["audit-logs", params],
    queryFn: () =>
      api.get<PaginatedResponse<AuditEntry>>(
        endpoints.auditLogs,
        params as Record<string, string>,
      ),
  });
}
