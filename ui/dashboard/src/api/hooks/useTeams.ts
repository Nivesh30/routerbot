import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../client";
import { endpoints } from "../endpoints";
import type { Team, TeamMember } from "../types";

export function useTeams() {
  return useQuery({
    queryKey: ["teams"],
    queryFn: () => api.get<Team[]>(endpoints.teams),
  });
}

export function useTeam(id: string) {
  return useQuery({
    queryKey: ["teams", id],
    queryFn: () => api.get<Team>(endpoints.team(id)),
    enabled: !!id,
  });
}

export function useCreateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Team>) => api.post<Team>(endpoints.teams, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });
}

export function useUpdateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: Partial<Team> & { id: string }) =>
      api.put<Team>(endpoints.team(id), data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });
}

export function useDeleteTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(endpoints.team(id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });
}

export function useTeamMembers(teamId: string) {
  return useQuery({
    queryKey: ["teams", teamId, "members"],
    queryFn: () => api.get<TeamMember[]>(endpoints.teamMembers(teamId)),
    enabled: !!teamId,
  });
}

export function useAddTeamMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ teamId, userId, role }: { teamId: string; userId: string; role: string }) =>
      api.post(endpoints.teamMembers(teamId), { user_id: userId, role }),
    onSuccess: (_, { teamId }) =>
      qc.invalidateQueries({ queryKey: ["teams", teamId, "members"] }),
  });
}
