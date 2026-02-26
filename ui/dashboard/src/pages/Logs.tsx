import { RefreshCw, Search } from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";
import { LoadingSpinner } from "../components/common/LoadingSpinner";
import { Table } from "../components/common/Table";
import { PageContainer } from "../components/layout/PageContainer";
import { useAuditLogs } from "../api/hooks/useSettings";
import { formatDateTime } from "../utils/formatters";

import type { Column } from "../components/common/Table";
import type { AuditEntry } from "../api/types";

const ACTION_VARIANTS: Record<string, "success" | "danger" | "warning" | "info" | "neutral"> = {
  create: "success",
  delete: "danger",
  update: "warning",
  read: "info",
  login: "info",
  logout: "neutral",
};

function getVariant(action: string): "success" | "danger" | "warning" | "info" | "neutral" {
  const lower = action.toLowerCase();
  for (const [k, v] of Object.entries(ACTION_VARIANTS)) {
    if (lower.includes(k)) return v;
  }
  return "neutral";
}

export function Logs() {
  const [page, setPage] = useState(1);
  const [actorFilter, setActorFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const PER_PAGE = 25;

  const { data, isLoading, error, refetch, isFetching } = useAuditLogs({
    page,
    per_page: PER_PAGE,
    ...(actorFilter ? { actor: actorFilter } : {}),
    ...(actionFilter ? { action: actionFilter } : {}),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.ceil(total / PER_PAGE);

  const columns: Column<AuditEntry>[] = [
    {
      key: "timestamp",
      header: "Time",
      sortable: true,
      render: (e: AuditEntry) => (
        <span className="whitespace-nowrap text-gray-500">{formatDateTime(e.timestamp)}</span>
      ),
    },
    {
      key: "actor",
      header: "Actor",
      render: (e: AuditEntry) => (
        <span className="font-mono text-xs bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">
          {e.actor}
        </span>
      ),
    },
    {
      key: "action",
      header: "Action",
      sortable: true,
      render: (e: AuditEntry) => (
        <Badge variant={getVariant(e.action)}>
          {e.action}
        </Badge>
      ),
    },
    {
      key: "target",
      header: "Target",
      render: (e: AuditEntry) => (
        <span className="font-mono text-xs text-gray-600 dark:text-gray-400">{e.target}</span>
      ),
    },
    {
      key: "details",
      header: "Details",
      render: (e: AuditEntry) => {
        const keys = Object.keys(e.details);
        if (keys.length === 0) return null;
        return (
          <span className="text-xs text-gray-500">
            {keys
              .slice(0, 2)
              .map((k) => `${k}=${JSON.stringify(e.details[k])}`)
              .join(", ")}
            {keys.length > 2 ? "…" : ""}
          </span>
        );
      },
    },
  ];

  return (
    <PageContainer
      title="Audit Logs"
      description="Track all admin and API actions"
      actions={
        <Button variant="secondary" onClick={() => refetch()} loading={isFetching}>
          <RefreshCw className="h-4 w-4 mr-1" />Refresh
        </Button>
      }
    >
      <div className="mb-4 flex gap-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="Filter by actor…"
            className="pl-8 pr-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 w-48"
            value={actorFilter}
            onChange={(e) => { setActorFilter(e.target.value); setPage(1); }}
          />
        </div>
        <input
          type="text"
          placeholder="Filter by action…"
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 w-48"
          value={actionFilter}
          onChange={(e) => { setActionFilter(e.target.value); setPage(1); }}
        />
      </div>

      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <p className="text-red-500">Failed to load audit logs.</p>
      ) : items.length === 0 ? (
        <EmptyState
          title="No audit logs"
          description={actorFilter || actionFilter ? "Try clearing your filters." : "Admin actions will appear here."}
        />
      ) : (
        <>
          <Table data={items} columns={columns} keyFn={(e) => e.id} />
          {pages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500">
                Page {page} of {pages} ({total} total)
              </p>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
                <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}
    </PageContainer>
  );
}
