import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { Model } from "../types";

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: () => api.get<Model[]>(endpoints.models),
  });
}

export function useModel(id: string) {
  return useQuery({
    queryKey: ["models", id],
    queryFn: () => api.get<Model>(endpoints.model(id)),
    enabled: !!id,
  });
}

export function useCreateModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Model>) => api.post<Model>(endpoints.models, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

export function useUpdateModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: Partial<Model> & { id: string }) =>
      api.put<Model>(endpoints.model(id), data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

export function useDeleteModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(endpoints.model(id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

export function useTestModel() {
  return useMutation({
    mutationFn: (id: string) =>
      api.post<{ success: boolean; latency_ms: number }>(endpoints.modelTest(id)),
  });
}
