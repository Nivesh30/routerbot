import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type {
  GeneratedKeyResponse,
  KeyGenerateRequest,
  KeyRotateRequest,
  KeyUpdateRequest,
  RotatedKeyResponse,
  VirtualKey,
} from "../types";

/** List all virtual keys, optionally filtered by team or user. */
export function useKeys(params?: {
  team_id?: string;
  user_id?: string;
  active_only?: boolean;
}) {
  return useQuery({
    queryKey: ["keys", params],
    queryFn: async () => {
      const resp = await api.get<{ keys: VirtualKey[]; count: number }>(
        endpoints.keyList,
        params as Record<string, string>,
      );
      return resp.keys ?? [];
    },
  });
}

/** Get a single key by ID. */
export function useKey(id: string) {
  return useQuery({
    queryKey: ["keys", id],
    queryFn: () => api.get<VirtualKey>(endpoints.keyInfo, { key_id: id }),
    enabled: !!id,
  });
}

/** Generate a new virtual API key. Returns the plaintext key once. */
export function useGenerateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: KeyGenerateRequest) =>
      api.post<GeneratedKeyResponse>(endpoints.keyGenerate, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

/** Rotate a key — deactivate old, generate new. */
export function useRotateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: KeyRotateRequest) =>
      api.post<RotatedKeyResponse>(endpoints.keyRotate, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

/** Update a key's settings (partial update). */
export function useUpdateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: KeyUpdateRequest) =>
      api.post<VirtualKey>(endpoints.keyUpdate, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}

/** Soft-delete (deactivate) a key. */
export function useDeleteKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      api.post<{ status: string }>(endpoints.keyDelete, { key_id: keyId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });
}
