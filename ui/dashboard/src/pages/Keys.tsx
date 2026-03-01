import {
  AlertTriangle,
  CheckCircle,
  ClipboardCopy,
  Key,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useCallback, useState } from "react";

import {
  useDeleteKey,
  useGenerateKey,
  useKeys,
  useRotateKey,
  useUpdateKey,
} from "../api/hooks/useKeys";
import { useModels } from "../api/hooks/useModels";
import { useTeams } from "../api/hooks/useTeams";
import { useUsers } from "../api/hooks/useUsers";
import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { CopyButton } from "../components/common/CopyButton";
import { Input } from "../components/common/Input";
import { Modal } from "../components/common/Modal";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import { formatCurrency, formatDate, truncateKey } from "../utils/formatters";

import type { Column } from "../components/common/Table";
import type { KeyGenerateRequest, KeyUpdateRequest, VirtualKey } from "../api/types";

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------
interface KeyFormState {
  user_id: string;
  team_id: string;
  models: string;
  max_budget: string;
  rate_limit_rpm: string;
  rate_limit_tpm: string;
  expires_at: string;
  metadata: string;
}

const EMPTY_FORM: KeyFormState = {
  user_id: "",
  team_id: "",
  models: "",
  max_budget: "",
  rate_limit_rpm: "",
  rate_limit_tpm: "",
  expires_at: "",
  metadata: "",
};

function formFromKey(k: VirtualKey): KeyFormState {
  return {
    user_id: k.user_id ?? "",
    team_id: k.team_id ?? "",
    models: k.models.length > 0 ? k.models.join(", ") : "",
    max_budget: k.max_budget != null ? String(k.max_budget) : "",
    rate_limit_rpm: k.rate_limit_rpm != null ? String(k.rate_limit_rpm) : "",
    rate_limit_tpm: k.rate_limit_tpm != null ? String(k.rate_limit_tpm) : "",
    expires_at: k.expires_at ? k.expires_at.split("T")[0] : "",
    metadata: Object.keys(k.metadata).length > 0 ? JSON.stringify(k.metadata) : "",
  };
}

