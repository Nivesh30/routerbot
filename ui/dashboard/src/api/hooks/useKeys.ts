import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { GeneratedKey, VirtualKey } from "../types";

export function useKeys(params?: { team_id?: string; user_id?: string }) {
  return useQuery({
    queryKey: ["keys", params],
    queryFn: () =>
      api.get<VirtualKey[]>(endpoints.keyList, params as Record<string, string>),
  });
}

export function useKey(id: string) {
  return useQuery({
    queryKey: ["keys", id],
    queryFn: () => api.get<VirtualKey>(endpoints.keyInfo, { key_id: id }),
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
    mutationFn: (keyId: string) =>
      api.post<GeneratedKey>(endpoints.keyRotate, { key_id: keyId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

export function useUpdateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<VirtualKey> & { key_id: string }) =>
      api.post<VirtualKey>(endpoints.keyUpdate, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

export function useDeleteKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      api.post(endpoints.keyDelete, { key_id: keyId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}
