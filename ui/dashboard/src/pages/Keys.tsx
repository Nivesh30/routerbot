import { Plus } from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { CopyButton } from "../components/common/CopyButton";
import { Input } from "../components/common/Input";
import { Modal } from "../components/common/Modal";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import { formatCurrency, truncateKey } from "../utils/formatters";

import type { Column } from "../components/common/Table";
import type { VirtualKey } from "../api/types";

const mockKeys: VirtualKey[] = [
  {
    id: "1",
    key_prefix: "sk-rb-abc",
    key_name: "Production Key",
    team_id: "team-1",
    user_id: "user-1",
    models: ["gpt-4o", "claude-sonnet-4-20250514"],
    max_budget: 100,
    current_spend: 48.32,
    rpm_limit: 100,
    tpm_limit: 50000,
    status: "active",
    ip_restrictions: [],
    metadata: {},
    created_at: "2024-01-15T10:00:00Z",
  },
  {
    id: "2",
    key_prefix: "sk-rb-def",
    key_name: "Dev Key",
    models: ["gpt-4o"],
    max_budget: 20,
    current_spend: 5.12,
    status: "active",
    ip_restrictions: [],
    metadata: {},
    created_at: "2024-02-01T14:00:00Z",
  },
];

const statusVariant = {
  active: "success" as const,
  expired: "warning" as const,
  revoked: "danger" as const,
};

const columns: Column<VirtualKey>[] = [
  {
    key: "key_prefix",
    header: "Key",
    render: (k: VirtualKey) => (
      <div className="flex items-center gap-1">
        <code className="text-xs">{truncateKey(k.key_prefix)}</code>
        <CopyButton text={k.key_prefix} />
      </div>
    ),
  },
  { key: "key_name", header: "Name", sortable: true },
  { key: "team_id", header: "Team", sortable: true },
  {
    key: "models",
    header: "Models",
    render: (k: VirtualKey) => (
      <span className="text-xs text-surface-500">
        {k.models.length > 0 ? k.models.join(", ") : "All"}
      </span>
    ),
  },
  {
    key: "current_spend",
    header: "Budget",
    render: (k: VirtualKey) => (
      <div className="space-y-1">
        <div className="text-sm">
          {formatCurrency(k.current_spend)} / {k.max_budget ? formatCurrency(k.max_budget) : "∞"}
        </div>
        {k.max_budget && (
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-200 dark:bg-surface-700">
            <div
              className="h-full rounded-full bg-primary-500"
              style={{ width: `${Math.min((k.current_spend / k.max_budget) * 100, 100)}%` }}
            />
          </div>
        )}
      </div>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (k: VirtualKey) => (
      <Badge variant={statusVariant[k.status]}>{k.status}</Badge>
    ),
  },
];

export function Keys() {
  const [showGenerate, setShowGenerate] = useState(false);

  return (
    <PageContainer
      title="Virtual Keys"
      description="Manage API keys for teams and users"
      actions={
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => setShowGenerate(true)}>
          Generate Key
        </Button>
      }
    >
      <div className="rounded-xl border border-surface-200 bg-white dark:border-surface-700 dark:bg-surface-800">
        <Table
          columns={columns}
          data={mockKeys}
          keyFn={(item) => item.id}
          emptyMessage="No keys generated"
        />
      </div>

      <Modal
        open={showGenerate}
        onClose={() => setShowGenerate(false)}
        title="Generate Virtual Key"
        size="lg"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowGenerate(false)}>
              Cancel
            </Button>
            <Button onClick={() => setShowGenerate(false)}>Generate</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Key Name" placeholder="e.g. Production Key" />
          <div className="grid grid-cols-2 gap-4">
            <Input label="Team" placeholder="Select team" />
            <Input label="User" placeholder="Select user" />
          </div>
          <Input label="Allowed Models" placeholder="e.g. gpt-4o, claude-sonnet-4-20250514 (comma-separated)" />
          <div className="grid grid-cols-2 gap-4">
            <Input label="Budget Limit ($)" type="number" placeholder="100" />
            <Input label="Expiration" type="date" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Input label="RPM Limit" type="number" placeholder="100" />
            <Input label="TPM Limit" type="number" placeholder="50000" />
          </div>
        </div>
      </Modal>
    </PageContainer>
  );
}
