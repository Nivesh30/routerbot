import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { Team } from "../types";

export function useTeams() {
  return useQuery({
    queryKey: ["teams"],
    queryFn: () => api.get<Team[]>(endpoints.teamList),
  });
}

export function useTeam(id: string) {
  return useQuery({
    queryKey: ["teams", id],
    queryFn: () => api.get<Team>(endpoints.teamInfo(id)),
    enabled: !!id,
  });
}

export function useCreateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Team>) => api.post<Team>(endpoints.teamNew, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });
}

export function useUpdateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Team> & { team_id: string }) =>
      api.post<Team>(endpoints.teamUpdate, data),
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
