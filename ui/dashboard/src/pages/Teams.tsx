import { Plus, Users as UsersIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "../components/common/Button";
import { Input } from "../components/common/Input";
import { Modal } from "../components/common/Modal";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import { formatCurrency, formatNumber } from "../utils/formatters";

import type { Column } from "../components/common/Table";
import type { Team } from "../api/types";

const mockTeams: Team[] = [
  {
    id: "team-1",
    team_alias: "Engineering",
    max_budget: 500,
    current_spend: 187.45,
    member_count: 12,
    key_count: 5,
    models: ["gpt-4o", "claude-sonnet-4-20250514"],
    metadata: {},
    created_at: "2024-01-01T00:00:00Z",
  },
  {
    id: "team-2",
    team_alias: "Data Science",
    max_budget: 300,
    current_spend: 92.10,
    member_count: 6,
    key_count: 3,
    models: ["gpt-4o"],
    metadata: {},
    created_at: "2024-01-15T00:00:00Z",
  },
];

const columns: Column<Team>[] = [
  { key: "team_alias", header: "Team", sortable: true },
  {
    key: "member_count",
    header: "Members",
    sortable: true,
    render: (t: Team) => (
      <span className="inline-flex items-center gap-1">
        <UsersIcon className="h-3.5 w-3.5 text-surface-400" />
        {formatNumber(t.member_count)}
      </span>
    ),
  },
  {
    key: "key_count",
    header: "Keys",
    sortable: true,
    render: (t: Team) => formatNumber(t.key_count),
  },
  {
    key: "current_spend",
    header: "Budget",
    render: (t: Team) => (
      <div className="space-y-1">
        <div className="text-sm">
          {formatCurrency(t.current_spend)} / {t.max_budget ? formatCurrency(t.max_budget) : "∞"}
        </div>
        {t.max_budget && (
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-200 dark:bg-surface-700">
            <div
              className="h-full rounded-full bg-primary-500"
              style={{ width: `${Math.min((t.current_spend / t.max_budget) * 100, 100)}%` }}
            />
          </div>
        )}
      </div>
    ),
  },
  {
    key: "models",
    header: "Models",
    render: (t: Team) => (
      <span className="text-xs text-surface-500">{t.models.join(", ")}</span>
    ),
  },
];

export function Teams() {
  const [showCreate, setShowCreate] = useState(false);

  return (
    <PageContainer
      title="Teams"
      description="Manage teams and their budgets"
      actions={
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => setShowCreate(true)}>
          Create Team
        </Button>
      }
    >
      <div className="rounded-xl border border-surface-200 bg-white dark:border-surface-700 dark:bg-surface-800">
        <Table
          columns={columns}
          data={mockTeams}
          keyFn={(item) => item.id}
          emptyMessage="No teams created"
        />
      </div>

      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="Create Team"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button onClick={() => setShowCreate(false)}>Create</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Team Name" placeholder="e.g. Engineering" />
          <Input label="Budget Limit ($)" type="number" placeholder="500" />
          <Input label="Allowed Models" placeholder="e.g. gpt-4o (comma-separated)" />
        </div>
      </Modal>
    </PageContainer>
  );
}
