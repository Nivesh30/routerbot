import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { AuditEntry, PaginatedResponse, SSOProvider } from "../types";

export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<Record<string, unknown>>(endpoints.config),
  });
}

export function useReloadConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(endpoints.configReload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["config"] }),
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