// ---------------------------------------------------------------------------
// Budget progress bar
// ---------------------------------------------------------------------------
function BudgetBar({ spend, max }: { spend: number; max: number | null }) {
  if (max == null) {
    return <span className="text-sm">{formatCurrency(spend)} / ∞</span>;
  }
  const pct = Math.min((spend / max) * 100, 100);
  const variant =
    pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-amber-500" : "bg-primary-500";

  return (
    <div className="space-y-1">
      <div className="text-sm">
        {formatCurrency(spend)} / {formatCurrency(max)}
      </div>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-200 dark:bg-surface-700">
        <div className={`h-full rounded-full ${variant}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Key status helpers
// ---------------------------------------------------------------------------
function keyStatus(k: VirtualKey): "active" | "expired" | "revoked" {
  if (!k.is_active) return "revoked";
  if (k.expires_at && new Date(k.expires_at) < new Date()) return "expired";
  return "active";
}

const statusVariant = {
  active: "success" as const,
  expired: "warning" as const,
  revoked: "danger" as const,
};

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------
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
  { key: "user_id", header: "User", sortable: true, render: (k: VirtualKey) => k.user_id ?? "—" },
  { key: "team_id", header: "Team", sortable: true, render: (k: VirtualKey) => k.team_id ?? "—" },
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
    key: "spend",
    header: "Budget",
    sortable: true,
    render: (k: VirtualKey) => <BudgetBar spend={k.spend} max={k.max_budget} />,
  },
  {
    key: "rate_limit_rpm",
    header: "RPM",
    sortable: true,
    render: (k: VirtualKey) => k.rate_limit_rpm ?? "—",
  },
  {
    key: "rate_limit_tpm",
    header: "TPM",
    sortable: true,
    render: (k: VirtualKey) => k.rate_limit_tpm ?? "—",
  },
  {
    key: "expires_at",
    header: "Expires",
    sortable: true,
    render: (k: VirtualKey) => (k.expires_at ? formatDate(k.expires_at) : "Never"),
  },
  {
    key: "is_active",
    header: "Status",
    render: (k: VirtualKey) => {
      const s = keyStatus(k);
      return <Badge variant={statusVariant[s]}>{s}</Badge>;
    },
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function Keys() {
  const { data: keys = [], isLoading } = useKeys();
  const { data: models = [] } = useModels();
  const { data: teams = [] } = useTeams();
  const { data: users = [] } = useUsers();
  const generateKey = useGenerateKey();
  const updateKey = useUpdateKey();
  const deleteKey = useDeleteKey();
  const rotateKey = useRotateKey();

  // Modal state
  const [showGenerate, setShowGenerate] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [showRotate, setShowRotate] = useState(false);
  const [showCopyKey, setShowCopyKey] = useState(false);

  // Form state
  const [form, setForm] = useState<KeyFormState>(EMPTY_FORM);
  const [editKeyId, setEditKeyId] = useState<string>("");
  const [deleteTarget, setDeleteTarget] = useState<VirtualKey | null>(null);
  const [rotateTarget, setRotateTarget] = useState<VirtualKey | null>(null);
  const [gracePeriod, setGracePeriod] = useState("0");
  const [generatedPlaintext, setGeneratedPlaintext] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState(false);

  // ---- helpers ----
  const updateField = useCallback(
    (key: keyof KeyFormState, value: string) => setForm((f) => ({ ...f, [key]: value })),
    [],
  );

  const optInt = (v: string) => (v.trim() ? parseInt(v, 10) : undefined);
  const optFloat = (v: string) => (v.trim() ? parseFloat(v) : undefined);

  const parseModels = (v: string): string[] =>
    v
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

  const parseMetadata = (v: string): Record<string, unknown> | undefined => {
    if (!v.trim()) return undefined;
    try {
      return JSON.parse(v) as Record<string, unknown>;
    } catch {
      return undefined;
    }
  };

  // ---- generate key ----
  const handleGenerate = async () => {
    setErrors({});
    const body: KeyGenerateRequest = {};

    if (form.user_id.trim()) body.user_id = form.user_id.trim();
    if (form.team_id.trim()) body.team_id = form.team_id.trim();
    const models = parseModels(form.models);
    if (models.length > 0) body.models = models;
    const budget = optFloat(form.max_budget);
    if (budget !== undefined) body.max_budget = budget;
    const rpm = optInt(form.rate_limit_rpm);
    if (rpm !== undefined) body.rate_limit_rpm = rpm;
    const tpm = optInt(form.rate_limit_tpm);
    if (tpm !== undefined) body.rate_limit_tpm = tpm;
    if (form.expires_at.trim()) body.expires_at = new Date(form.expires_at).toISOString();
    const meta = parseMetadata(form.metadata);
    if (meta) body.metadata = meta;

    try {
      const resp = await generateKey.mutateAsync(body);
      setGeneratedPlaintext(resp.key);
      setShowGenerate(false);
      setForm(EMPTY_FORM);
      setShowCopyKey(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Generation failed";
      setErrors({ submit: msg });
    }
  };

  // ---- edit key ----
  const openEdit = (k: VirtualKey) => {
    setEditKeyId(k.id);
    setForm(formFromKey(k));
    setErrors({});
    setShowEdit(true);
  };

  const handleUpdate = async () => {
    setErrors({});
    try {
      const body: KeyUpdateRequest = { key_id: editKeyId };
      const models = parseModels(form.models);
      if (models.length > 0) body.models = models;
      const budget = optFloat(form.max_budget);
      if (budget !== undefined) body.max_budget = budget;
      const rpm = optInt(form.rate_limit_rpm);
      if (rpm !== undefined) body.rate_limit_rpm = rpm;
      const tpm = optInt(form.rate_limit_tpm);
      if (tpm !== undefined) body.rate_limit_tpm = tpm;
      if (form.expires_at.trim()) body.expires_at = new Date(form.expires_at).toISOString();
      const meta = parseMetadata(form.metadata);
      if (meta) body.metadata = meta;

      await updateKey.mutateAsync(body);
      setShowEdit(false);
      setForm(EMPTY_FORM);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Update failed";
      setErrors({ submit: msg });
    }
  };

  // ---- delete key ----
  const openDelete = (k: VirtualKey) => {
    setDeleteTarget(k);
    setShowDelete(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteKey.mutateAsync(deleteTarget.id);
      setShowDelete(false);
      setDeleteTarget(null);
    } catch {
      // ignore — mutation error surfaces in UI
    }
  };

  // ---- rotate key ----
  const openRotate = (k: VirtualKey) => {
    setRotateTarget(k);
    setGracePeriod("0");
    setShowRotate(true);
  };

  const handleRotate = async () => {
    if (!rotateTarget) return;
    try {
      const resp = await rotateKey.mutateAsync({
        key_id: rotateTarget.id,
        grace_period_seconds: parseInt(gracePeriod, 10) || 0,
      });
      setGeneratedPlaintext(resp.new_key.key);
      setShowRotate(false);
      setRotateTarget(null);
      setShowCopyKey(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Rotation failed";
      setErrors({ submit: msg });
    }
  };

  // ---- copy to clipboard ----
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(generatedPlaintext);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback — select text in the input
    }
  };

  // ---- action column ----
  const actionColumn: Column<VirtualKey> = {
    key: "_actions",
    header: "Actions",
    render: (k: VirtualKey) => (
      <div className="flex items-center gap-1">
        <button
          className="rounded p-1 hover:bg-surface-100 dark:hover:bg-surface-700"
          title="Edit"
          onClick={(e) => {
            e.stopPropagation();
            openEdit(k);
          }}
        >
          <Pencil className="h-4 w-4 text-surface-500" />
        </button>
        <button
          className="rounded p-1 hover:bg-surface-100 dark:hover:bg-surface-700"
          title="Rotate"
          onClick={(e) => {
            e.stopPropagation();
            openRotate(k);
          }}
        >
          <RefreshCw className="h-4 w-4 text-surface-500" />
        </button>
        <button
          className="rounded p-1 hover:bg-red-50 dark:hover:bg-red-900/20"
          title="Delete"
          onClick={(e) => {
            e.stopPropagation();
            openDelete(k);
          }}
        >
          <Trash2 className="h-4 w-4 text-red-500" />
        </button>
      </div>
    ),
  };

  // Render the form fields (shared between generate and edit modals)
  const selectCls =
    "w-full rounded-lg border border-surface-300 bg-white px-3 py-2 text-sm dark:border-surface-600 dark:bg-surface-800 dark:text-surface-100 focus:outline-none focus:ring-1 focus:ring-primary-500";

  const renderFormFields = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        {/* User dropdown */}
        <div className="space-y-1">
          <label htmlFor="key-user-id" className="block text-xs font-medium text-surface-600 dark:text-surface-400">
            User ID
          </label>
          <select
            id="key-user-id"
            value={form.user_id}
            onChange={(e) => updateField("user_id", e.target.value)}
            className={selectCls}
          >
            <option value="">None (optional)</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.email ?? u.id}
              </option>
            ))}
          </select>
        </div>
        {/* Team dropdown */}
        <div className="space-y-1">
          <label htmlFor="key-team-id" className="block text-xs font-medium text-surface-600 dark:text-surface-400">
            Team ID
          </label>
          <select
            id="key-team-id"
            value={form.team_id}
            onChange={(e) => updateField("team_id", e.target.value)}
            className={selectCls}
          >
            <option value="">None (optional)</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.team_alias}
              </option>
            ))}
          </select>
        </div>
      </div>
      {/* Models multi-select (checkboxes) */}
      <div className="space-y-1">
        <label htmlFor="key-allowed-models" className="block text-xs font-medium text-surface-600 dark:text-surface-400">
          Allowed Models
        </label>
        {models.length > 0 ? (
          <div className="flex flex-wrap gap-2 rounded-lg border border-surface-200 dark:border-surface-700 p-3 bg-surface-50 dark:bg-surface-900">
            {models.map((m) => {
              const selected = form.models
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
                .includes(m.model_name);
              return (
                <label
                  key={m.model_name}
                  className={`inline-flex items-center gap-1.5 cursor-pointer rounded-md px-2 py-1 text-xs border ${
                    selected
                      ? "bg-primary-50 dark:bg-primary-900/30 border-primary-300 dark:border-primary-600 text-primary-700 dark:text-primary-300"
                      : "bg-white dark:bg-surface-800 border-surface-200 dark:border-surface-600 text-surface-600 dark:text-surface-400"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => {
                      const current = form.models
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean);
                      const next = selected
                        ? current.filter((name) => name !== m.model_name)
                        : [...current, m.model_name];
                      updateField("models", next.join(", "));
                    }}
                    className="sr-only"
                  />
                  {m.model_name}
                </label>
              );
            })}
          </div>
        ) : (
          <Input
            id="key-allowed-models"
            placeholder="e.g. gpt-4o, claude-sonnet-4-20250514 (comma-separated, empty = all)"
            value={form.models}
            onChange={(e) => updateField("models", e.target.value)}
          />
        )}
        <p className="text-xs text-surface-400 mt-1">
          {form.models ? form.models : "All models (no restriction)"}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="Budget Limit ($)"
          type="number"
          placeholder="100"
          value={form.max_budget}
          onChange={(e) => updateField("max_budget", e.target.value)}
        />
        <Input
          label="Expiration"
          type="date"
          value={form.expires_at}
          onChange={(e) => updateField("expires_at", e.target.value)}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="RPM Limit"
          type="number"
          placeholder="100"
          value={form.rate_limit_rpm}
          onChange={(e) => updateField("rate_limit_rpm", e.target.value)}
        />
        <Input
          label="TPM Limit"
          type="number"
          placeholder="50000"
          value={form.rate_limit_tpm}
          onChange={(e) => updateField("rate_limit_tpm", e.target.value)}
        />
      </div>
      <Input
        label="Metadata (JSON)"
        placeholder='{"env": "production"}'
        value={form.metadata}
        onChange={(e) => updateField("metadata", e.target.value)}
      />
      {errors.submit && (
        <div className="flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {errors.submit}
        </div>
      )}
    </div>
  );

  return (
    <PageContainer
      title="Virtual Keys"
      description="Manage API keys for teams and users"
      actions={
        <Button
          icon={<Plus className="h-4 w-4" />}
          onClick={() => {
            setForm(EMPTY_FORM);
            setErrors({});
            setShowGenerate(true);
          }}
        >
          Generate Key
        </Button>
      }
    >
      <div className="rounded-xl border border-surface-200 bg-white dark:border-surface-700 dark:bg-surface-800">
        <Table
          columns={[...columns, actionColumn]}
          data={keys}
          keyFn={(item) => item.id}
          loading={isLoading}
          emptyMessage="No keys generated yet"
        />
      </div>

      {/* Generate Key Modal */}
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
            <Button
              onClick={handleGenerate}
              disabled={generateKey.isPending}
              icon={
                generateKey.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Key className="h-4 w-4" />
                )
              }
            >
              Generate
            </Button>
          </>
        }
      >
        {renderFormFields()}
      </Modal>

      {/* Edit Key Modal */}
      <Modal
        open={showEdit}
        onClose={() => setShowEdit(false)}
        title="Edit Key Settings"
        size="lg"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowEdit(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleUpdate}
              disabled={updateKey.isPending}
              icon={
                updateKey.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : undefined
              }
            >
              Save Changes
            </Button>
          </>
        }
      >
        {renderFormFields()}
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        open={showDelete}
        onClose={() => setShowDelete(false)}
        title="Deactivate Key"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={deleteKey.isPending}
              icon={
                deleteKey.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : undefined
              }
            >
              Deactivate
            </Button>
          </>
        }
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-6 w-6 shrink-0 text-amber-500" />
          <div>
            <p className="font-medium">Are you sure you want to deactivate this key?</p>
            {deleteTarget && (
              <p className="mt-1 text-sm text-surface-500">
                Key <code className="text-xs">{deleteTarget.key_prefix}</code> will be deactivated.
                It will no longer accept requests.
              </p>
            )}
          </div>
        </div>
      </Modal>

      {/* Rotate Key Modal */}
      <Modal
        open={showRotate}
        onClose={() => setShowRotate(false)}
        title="Rotate Key"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowRotate(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleRotate}
              disabled={rotateKey.isPending}
              icon={
                rotateKey.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )
              }
            >
              Rotate
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-surface-600 dark:text-surface-400">
            This will generate a new key and deactivate the old one.
            {rotateTarget && (
              <span>
                {" "}
                Key <code className="text-xs">{rotateTarget.key_prefix}</code> will be replaced.
              </span>
            )}
          </p>
          <Input
            label="Grace Period (seconds)"
            type="number"
            placeholder="0 (immediate deactivation)"
            value={gracePeriod}
            onChange={(e) => setGracePeriod(e.target.value)}
          />
          <p className="text-xs text-surface-500">
            If set to &gt; 0, the old key will remain active for the specified number of seconds
            before being deactivated. This allows a smooth transition.
          </p>
          {errors.submit && (
            <div className="flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {errors.submit}
            </div>
          )}
        </div>
      </Modal>

      {/* Copy Key Modal — shown once after generation or rotation */}
      <Modal
        open={showCopyKey}
        onClose={() => {
          setShowCopyKey(false);
          setGeneratedPlaintext("");
          setCopied(false);
        }}
        title="Your New API Key"
        footer={
          <Button
            onClick={() => {
              setShowCopyKey(false);
              setGeneratedPlaintext("");
              setCopied(false);
            }}
          >
            Done
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-start gap-3">
            <CheckCircle className="h-5 w-5 shrink-0 text-green-500" />
            <p className="text-sm text-surface-600 dark:text-surface-400">
              Copy this key now — <strong>you will not be able to see it again</strong>.
            </p>
          </div>

          <div className="flex items-center gap-2 rounded-lg border border-surface-200 bg-surface-50 p-3 dark:border-surface-700 dark:bg-surface-900">
            <code className="flex-1 break-all text-sm font-mono">{generatedPlaintext}</code>
            <button
              onClick={handleCopy}
              className="rounded-lg p-2 hover:bg-surface-200 dark:hover:bg-surface-700"
              title="Copy to clipboard"
            >
              {copied ? (
                <CheckCircle className="h-5 w-5 text-green-500" />
              ) : (
                <ClipboardCopy className="h-5 w-5 text-surface-500" />
              )}
            </button>
          </div>

          {copied && (
            <p className="text-xs text-green-600 dark:text-green-400">Copied to clipboard!</p>
          )}
        </div>
      </Modal>
    </PageContainer>
  );
}
