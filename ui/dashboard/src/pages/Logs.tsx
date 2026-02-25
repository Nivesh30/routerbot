import { Table } from "../components/common/Table";
import { Badge } from "../components/common/Badge";
import { PageContainer } from "../components/layout/PageContainer";
import { formatDateTime } from "../utils/formatters";

import type { Column } from "../components/common/Table";

interface LogEntry {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error";
  model: string;
  message: string;
  request_id: string;
}

const levelVariant = {
  info: "info" as const,
  warning: "warning" as const,
  error: "danger" as const,
};

const mockLogs: LogEntry[] = [
  {
    id: "1",
    timestamp: new Date(Date.now() - 5 * 60_000).toISOString(),
    level: "info",
    model: "gpt-4o",
    message: "Chat completion successful",
    request_id: "req-abc123",
  },
  {
    id: "2",
    timestamp: new Date(Date.now() - 12 * 60_000).toISOString(),
    level: "warning",
    model: "claude-sonnet-4-20250514",
    message: "Rate limit approaching (80% RPM)",
    request_id: "req-def456",
  },
  {
    id: "3",
    timestamp: new Date(Date.now() - 25 * 60_000).toISOString(),
    level: "error",
    model: "gemini-2.0-flash",
    message: "Provider returned 503 Service Unavailable",
    request_id: "req-ghi789",
  },
];

const columns: Column<LogEntry>[] = [
  {
    key: "timestamp",
    header: "Time",
    sortable: true,
    render: (l: LogEntry) => (
      <span className="text-xs text-surface-500">{formatDateTime(l.timestamp)}</span>
    ),
  },
  {
    key: "level",
    header: "Level",
    render: (l: LogEntry) => <Badge variant={levelVariant[l.level]}>{l.level}</Badge>,
  },
  { key: "model", header: "Model", sortable: true },
  { key: "message", header: "Message" },
  {
    key: "request_id",
    header: "Request ID",
    render: (l: LogEntry) => (
      <code className="text-xs text-surface-500">{l.request_id}</code>
    ),
  },
];

export function Logs() {
  return (
    <PageContainer title="Logs" description="View request and system logs">
      <div className="rounded-xl border border-surface-200 bg-white dark:border-surface-700 dark:bg-surface-800">
        <Table
          columns={columns}
          data={mockLogs}
          keyFn={(item) => item.id}
          emptyMessage="No logs"
        />
      </div>
    </PageContainer>
  );
}
