import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { Model, ModelNewRequest, ModelTestResult, ModelUpdateRequest } from "../types";

/** List all models from the admin endpoint (with extended info). */
export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: async () => {
      const resp = await api.get<{ data: Model[]; total: number }>(endpoints.modelList);
      return resp.data ?? [];
    },
  });
}

/** Get a single model by name. */
export function useModel(name: string) {
  return useQuery({
    queryKey: ["models", name],
    queryFn: () => api.get<Model>(endpoints.modelInfo(name)),
    enabled: !!name,
  });
}

/** Add a new model. */
export function useAddModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ModelNewRequest) =>
      api.post<{ status: string; model: Model }>(endpoints.modelNew, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

/** Update an existing model. */
export function useUpdateModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ModelUpdateRequest) =>
      api.post<{ status: string; model: Model }>(endpoints.modelUpdate, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

/** Delete a model. */
export function useDeleteModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (model_name: string) =>
      api.post<{ status: string }>(endpoints.modelDelete, { model_name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

/** Test a model connection. */
export function useTestConnection() {
  return useMutation({
    mutationFn: (model_name: string) =>
      api.post<ModelTestResult>(endpoints.modelTest, { model_name }),
  });
}
