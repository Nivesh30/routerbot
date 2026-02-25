import { useQuery } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { Model } from "../types";

/** Models come from the config — the /v1/models endpoint is read-only. */
export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: async () => {
      const resp = await api.get<{ data: Model[] }>(endpoints.models);
      return resp.data ?? [];
    },
  });
}

export function useModel(id: string) {
  return useQuery({
    queryKey: ["models", id],
    queryFn: () => api.get<Model>(endpoints.model(id)),
    enabled: !!id,
  });
}
