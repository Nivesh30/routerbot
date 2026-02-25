import { Plus } from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { Modal } from "../components/common/Modal";
import { Input } from "../components/common/Input";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import { formatLatency, formatNumber } from "../utils/formatters";

import type { Column } from "../components/common/Table";
import type { Model } from "../api/types";

const mockModels: Model[] = [
  {
    id: "1",
    model_name: "gpt-4o",
    provider: "openai",
    status: "healthy",
    request_count: 4520,
    avg_latency_ms: 890,
    rpm: 500,
    tpm: 80000,
  },
  {
    id: "2",
    model_name: "claude-sonnet-4-20250514",
    provider: "anthropic",
    status: "healthy",
    request_count: 3210,
    avg_latency_ms: 1120,
    rpm: 300,
    tpm: 60000,
  },
  {
    id: "3",
    model_name: "gemini-2.0-flash",
    provider: "google",
    status: "degraded",
    request_count: 1890,
    avg_latency_ms: 560,
    rpm: 1000,
    tpm: 100000,
  },
];

const statusVariant = {
  healthy: "success" as const,
  degraded: "warning" as const,
  down: "danger" as const,
};

const columns: Column<Model>[] = [
  { key: "model_name", header: "Model", sortable: true },
  { key: "provider", header: "Provider", sortable: true },
  {
    key: "status",
    header: "Status",
    render: (m: Model) => (
      <Badge variant={statusVariant[m.status]}>{m.status}</Badge>
    ),
  },
  {
    key: "request_count",
    header: "Requests",
    sortable: true,
    render: (m: Model) => formatNumber(m.request_count),
  },
  {
    key: "avg_latency_ms",
    header: "Avg Latency",
    sortable: true,
    render: (m: Model) => formatLatency(m.avg_latency_ms),
  },
  { key: "rpm", header: "RPM", sortable: true },
  { key: "tpm", header: "TPM", sortable: true },
];

export function Models() {
  const [showAdd, setShowAdd] = useState(false);

  return (
    <PageContainer
      title="Models"
      description="Manage your configured LLM models"
      actions={
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => setShowAdd(true)}>
          Add Model
        </Button>
      }
    >
      <div className="rounded-xl border border-surface-200 bg-white dark:border-surface-700 dark:bg-surface-800">
        <Table
          columns={columns}
          data={mockModels}
          keyFn={(item) => item.id}
          emptyMessage="No models configured"
        />
      </div>

      <Modal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        title="Add Model"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowAdd(false)}>
              Cancel
            </Button>
            <Button onClick={() => setShowAdd(false)}>Save</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Model Name" placeholder="e.g. gpt-4o" />
          <Input label="Provider" placeholder="e.g. openai" />
          <Input label="API Base" placeholder="https://api.openai.com/v1" />
          <div className="grid grid-cols-2 gap-4">
            <Input label="RPM Limit" type="number" placeholder="500" />
            <Input label="TPM Limit" type="number" placeholder="80000" />
          </div>
        </div>
      </Modal>
    </PageContainer>
  );
}
