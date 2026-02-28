import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type {
  AuditEntry,
  ConfigUpdateRequest,
  ConfigUpdateResponse,
  PaginatedResponse,
  SSOProvider,
} from "../types";

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

export function useUpdateConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ConfigUpdateRequest) =>
      api.post<ConfigUpdateResponse>(endpoints.configUpdate, data),
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
    queryFn: async () => {
      const page = params?.page ?? 1;
      const per_page = params?.per_page ?? 25;
      const offset = (page - 1) * per_page;
      // Backend uses offset/limit, convert from page/per_page
      const queryParams: Record<string, string> = {
        offset: String(offset),
        limit: String(per_page),
      };
      if (params?.actor) queryParams.actor_id = params.actor;
      if (params?.action) queryParams.action = params.action;
      if (params?.start_date) queryParams.start_date = params.start_date;
      if (params?.end_date) queryParams.end_date = params.end_date;

      const resp = await api.get<{ logs: AuditEntry[]; total: number; offset: number; limit: number }>(
        endpoints.auditLogs,
        queryParams,
      );
      const logs = resp.logs ?? [];
      const total = resp.total ?? 0;
      return {
        items: logs,
        total,
        page,
        per_page,
        pages: Math.ceil(total / per_page),
      } as PaginatedResponse<AuditEntry>;
    },
  });
}
