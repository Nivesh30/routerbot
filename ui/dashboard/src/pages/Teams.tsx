import { Plus, Trash2, Edit, Users as UsersIcon, ChevronRight } from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { Card } from "../components/common/Card";
import { EmptyState } from "../components/common/EmptyState";
import { Input } from "../components/common/Input";
import { LoadingSpinner } from "../components/common/LoadingSpinner";
import { Modal } from "../components/common/Modal";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import {
  useTeams,
  useCreateTeam,
  useUpdateTeam,
  useDeleteTeam,
  useTeam,
  useAddTeamMember,
} from "../api/hooks/useTeams";
import { useUsers } from "../api/hooks/useUsers";
import { formatCurrency, formatNumber, formatDate } from "../utils/formatters";

import type { Column } from "../components/common/Table";
import type { Team } from "../api/types";

// ─── Budget bar ───────────────────────────────────────────────────────────────

function BudgetBar({ used, max }: { used: number; max?: number | null }) {
  const pct = max && max > 0 ? Math.min((used / max) * 100, 100) : 0;
  const color = pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-2 min-w-[60px]">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 whitespace-nowrap">
        {formatCurrency(used)}{max ? ` / ${formatCurrency(max)}` : ""}
      </span>
    </div>
  );
}

// ─── Create/Edit modal ────────────────────────────────────────────────────────

interface TeamFormData {
  team_alias: string;
  max_budget: string;
  models: string;
}

const EMPTY_FORM: TeamFormData = { team_alias: "", max_budget: "", models: "" };

function teamToForm(t: Team): TeamFormData {
  return {
    team_alias: t.team_alias,
    max_budget: t.max_budget != null ? String(t.max_budget) : "",
    models: t.models.join(", "),
  };
}

