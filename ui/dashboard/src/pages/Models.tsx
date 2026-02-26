import { AlertTriangle, CheckCircle, Loader2, Pencil, Plus, Trash2, Wifi } from "lucide-react";
import { useCallback, useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { Input } from "../components/common/Input";
import { Modal } from "../components/common/Modal";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import { useAddModel, useDeleteModel, useModels, useTestConnection, useUpdateModel } from "../api/hooks/useModels";

import type { Column } from "../components/common/Table";
import type { Model, ModelNewRequest, ModelUpdateRequest } from "../api/types";

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------
interface ModelFormState {
  model_name: string;
  model: string;
  api_key: string;
  api_base: string;
  api_version: string;
  max_tokens: string;
  rpm: string;
  tpm: string;
  timeout: string;
  input_cost_per_token: string;
  output_cost_per_token: string;
  supports_streaming: boolean;
  supports_function_calling: boolean;
  supports_vision: boolean;
}

const EMPTY_FORM: ModelFormState = {
  model_name: "",
  model: "",
  api_key: "",
  api_base: "",
  api_version: "",
  max_tokens: "",
  rpm: "",
  tpm: "",
  timeout: "",
  input_cost_per_token: "",
  output_cost_per_token: "",
  supports_streaming: true,
  supports_function_calling: false,
  supports_vision: false,
};

function formFromModel(m: Model): ModelFormState {
  return {
    model_name: m.model_name,
    model: m.model,
    api_key: "",
    api_base: m.api_base ?? "",
    api_version: "",
    max_tokens: m.max_tokens ? String(m.max_tokens) : "",
    rpm: m.rpm ? String(m.rpm) : "",
    tpm: m.tpm ? String(m.tpm) : "",
    timeout: m.timeout ? String(m.timeout) : "",
    input_cost_per_token: m.model_info?.input_cost_per_token ? String(m.model_info.input_cost_per_token) : "",
    output_cost_per_token: m.model_info?.output_cost_per_token ? String(m.model_info.output_cost_per_token) : "",
    supports_streaming: m.model_info?.supports_streaming ?? true,
    supports_function_calling: m.model_info?.supports_function_calling ?? false,
    supports_vision: m.model_info?.supports_vision ?? false,
  };
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------
const columns: Column<Model>[] = [
  { key: "model_name", header: "Model Name", sortable: true },
  { key: "provider", header: "Provider", sortable: true },
  {
    key: "model",
    header: "Provider Model",
    sortable: true,
    render: (m: Model) => (
      <span className="text-xs text-surface-500 dark:text-surface-400 font-mono">{m.model}</span>
    ),
  },
  {
    key: "api_key_set",
    header: "API Key",
    render: (m: Model) =>
      m.api_key_set ? (
        <Badge variant="success">Set</Badge>
      ) : (
        <Badge variant="warning">Not set</Badge>
      ),
  },
  { key: "rpm", header: "RPM", sortable: true, render: (m: Model) => m.rpm ?? "—" },
  { key: "tpm", header: "TPM", sortable: true, render: (m: Model) => m.tpm ?? "—" },
  { key: "max_tokens", header: "Max Tokens", sortable: true, render: (m: Model) => m.max_tokens ?? "—" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function Models() {
  const { data: models = [], isLoading } = useModels();
  const addModel = useAddModel();
  const updateModel = useUpdateModel();
  const deleteModel = useDeleteModel();
  const testConnection = useTestConnection();

  const [showAdd, setShowAdd] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [form, setForm] = useState<ModelFormState>(EMPTY_FORM);
  const [deleteTarget, setDeleteTarget] = useState<string>("");
  const [testResult, setTestResult] = useState<{ status: string; message: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // ---- helpers ----
  const updateField = useCallback(
    (key: keyof ModelFormState, value: string | boolean) =>
      setForm((f) => ({ ...f, [key]: value })),
    [],
  );

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!form.model_name.trim()) e.model_name = "Required";
    if (!form.model.trim()) e.model = "Required (e.g. openai/gpt-4o)";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const optInt = (v: string) => (v.trim() ? parseInt(v, 10) : undefined);
  const optFloat = (v: string) => (v.trim() ? parseFloat(v) : undefined);

  // ---- add ----
  const handleAdd = async () => {
    if (!validate()) return;
    const body: ModelNewRequest = {
      model_name: form.model_name.trim(),
      model: form.model.trim(),
      ...(form.api_key.trim() && { api_key: form.api_key.trim() }),
      ...(form.api_base.trim() && { api_base: form.api_base.trim() }),
      ...(form.api_version.trim() && { api_version: form.api_version.trim() }),
      ...((v) => v !== undefined && { max_tokens: v })(optInt(form.max_tokens)),
      ...((v) => v !== undefined && { rpm: v })(optInt(form.rpm)),
      ...((v) => v !== undefined && { tpm: v })(optInt(form.tpm)),
      ...((v) => v !== undefined && { timeout: v })(optInt(form.timeout)),
      ...((v) => v !== undefined && { input_cost_per_token: v })(optFloat(form.input_cost_per_token)),
      ...((v) => v !== undefined && { output_cost_per_token: v })(optFloat(form.output_cost_per_token)),
      supports_streaming: form.supports_streaming,
      supports_function_calling: form.supports_function_calling,
      supports_vision: form.supports_vision,
    };
    try {
      await addModel.mutateAsync(body);
      setShowAdd(false);
      setForm(EMPTY_FORM);
      setErrors({});
    } catch { /* mutation error handled by React Query */ }
  };

  // ---- edit ----
  const openEdit = (m: Model) => {
    setForm(formFromModel(m));
    setShowEdit(true);
    setTestResult(null);
  };

  const handleUpdate = async () => {
    const body: ModelUpdateRequest = {
      model_name: form.model_name,
      ...(form.model.trim() && { model: form.model.trim() }),
      ...(form.api_key.trim() && { api_key: form.api_key.trim() }),
      ...(form.api_base.trim() && { api_base: form.api_base.trim() }),
      ...((v) => v !== undefined && { max_tokens: v })(optInt(form.max_tokens)),
      ...((v) => v !== undefined && { rpm: v })(optInt(form.rpm)),
      ...((v) => v !== undefined && { tpm: v })(optInt(form.tpm)),
      ...((v) => v !== undefined && { timeout: v })(optInt(form.timeout)),
      ...((v) => v !== undefined && { input_cost_per_token: v })(optFloat(form.input_cost_per_token)),
      ...((v) => v !== undefined && { output_cost_per_token: v })(optFloat(form.output_cost_per_token)),
      supports_streaming: form.supports_streaming,
      supports_function_calling: form.supports_function_calling,
      supports_vision: form.supports_vision,
    };
    try {
      await updateModel.mutateAsync(body);
      setShowEdit(false);
      setForm(EMPTY_FORM);
    } catch { /* mutation error handled by React Query */ }
  };

  // ---- delete ----
  const confirmDelete = (name: string) => {
    setDeleteTarget(name);
    setShowDelete(true);
  };

  const handleDelete = async () => {
    try {
      await deleteModel.mutateAsync(deleteTarget);
      setShowDelete(false);
      setDeleteTarget("");
    } catch { /* mutation error handled by React Query */ }
  };

  // ---- test connection ----
  const handleTest = async () => {
    setTestResult(null);
    try {
      const res = await testConnection.mutateAsync(form.model_name);
      setTestResult({ status: res.status, message: `${res.message} (${res.latency_ms}ms)` });
    } catch {
      setTestResult({ status: "error", message: "Connection test failed" });
    }
  };

  // ---- action column ----
  const actionColumns: Column<Model>[] = [
    ...columns,
    {
      key: "_actions",
      header: "Actions",
      render: (m: Model) => (
        <div className="flex items-center gap-2">
          <button
            className="rounded p-1 text-surface-500 hover:bg-surface-100 hover:text-primary-600 dark:hover:bg-surface-700"
            title="Edit"
            onClick={(e) => { e.stopPropagation(); openEdit(m); }}
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            className="rounded p-1 text-surface-500 hover:bg-red-50 hover:text-red-600 dark:hover:bg-surface-700"
            title="Delete"
            onClick={(e) => { e.stopPropagation(); confirmDelete(m.model_name); }}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ),
    },
  ];

  // ---- form JSX ----
  const formFields = (
    <div className="space-y-4">
      <Input
        label="Model Name"
        placeholder="e.g. gpt-4o"
        value={form.model_name}
        onChange={(e) => updateField("model_name", e.target.value)}
        error={errors.model_name}
        disabled={showEdit}
      />
      <Input
        label="Provider/Model"
        placeholder="e.g. openai/gpt-4o"
        value={form.model}
        onChange={(e) => updateField("model", e.target.value)}
        error={errors.model}
        hint="Format: provider/model-name"
      />
      <Input
        label="API Key"
        type="password"
        placeholder={showEdit ? "(unchanged)" : "sk-..."}
        value={form.api_key}
        onChange={(e) => updateField("api_key", e.target.value)}
        hint="Leave blank to keep existing key"
      />
      <Input
        label="API Base URL"
        placeholder="https://api.openai.com/v1"
        value={form.api_base}
        onChange={(e) => updateField("api_base", e.target.value)}
      />
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="Max Tokens"
          type="number"
          placeholder="4096"
          value={form.max_tokens}
          onChange={(e) => updateField("max_tokens", e.target.value)}
        />
        <Input
          label="Timeout (s)"
          type="number"
          placeholder="600"
          value={form.timeout}
          onChange={(e) => updateField("timeout", e.target.value)}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="RPM Limit"
          type="number"
          placeholder="500"
          value={form.rpm}
          onChange={(e) => updateField("rpm", e.target.value)}
        />
        <Input
          label="TPM Limit"
          type="number"
          placeholder="80000"
          value={form.tpm}
          onChange={(e) => updateField("tpm", e.target.value)}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="Input Cost ($/token)"
          type="number"
          placeholder="0.00015"
          value={form.input_cost_per_token}
          onChange={(e) => updateField("input_cost_per_token", e.target.value)}
        />
        <Input
          label="Output Cost ($/token)"
          type="number"
          placeholder="0.0006"
          value={form.output_cost_per_token}
          onChange={(e) => updateField("output_cost_per_token", e.target.value)}
        />
      </div>
      <div className="flex flex-wrap gap-4 pt-2">
        <label className="flex items-center gap-2 text-sm text-surface-700 dark:text-surface-300">
          <input
            type="checkbox"
            checked={form.supports_streaming}
            onChange={(e) => updateField("supports_streaming", e.target.checked)}
            className="h-4 w-4 rounded border-surface-300"
          />
          Streaming
        </label>
        <label className="flex items-center gap-2 text-sm text-surface-700 dark:text-surface-300">
          <input
            type="checkbox"
            checked={form.supports_function_calling}
            onChange={(e) => updateField("supports_function_calling", e.target.checked)}
            className="h-4 w-4 rounded border-surface-300"
          />
          Function Calling
        </label>
        <label className="flex items-center gap-2 text-sm text-surface-700 dark:text-surface-300">
          <input
            type="checkbox"
            checked={form.supports_vision}
            onChange={(e) => updateField("supports_vision", e.target.checked)}
            className="h-4 w-4 rounded border-surface-300"
          />
          Vision
        </label>
      </div>
    </div>
  );

  return (
    <PageContainer
      title="Models"
      description="Manage your configured LLM models"
      actions={
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => { setForm(EMPTY_FORM); setErrors({}); setShowAdd(true); }}>
          Add Model
        </Button>
      }
    >
      <div className="rounded-xl border border-surface-200 bg-white dark:border-surface-700 dark:bg-surface-800">
        <Table
          columns={actionColumns}
          data={models}
          keyFn={(item) => item.model_name}
          emptyMessage="No models configured"
          loading={isLoading}
          onRowClick={openEdit}
        />
      </div>

      {/* Add Modal */}
      <Modal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        title="Add Model"
        size="lg"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={handleAdd} disabled={addModel.isPending}>
              {addModel.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Add Model"}
            </Button>
          </>
        }
      >
        {formFields}
      </Modal>

      {/* Edit Modal */}
      <Modal
        open={showEdit}
        onClose={() => { setShowEdit(false); setTestResult(null); }}
        title={`Edit ${form.model_name}`}
        size="lg"
        footer={
          <div className="flex w-full items-center justify-between">
            <Button
              variant="secondary"
              onClick={handleTest}
              disabled={testConnection.isPending}
              icon={testConnection.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wifi className="h-4 w-4" />}
            >
              Test Connection
            </Button>
            <div className="flex gap-3">
              <Button variant="secondary" onClick={() => setShowEdit(false)}>Cancel</Button>
              <Button onClick={handleUpdate} disabled={updateModel.isPending}>
                {updateModel.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save Changes"}
              </Button>
            </div>
          </div>
        }
      >
        {formFields}
        {testResult && (
          <div className={`mt-4 flex items-center gap-2 rounded-lg p-3 text-sm ${
            testResult.status === "success"
              ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
              : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
          }`}>
            {testResult.status === "success" ? <CheckCircle className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
            {testResult.message}
          </div>
        )}
      </Modal>

      {/* Delete Confirmation */}
      <Modal
        open={showDelete}
        onClose={() => setShowDelete(false)}
        title="Delete Model"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowDelete(false)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={deleteModel.isPending}
            >
              {deleteModel.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Delete"}
            </Button>
          </>
        }
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
          <p className="text-sm text-surface-600 dark:text-surface-400">
            Are you sure you want to delete <strong>{deleteTarget}</strong>? This will immediately
            stop routing any new requests to this model.
          </p>
        </div>
      </Modal>
    </PageContainer>
  );
}
