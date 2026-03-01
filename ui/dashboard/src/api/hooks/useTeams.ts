import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { Team } from "../types";

// Backend returns a different shape than our frontend Team type.
// This adapter normalizes backend fields to frontend fields.
interface BackendTeam {
  id: string;
  name: string;
  budget_limit?: number | null;
  spend: number;
  max_budget_per_member?: number | null;
  settings: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  members: { user_id: string; role: string; added_at: string | null }[];
}

function adaptTeam(bt: BackendTeam): Team {
  return {
    id: bt.id,
    team_alias: bt.name,
    max_budget: bt.budget_limit ?? undefined,
    current_spend: bt.spend ?? 0,
    member_count: bt.members?.length ?? 0,
    key_count: 0,
    models: (bt.settings?.allowed_models as string[]) ?? [],
    metadata: {},
    created_at: bt.created_at ?? "",
  };
}

export function useTeams() {
  return useQuery({
    queryKey: ["teams"],
    queryFn: async () => {
      const resp = await api.get<{ teams: BackendTeam[] }>(endpoints.teamList);
      return (resp.teams ?? []).map(adaptTeam);
    },
  });
}

export function useTeam(id: string) {
  return useQuery({
    queryKey: ["teams", id],
    queryFn: async () => {
      const resp = await api.get<BackendTeam>(endpoints.teamInfo(id));
      return adaptTeam(resp);
    },
    enabled: !!id,
  });
}

export function useCreateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Team>) => {
      // Map frontend field names to backend field names
      const payload: Record<string, unknown> = {};
      if (data.team_alias) payload.name = data.team_alias;
      if (data.max_budget != null) payload.budget_limit = data.max_budget;
      if (data.models?.length) payload.settings = { allowed_models: data.models };
      return api.post<BackendTeam>(endpoints.teamNew, payload);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });
}

export function useUpdateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Team> & { team_id: string }) => {
      const payload: Record<string, unknown> = { team_id: data.team_id };
      if (data.team_alias) payload.name = data.team_alias;
      if (data.max_budget != null) payload.budget_limit = data.max_budget;
      if (data.models) payload.settings = { allowed_models: data.models };
      return api.post<BackendTeam>(endpoints.teamUpdate, payload);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });
}

export function useDeleteTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (teamId: string) =>
      api.post(endpoints.teamDelete, { team_id: teamId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });
}

export function useAddTeamMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ teamId, userId }: { teamId: string; userId: string }) =>
      api.post(endpoints.teamMemberAdd, { team_id: teamId, user_id: userId }),
    onSuccess: (_, { teamId }) =>
      qc.invalidateQueries({ queryKey: ["teams", teamId] }),
  });
}

export function useRemoveTeamMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ teamId, userId }: { teamId: string; userId: string }) =>
      api.post(endpoints.teamMemberRemove, { team_id: teamId, user_id: userId }),
    onSuccess: (_, { teamId }) =>
      qc.invalidateQueries({ queryKey: ["teams", teamId] }),
  });
}
