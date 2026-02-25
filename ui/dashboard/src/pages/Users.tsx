import { Plus } from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { Input } from "../components/common/Input";
import { Modal } from "../components/common/Modal";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import { formatCurrency, formatDate } from "../utils/formatters";

import type { Column } from "../components/common/Table";
import type { User } from "../api/types";

const mockUsers: User[] = [
  {
    id: "user-1",
    email: "alice@example.com",
    role: "admin",
    teams: ["Engineering"],
    max_budget: 200,
    current_spend: 78.50,
    status: "active",
    created_at: "2024-01-01T00:00:00Z",
  },
  {
    id: "user-2",
    email: "bob@example.com",
    role: "user",
    teams: ["Data Science"],
    max_budget: 50,
    current_spend: 12.30,
    status: "active",
    created_at: "2024-02-10T00:00:00Z",
  },
];

const roleVariant = {
  admin: "danger" as const,
  user: "info" as const,
  viewer: "neutral" as const,
};

const statusVariant = {
  active: "success" as const,
  disabled: "neutral" as const,
};

const columns: Column<User>[] = [
  { key: "email", header: "Email", sortable: true },
  {
    key: "role",
    header: "Role",
    sortable: true,
    render: (u: User) => <Badge variant={roleVariant[u.role]}>{u.role}</Badge>,
  },
  {
    key: "teams",
    header: "Teams",
    render: (u: User) => (
      <span className="text-xs text-surface-500">{u.teams.join(", ") || "—"}</span>
    ),
  },
  {
    key: "current_spend",
    header: "Spend",
    sortable: true,
    render: (u: User) => formatCurrency(u.current_spend),
  },
  {
    key: "status",
    header: "Status",
    render: (u: User) => <Badge variant={statusVariant[u.status]}>{u.status}</Badge>,
  },
  {
    key: "created_at",
    header: "Created",
    sortable: true,
    render: (u: User) => formatDate(u.created_at),
  },
];

export function Users() {
  const [showCreate, setShowCreate] = useState(false);

  return (
    <PageContainer
      title="Users"
      description="Manage user accounts and roles"
      actions={
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => setShowCreate(true)}>
          Add User
        </Button>
      }
    >
      <div className="rounded-xl border border-surface-200 bg-white dark:border-surface-700 dark:bg-surface-800">
        <Table
          columns={columns}
          data={mockUsers}
          keyFn={(item) => item.id}
          emptyMessage="No users"
        />
      </div>

      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="Add User"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button onClick={() => setShowCreate(false)}>Add</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Email" type="email" placeholder="user@example.com" />
          <Input label="Role" placeholder="admin, user, or viewer" />
          <Input label="Budget Limit ($)" type="number" placeholder="100" />
        </div>
      </Modal>
    </PageContainer>
  );
}