function TeamFormModal({
  open,
  editing,
  onClose,
}: {
  open: boolean;
  editing: Team | null;
  onClose: () => void;
}) {
  const [form, setForm] = useState<TeamFormData>(editing ? teamToForm(editing) : EMPTY_FORM);
  const [errors, setErrors] = useState<Partial<TeamFormData>>({});
  const create = useCreateTeam();
  const update = useUpdateTeam();

  function set(k: keyof TeamFormData, v: string) {
    setForm((p) => ({ ...p, [k]: v }));
    setErrors((p) => ({ ...p, [k]: undefined }));
  }

  function validate() {
    const e: Partial<TeamFormData> = {};
    if (!form.team_alias.trim()) e.team_alias = "Team name is required";
    if (form.max_budget && isNaN(parseFloat(form.max_budget)))
      e.max_budget = "Must be a number";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function handleSubmit() {
    if (!validate()) return;
    const payload = {
      team_alias: form.team_alias.trim(),
      ...(form.max_budget ? { max_budget: parseFloat(form.max_budget) } : {}),
      models: form.models ? form.models.split(",").map((m) => m.trim()).filter(Boolean) : [],
    };
    if (editing) {
      await update.mutateAsync({ ...payload, team_id: editing.id });
    } else {
      await create.mutateAsync(payload);
    }
    onClose();
  }

  const busy = create.isPending || update.isPending;

  return (
    <Modal
      open={open}
      title={editing ? "Edit Team" : "Create Team"}
      onClose={onClose}
      footer={
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={handleSubmit} loading={busy}>
            {editing ? "Save changes" : "Create team"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <Input
          label="Team name *"
          value={form.team_alias}
          onChange={(e) => set("team_alias", e.target.value)}
          error={errors.team_alias}
          placeholder="Engineering"
        />
        <Input
          label="Budget limit ($)"
          type="number"
          value={form.max_budget}
          onChange={(e) => set("max_budget", e.target.value)}
          error={errors.max_budget}
          placeholder="Unlimited"
        />
        <Input
          label="Allowed models (comma-separated)"
          value={form.models}
          onChange={(e) => set("models", e.target.value)}
          placeholder="gpt-4o, claude-sonnet-4-20250514"
        />
      </div>
    </Modal>
  );
}

// ─── Team detail panel ────────────────────────────────────────────────────────

function TeamDetailPanel({ teamId, onClose }: { teamId: string; onClose: () => void }) {
  const { data: team, isLoading } = useTeam(teamId);
  const { data: allUsers } = useUsers();
  const addMember = useAddTeamMember();
  const [adding, setAdding] = useState(false);
  const [userId, setUserId] = useState("");

  async function handleAdd() {
    if (!userId) return;
    await addMember.mutateAsync({ teamId, userId });
    setUserId("");
    setAdding(false);
  }

  return (
    <Modal open title={`Team: ${team?.team_alias ?? "..."}`} onClose={onClose}>
      {isLoading ? (
        <LoadingSpinner />
      ) : !team ? (
        <p className="text-gray-500">Team not found.</p>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <Card title="Spend"><BudgetBar used={team.current_spend} max={team.max_budget} /></Card>
            <Card title="Members"><p className="text-2xl font-bold">{team.member_count}</p></Card>
            <Card title="Keys"><p className="text-2xl font-bold">{team.key_count}</p></Card>
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="font-medium text-sm">Members</h4>
              <Button size="sm" onClick={() => setAdding(true)}><Plus className="h-3 w-3 mr-1" />Add</Button>
            </div>
            {adding && (
              <div className="flex gap-2 mb-2">
                <select
                  className="flex-1 border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                >
                  <option value="">Select user…</option>
                  {(allUsers ?? []).map((u) => (
                    <option key={u.id} value={u.id}>{u.email ?? u.id}</option>
                  ))}
                </select>
                <Button size="sm" onClick={handleAdd} loading={addMember.isPending}>Add</Button>
                <Button size="sm" variant="secondary" onClick={() => setAdding(false)}>Cancel</Button>
              </div>
            )}
          </div>
          {team.models.length > 0 && (
            <div>
              <h4 className="font-medium text-sm mb-2">Allowed models</h4>
              <div className="flex flex-wrap gap-1">
                {team.models.map((m) => <Badge key={m} variant="info">{m}</Badge>)}
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

// ─── Delete modal ─────────────────────────────────────────────────────────────

function DeleteTeamModal({ team, onClose }: { team: Team | null; onClose: () => void }) {
  const del = useDeleteTeam();
  return (
    <Modal
      open={!!team}
      title="Delete Team"
      onClose={onClose}
      footer={
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="danger" onClick={async () => { if (team) { await del.mutateAsync(team.id); onClose(); } }} loading={del.isPending}>
            Delete
          </Button>
        </div>
      }
    >
      {team && (
        <p>Are you sure you want to delete team <strong>{team.team_alias}</strong>?</p>
      )}
    </Modal>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function Teams() {
  const { data, isLoading, error } = useTeams();
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Team | null>(null);
  const [deleting, setDeleting] = useState<Team | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const teams = (data ?? []).filter((t) =>
    t.team_alias.toLowerCase().includes(search.toLowerCase()),
  );

  const columns: Column<Team>[] = [
    {
      key: "team_alias",
      header: "Team",
      sortable: true,
      render: (t: Team) => (
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center">
            <UsersIcon className="h-4 w-4 text-blue-600" />
          </div>
          <span className="font-medium">{t.team_alias}</span>
        </div>
      ),
    },
    { key: "current_spend", header: "Budget", sortable: true, render: (t: Team) => <BudgetBar used={t.current_spend} max={t.max_budget} /> },
    { key: "member_count", header: "Members", sortable: true, render: (t: Team) => formatNumber(t.member_count) },
    { key: "key_count", header: "Keys", sortable: true, render: (t: Team) => formatNumber(t.key_count) },
    {
      key: "models",
      header: "Models",
      render: (t: Team) =>
        t.models.length ? (
          <div className="flex flex-wrap gap-1">
            {t.models.slice(0, 2).map((m) => <Badge key={m} variant="info">{m}</Badge>)}
            {t.models.length > 2 && <Badge variant="neutral">+{t.models.length - 2}</Badge>}
          </div>
        ) : (
          <span className="text-gray-400 text-sm">all</span>
        ),
    },
    { key: "created_at", header: "Created", sortable: true, render: (t: Team) => formatDate(t.created_at) },
    {
      key: "id",
      header: "",
      render: (t: Team) => (
        <div className="flex gap-1 justify-end">
          <Button size="sm" variant="ghost" onClick={() => setDetailId(t.id)} title="View"><ChevronRight className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(t)} title="Edit"><Edit className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" onClick={() => setDeleting(t)} title="Delete" className="text-red-500 hover:text-red-700"><Trash2 className="h-4 w-4" /></Button>
        </div>
      ),
    },
  ];

  return (
    <PageContainer
      title="Teams"
      description="Manage teams, budgets, and members"
      actions={<Button onClick={() => setShowCreate(true)}><Plus className="h-4 w-4 mr-1" />New Team</Button>}
    >
      <div className="mb-4">
        <Input placeholder="Search teams…" value={search} onChange={(e) => setSearch(e.target.value)} className="max-w-xs" />
      </div>
      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <p className="text-red-500">Failed to load teams.</p>
      ) : teams.length === 0 ? (
        <EmptyState
          title="No teams yet"
          description="Create a team to organize users and budgets."
          action={<Button onClick={() => setShowCreate(true)}><Plus className="h-4 w-4 mr-1" />New Team</Button>}
        />
      ) : (
        <Table data={teams} columns={columns} keyFn={(t) => t.id} />
      )}
      <TeamFormModal open={showCreate || !!editing} editing={editing} onClose={() => { setShowCreate(false); setEditing(null); }} />
      <DeleteTeamModal team={deleting} onClose={() => setDeleting(null)} />
      {detailId && <TeamDetailPanel teamId={detailId} onClose={() => setDetailId(null)} />}
    </PageContainer>
  );
}
