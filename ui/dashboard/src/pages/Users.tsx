import { Plus, Trash2, Edit, User as UserIcon } from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";
import { Input } from "../components/common/Input";
import { LoadingSpinner } from "../components/common/LoadingSpinner";
import { Modal } from "../components/common/Modal";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import {
  useUsers,
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
} from "../api/hooks/useUsers";
import { formatCurrency, formatDate } from "../utils/formatters";

import type { Column } from "../components/common/Table";
import type { User } from "../api/types";

// ─── Role badge ───────────────────────────────────────────────────────────────

const ROLE_VARIANT: Record<string, "success" | "info" | "warning" | "danger" | "neutral"> = {
  admin: "danger",
  user: "info",
  viewer: "neutral",
};

// ─── User form modal ──────────────────────────────────────────────────────────

interface UserFormData {
  email: string;
  role: "admin" | "user" | "viewer";
  max_budget: string;
}

const EMPTY_FORM: UserFormData = { email: "", role: "user", max_budget: "" };

function userToForm(u: User): UserFormData {
  return {
    email: u.email ?? "",
    role: u.role,
    max_budget: u.max_budget != null ? String(u.max_budget) : "",
  };
}

function UserFormModal({
  open,
  editing,
  onClose,
}: {
  open: boolean;
  editing: User | null;
  onClose: () => void;
}) {
  const [form, setForm] = useState<UserFormData>(editing ? userToForm(editing) : EMPTY_FORM);
  const [errors, setErrors] = useState<Partial<UserFormData>>({});
  const create = useCreateUser();
  const update = useUpdateUser();

  function set<K extends keyof UserFormData>(k: K, v: UserFormData[K]) {
    setForm((p) => ({ ...p, [k]: v }));
    setErrors((p) => ({ ...p, [k]: undefined }));
  }

  function validate() {
    const e: Partial<UserFormData> = {};
    if (!editing && !form.email.trim()) e.email = "Email is required";
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
      e.email = "Invalid email";
    if (form.max_budget && isNaN(parseFloat(form.max_budget)))
      e.max_budget = "Must be a number";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function handleSubmit() {
    if (!validate()) return;
    const payload = {
      email: form.email.trim() || undefined,
      role: form.role,
      ...(form.max_budget ? { max_budget: parseFloat(form.max_budget) } : {}),
    };
    if (editing) {
      await update.mutateAsync({ ...payload, user_id: editing.id });
    } else {
      await create.mutateAsync(payload);
    }
    onClose();
  }

  const busy = create.isPending || update.isPending;

  return (
    <Modal
      open={open}
      title={editing ? "Edit User" : "Create User"}
      onClose={onClose}
      footer={
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={handleSubmit} loading={busy}>
            {editing ? "Save changes" : "Create user"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <Input
          label={editing ? "Email" : "Email *"}
          type="email"
          value={form.email}
          onChange={(e) => set("email", e.target.value)}
          error={errors.email as string}
          placeholder="alice@example.com"
          readOnly={!!editing}
        />
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Role</label>
          <select
            className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            value={form.role}
            onChange={(e) => set("role", e.target.value as UserFormData["role"])}
          >
            <option value="viewer">Viewer</option>
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <Input
          label="Budget limit ($)"
          type="number"
          value={form.max_budget}
          onChange={(e) => set("max_budget", e.target.value)}
          error={errors.max_budget as string}
          placeholder="Unlimited"
        />
      </div>
    </Modal>
  );
}

// ─── Delete modal ─────────────────────────────────────────────────────────────

function DeleteUserModal({ user, onClose }: { user: User | null; onClose: () => void }) {
  const del = useDeleteUser();
  return (
    <Modal
      open={!!user}
      title="Delete User"
      onClose={onClose}
      footer={
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button
            variant="danger"
            loading={del.isPending}
            onClick={async () => { if (user) { await del.mutateAsync(user.id); onClose(); } }}
          >
            Delete
          </Button>
        </div>
      }
    >
      {user && (
        <p>Are you sure you want to delete user <strong>{user.email ?? user.id}</strong>?</p>
      )}
    </Modal>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function Users() {
  const { data, isLoading, error } = useUsers();
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);

  const users = (data ?? []).filter((u) => {
    const matchSearch =
      !search ||
      (u.email ?? "").toLowerCase().includes(search.toLowerCase()) ||
      u.id.toLowerCase().includes(search.toLowerCase());
    const matchRole = roleFilter === "all" || u.role === roleFilter;
    return matchSearch && matchRole;
  });

  const columns: Column<User>[] = [
    {
      key: "email",
      header: "User",
      sortable: true,
      render: (u: User) => (
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-full bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
            <UserIcon className="h-4 w-4 text-gray-500" />
          </div>
          <div>
            <p className="font-medium">{u.email ?? "—"}</p>
            <p className="text-xs text-gray-400 font-mono">{u.id.slice(0, 8)}…</p>
          </div>
        </div>
      ),
    },
    {
      key: "role",
      header: "Role",
      sortable: true,
      render: (u: User) => (
        <Badge variant={ROLE_VARIANT[u.role] ?? "default"}>
          {u.role}
        </Badge>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (u: User) => (
        <Badge variant={u.status === "active" ? "success" : "neutral"}>
          {u.status}
        </Badge>
      ),
    },
    {
      key: "current_spend",
      header: "Spend",
      sortable: true,
      render: (u: User) => {
        const pct = u.max_budget ? Math.round((u.current_spend / u.max_budget) * 100) : null;
        return (
          <div>
            <span>{formatCurrency(u.current_spend)}</span>
            {u.max_budget && (
              <span className="text-gray-400 text-xs ml-1">/ {formatCurrency(u.max_budget)} ({pct}%)</span>
            )}
          </div>
        );
      },
    },
    {
      key: "teams",
      header: "Teams",
      render: (u: User) =>
        u.teams.length ? (
          <div className="flex flex-wrap gap-1">
            {u.teams.slice(0, 2).map((t) => <Badge key={t} variant="neutral">{t}</Badge>)}
            {u.teams.length > 2 && <Badge variant="neutral">+{u.teams.length - 2}</Badge>}
          </div>
        ) : (
          <span className="text-gray-400 text-sm">—</span>
        ),
    },
    { key: "created_at", header: "Created", sortable: true, render: (u: User) => formatDate(u.created_at) },
    {
      key: "id",
      header: "",
      render: (u: User) => (
        <div className="flex gap-1 justify-end">
          <Button size="sm" variant="ghost" onClick={() => setEditing(u)} title="Edit"><Edit className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" onClick={() => setDeleting(u)} title="Delete" className="text-red-500 hover:text-red-700"><Trash2 className="h-4 w-4" /></Button>
        </div>
      ),
    },
  ];

  return (
    <PageContainer
      title="Users"
      description="Manage users, roles, and budgets"
      actions={<Button onClick={() => setShowCreate(true)}><Plus className="h-4 w-4 mr-1" />New User</Button>}
    >
      <div className="mb-4 flex gap-2">
        <Input
          placeholder="Search users…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <select
          className="border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
        >
          <option value="all">All roles</option>
          <option value="admin">Admin</option>
          <option value="user">User</option>
          <option value="viewer">Viewer</option>
        </select>
      </div>
      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <p className="text-red-500">Failed to load users.</p>
      ) : users.length === 0 ? (
        <EmptyState
          title="No users found"
          description={search || roleFilter !== "all" ? "Try adjusting your filters." : "Create a user to get started."}
          action={
            !search && roleFilter === "all" ? (
              <Button onClick={() => setShowCreate(true)}><Plus className="h-4 w-4 mr-1" />New User</Button>
            ) : undefined
          }
        />
      ) : (
        <Table data={users} columns={columns} keyFn={(u) => u.id} />
      )}
      <UserFormModal open={showCreate || !!editing} editing={editing} onClose={() => { setShowCreate(false); setEditing(null); }} />
      <DeleteUserModal user={deleting} onClose={() => setDeleting(null)} />
    </PageContainer>
  );
}
