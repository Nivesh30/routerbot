import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { GeneratedKey, VirtualKey } from "../types";

export function useKeys(params?: { team_id?: string; user_id?: string; status?: string }) {
  return useQuery({
    queryKey: ["keys", params],
    queryFn: () =>
      api.get<VirtualKey[]>(endpoints.keys, params as Record<string, string>),
  });
}

export function useKey(id: string) {
  return useQuery({
    queryKey: ["keys", id],
    queryFn: () => api.get<VirtualKey>(endpoints.key(id)),
    enabled: !!id,
  });
}

export function useGenerateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<VirtualKey>) =>
      api.post<GeneratedKey>(endpoints.keyGenerate, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

export function useRotateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<GeneratedKey>(endpoints.keyRotate(id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

export function useDeleteKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(endpoints.key(id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}
