import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { User } from "../types";

// Backend returns a different shape than our frontend User type
interface BackendUser {
  id: string;
  email: string | null;
  role: string;
  max_budget: number | null;
  spend: number;
  is_active: boolean;
  sso_provider_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

function adaptUser(bu: BackendUser): User {
  return {
    id: bu.id,
    email: bu.email ?? undefined,
    role: (bu.role === "admin" ? "admin" : bu.role === "viewer" ? "viewer" : "user") as User["role"],
    teams: [],
    max_budget: bu.max_budget ?? undefined,
    current_spend: bu.spend ?? 0,
    status: bu.is_active ? "active" : "disabled",
    created_at: bu.created_at ?? "",
  };
}

export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: async () => {
      const resp = await api.get<{ users: BackendUser[] }>(endpoints.userList);
      return (resp.users ?? []).map(adaptUser);
    },
  });
}

export function useUser(id: string) {
  return useQuery({
    queryKey: ["users", id],
    queryFn: async () => {
      const resp = await api.get<BackendUser>(endpoints.userInfo(id));
      return adaptUser(resp);
    },
    enabled: !!id,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<User>) => {
      const payload: Record<string, unknown> = {};
      if (data.email) payload.email = data.email;
      if (data.role) payload.role = data.role === "user" ? "api_user" : data.role;
      if (data.max_budget != null) payload.max_budget = data.max_budget;
      return api.post<BackendUser>(endpoints.userNew, payload);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<User> & { user_id: string }) => {
      const payload: Record<string, unknown> = { user_id: data.user_id };
      if (data.email) payload.email = data.email;
      if (data.role) payload.role = data.role === "user" ? "api_user" : data.role;
      if (data.max_budget != null) payload.max_budget = data.max_budget;
      return api.post<BackendUser>(endpoints.userUpdate, payload);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      api.post(endpoints.userDelete, { user_id: userId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}
