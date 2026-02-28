import { Key, Pencil, Plus, RefreshCw, Save, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { Card } from "../components/common/Card";
import { EmptyState } from "../components/common/EmptyState";
import { Input } from "../components/common/Input";
import { LoadingSpinner } from "../components/common/LoadingSpinner";
import { Notification } from "../components/common/Notification";
import { PageContainer } from "../components/layout/PageContainer";
import {
  useConfig,
  useReloadConfig,
  useSSOProviders,
  useUpdateConfig,
  useAuditLogs,
} from "../api/hooks/useSettings";
import { formatDateTime } from "../utils/formatters";

import type { ConfigUpdateRequest } from "../api/types";

// ─── Audit Logs Section ───────────────────────────────────────────────────────

function AuditLogsSection() {
  const { data, isLoading } = useAuditLogs({ per_page: 50 });
  const items = data?.items ?? [];

  if (isLoading) return <LoadingSpinner />;
  if (items.length === 0)
    return (
      <EmptyState
        title="No audit logs"
        description="Admin actions will appear here."
      />
    );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 dark:border-gray-700">
            {["Time", "Actor", "Action", "Target"].map((h) => (
              <th
                key={h}
                className="text-left py-2 px-3 text-gray-500 font-medium"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((entry) => (
            <tr
              key={entry.id}
              className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50"
            >
              <td className="py-2 px-3 text-gray-500 whitespace-nowrap">
                {formatDateTime(entry.timestamp)}
              </td>
              <td className="py-2 px-3 font-mono text-xs">{entry.actor}</td>
              <td className="py-2 px-3">
                <Badge variant="info">{entry.action}</Badge>
              </td>
              <td className="py-2 px-3 font-mono text-xs text-gray-500">
                {entry.target}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Shared styles ────────────────────────────────────────────────────────────

const selectCls =
  "w-full rounded-lg border border-surface-300 bg-white px-3 py-2 text-sm dark:border-surface-600 dark:bg-surface-800 dark:text-surface-100 focus:outline-none focus:ring-1 focus:ring-primary-500";
const checkboxLabelCls =
  "flex items-center gap-2 text-sm text-surface-700 dark:text-surface-300 py-2";
const checkboxCls = "h-4 w-4 rounded border-surface-300";
const sectionHeadingCls =
  "text-sm font-semibold text-surface-700 dark:text-surface-300 mb-3";
const tagCls =
  "inline-flex items-center gap-1 rounded-md bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 px-2 py-0.5 text-xs";

// ─── Editable config section ──────────────────────────────────────────────────

const ROUTING_STRATEGIES = [
  "round-robin",
  "weighted-round-robin",
  "latency-based",
  "cost-based",
  "random",
  "least-connections",
];
const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];
const CACHE_TYPES = ["none", "redis", "memory"];

interface GeneralForm {
  log_level: string;
  request_timeout: string;
  max_request_size_mb: string;
  max_response_size_mb: string;
  cors_allow_origins: string[];
  block_robots: boolean;
}

interface RouterForm {
  routing_strategy: string;
  num_retries: string;
  retry_delay: string;
  timeout: string;
  cooldown_time: string;
  allowed_fails: string;
  enable_health_check: boolean;
  health_check_interval: string;
  fallbacks: Record<string, string[]>;
}

interface CacheForm {
  enabled: boolean;
  type: string;
  ttl: string;
}

function ConfigSection() {
  const { data, isLoading, error } = useConfig();
  const reload = useReloadConfig();
  const updateConfig = useUpdateConfig();

  const [editing, setEditing] = useState(false);
  const [notification, setNotification] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const [general, setGeneral] = useState<GeneralForm>({
    log_level: "INFO",
    request_timeout: "600",
    max_request_size_mb: "100",
    max_response_size_mb: "100",
    cors_allow_origins: ["*"],
    block_robots: false,
  });

  const [router, setRouter] = useState<RouterForm>({
    routing_strategy: "round-robin",
    num_retries: "3",
    retry_delay: "1.0",
    timeout: "600",
    cooldown_time: "60",
    allowed_fails: "3",
    enable_health_check: true,
    health_check_interval: "300",
    fallbacks: {},
  });

  const [cache, setCache] = useState<CacheForm>({
    enabled: false,
    type: "none",
    ttl: "3600",
  });

  // CORS tag input
  const [corsInput, setCorsInput] = useState("");
  // Fallback editor
  const [fbModel, setFbModel] = useState("");
  const [fbTargets, setFbTargets] = useState("");

  // Sync form from server data
  const syncFromData = useCallback((d: Record<string, unknown>) => {
    setGeneral({
      log_level: String(d.log_level ?? "INFO"),
      request_timeout: String(d.request_timeout ?? "600"),
      max_request_size_mb: String(d.max_request_size_mb ?? "100"),
      max_response_size_mb: String(d.max_response_size_mb ?? "100"),
      cors_allow_origins: Array.isArray(d.cors_allow_origins)
        ? (d.cors_allow_origins as string[])
        : ["*"],
      block_robots: Boolean(d.block_robots),
    });
    setRouter({
      routing_strategy: String(d.routing_strategy ?? "round-robin"),
      num_retries: String(d.num_retries ?? "3"),
      retry_delay: String(d.retry_delay ?? "1.0"),
      timeout: String(d.timeout ?? "600"),
      cooldown_time: String(d.cooldown_time ?? "60"),
      allowed_fails: String(d.allowed_fails ?? "3"),
      enable_health_check: d.enable_health_check !== false,
      health_check_interval: String(d.health_check_interval ?? "300"),
      fallbacks:
        d.fallbacks && typeof d.fallbacks === "object"
          ? (d.fallbacks as Record<string, string[]>)
          : {},
    });
    setCache({
      enabled: Boolean(d.cache_enabled),
      type: String(d.cache_type ?? "none"),
      ttl: String(d.cache_ttl ?? "3600"),
    });
  }, []);

  useEffect(() => {
    if (data) syncFromData(data);
  }, [data, syncFromData]);

  if (isLoading) return <LoadingSpinner />;
  if (error)
    return (
      <p className="text-red-500 text-sm">Failed to load configuration.</p>
    );
  if (!data) return null;

  // Read-only display items (filter sensitive values)
  const displayEntries = Object.entries(data).filter(
    ([k]) =>
      !k.toLowerCase().includes("key") &&
      !k.toLowerCase().includes("secret") &&
      !k.toLowerCase().includes("password"),
  );

  const handleSave = async () => {
    const payload: ConfigUpdateRequest = {
      general_settings: {
        log_level: general.log_level,
        request_timeout: parseInt(general.request_timeout, 10) || 600,
        max_request_size_mb: parseFloat(general.max_request_size_mb) || 100,
        max_response_size_mb: parseFloat(general.max_response_size_mb) || 100,
        cors_allow_origins: general.cors_allow_origins,
        block_robots: general.block_robots,
      },
      router_settings: {
        routing_strategy: router.routing_strategy,
        num_retries: parseInt(router.num_retries, 10) || 3,
        retry_delay: parseFloat(router.retry_delay) || 1.0,
        timeout: parseInt(router.timeout, 10) || 600,
        cooldown_time: parseInt(router.cooldown_time, 10) || 60,
        allowed_fails: parseInt(router.allowed_fails, 10) || 3,
        enable_health_check: router.enable_health_check,
        health_check_interval:
          parseInt(router.health_check_interval, 10) || 300,
        fallbacks: router.fallbacks,
      },
      cache_settings: {
        enabled: cache.enabled,
        type: cache.type,
        ttl: parseInt(cache.ttl, 10) || 3600,
      },
    };

    try {
      await updateConfig.mutateAsync(payload);
      setNotification({ type: "success", message: "Settings saved and persisted to config file." });
      setEditing(false);
    } catch {
      setNotification({ type: "error", message: "Failed to save settings. Check server logs." });
    }
  };

  const handleCancel = () => {
    if (data) syncFromData(data);
    setEditing(false);
  };

  return (
    <div className="space-y-4">
      {notification && (
        <Notification
          type={notification.type}
          title={notification.type === "success" ? "Success" : "Error"}
          message={notification.message}
          onClose={() => setNotification(null)}
        />
      )}

      {!editing ? (
        <>
          {/* Read-only view */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {displayEntries.slice(0, 14).map(([k, v]) => (
              <div
                key={k}
                className="flex items-start gap-2 bg-gray-50 dark:bg-gray-800 rounded-md p-2"
              >
                <span className="text-xs font-mono text-gray-500 min-w-[140px] flex-shrink-0">
                  {k}
                </span>
                <span className="text-xs font-mono text-gray-800 dark:text-gray-200 truncate">
                  {typeof v === "object" ? JSON.stringify(v) : String(v ?? "—")}
                </span>
              </div>
            ))}
          </div>
          <div className="flex gap-2 pt-2">
            <Button variant="primary" size="sm" onClick={() => setEditing(true)}>
              <Pencil className="h-3 w-3 mr-1" />
              Edit Settings
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => reload.mutate()}
              loading={reload.isPending}
            >
              <RefreshCw className="h-3 w-3 mr-1" />
              Reload from file
            </Button>
          </div>
        </>
      ) : (
        <>
          {/* Edit form */}
          <div className="space-y-6">
            {/* General Settings */}
            <div>
              <h4 className={sectionHeadingCls}>General Settings</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="block text-xs font-medium text-surface-600 dark:text-surface-400">
                    Log Level
                  </label>
                  <select
                    value={general.log_level}
                    onChange={(e) =>
                      setGeneral({ ...general, log_level: e.target.value })
                    }
                    className={selectCls}
                  >
                    {LOG_LEVELS.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                </div>
                <Input
                  label="Request Timeout (s)"
                  type="number"
                  value={general.request_timeout}
                  onChange={(e) =>
                    setGeneral({ ...general, request_timeout: e.target.value })
                  }
                />
                <Input
                  label="Max Request Size (MB)"
                  type="number"
                  value={general.max_request_size_mb}
                  onChange={(e) =>
                    setGeneral({
                      ...general,
                      max_request_size_mb: e.target.value,
                    })
                  }
                />
                <Input
                  label="Max Response Size (MB)"
                  type="number"
                  value={general.max_response_size_mb}
                  onChange={(e) =>
                    setGeneral({
                      ...general,
                      max_response_size_mb: e.target.value,
                    })
                  }
                />
                <label className={checkboxLabelCls}>
                  <input
                    type="checkbox"
                    checked={general.block_robots}
                    onChange={(e) =>
                      setGeneral({ ...general, block_robots: e.target.checked })
                    }
                    className={checkboxCls}
                  />
                  Block Robots
                </label>
              </div>

              {/* CORS Origins */}
              <div className="mt-4">
                <label className="block text-xs font-medium text-surface-600 dark:text-surface-400 mb-2">
                  CORS Allowed Origins
                </label>
                <div className="flex flex-wrap gap-1 mb-2">
                  {general.cors_allow_origins.map((origin) => (
                    <span key={origin} className={tagCls}>
                      {origin}
                      <button
                        onClick={() =>
                          setGeneral({
                            ...general,
                            cors_allow_origins: general.cors_allow_origins.filter(
                              (o) => o !== origin,
                            ),
                          })
                        }
                        className="hover:text-red-500"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    className={selectCls}
                    placeholder="https://example.com or *"
                    value={corsInput}
                    onChange={(e) => setCorsInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        const val = corsInput.trim();
                        if (val && !general.cors_allow_origins.includes(val)) {
                          setGeneral({
                            ...general,
                            cors_allow_origins: [...general.cors_allow_origins, val],
                          });
                        }
                        setCorsInput("");
                      }
                    }}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      const val = corsInput.trim();
                      if (val && !general.cors_allow_origins.includes(val)) {
                        setGeneral({
                          ...general,
                          cors_allow_origins: [...general.cors_allow_origins, val],
                        });
                      }
                      setCorsInput("");
                    }}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            </div>

            {/* Router Settings */}
            <div>
              <h4 className={sectionHeadingCls}>Router Settings</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="block text-xs font-medium text-surface-600 dark:text-surface-400">
                    Routing Strategy
                  </label>
                  <select
                    value={router.routing_strategy}
                    onChange={(e) =>
                      setRouter({
                        ...router,
                        routing_strategy: e.target.value,
                      })
                    }
                    className={selectCls}
                  >
                    {ROUTING_STRATEGIES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>
                <Input
                  label="Num Retries"
                  type="number"
                  value={router.num_retries}
                  onChange={(e) =>
                    setRouter({ ...router, num_retries: e.target.value })
                  }
                />
                <Input
                  label="Retry Delay (s)"
                  type="number"
                  step="0.1"
                  value={router.retry_delay}
                  onChange={(e) =>
                    setRouter({ ...router, retry_delay: e.target.value })
                  }
                />
                <Input
                  label="Timeout (s)"
                  type="number"
                  value={router.timeout}
                  onChange={(e) =>
                    setRouter({ ...router, timeout: e.target.value })
                  }
                />
                <Input
                  label="Cooldown Time (s)"
                  type="number"
                  value={router.cooldown_time}
                  onChange={(e) =>
                    setRouter({ ...router, cooldown_time: e.target.value })
                  }
                />
                <Input
                  label="Allowed Fails"
                  type="number"
                  value={router.allowed_fails}
                  onChange={(e) =>
                    setRouter({ ...router, allowed_fails: e.target.value })
                  }
                />
                <Input
                  label="Health Check Interval (s)"
                  type="number"
                  value={router.health_check_interval}
                  onChange={(e) =>
                    setRouter({
                      ...router,
                      health_check_interval: e.target.value,
                    })
                  }
                />
                <label className={checkboxLabelCls}>
                  <input
                    type="checkbox"
                    checked={router.enable_health_check}
                    onChange={(e) =>
                      setRouter({
                        ...router,
                        enable_health_check: e.target.checked,
                      })
                    }
                    className={checkboxCls}
                  />
                  Enable Health Check
                </label>
              </div>

              {/* Fallbacks */}
              <div className="mt-4">
                <label className="block text-xs font-medium text-surface-600 dark:text-surface-400 mb-2">
                  Model Fallbacks
                </label>
                {Object.entries(router.fallbacks).length > 0 && (
                  <div className="space-y-1 mb-2">
                    {Object.entries(router.fallbacks).map(([model, targets]) => (
                      <div
                        key={model}
                        className="flex items-center gap-2 rounded-md bg-surface-50 dark:bg-surface-800 p-2 text-xs"
                      >
                        <span className="font-mono font-medium">{model}</span>
                        <span className="text-surface-400">→</span>
                        <span className="font-mono text-surface-600 dark:text-surface-400">
                          {targets.join(", ")}
                        </span>
                        <button
                          onClick={() => {
                            const copy = { ...router.fallbacks };
                            delete copy[model];
                            setRouter({ ...router, fallbacks: copy });
                          }}
                          className="ml-auto hover:text-red-500"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex gap-2">
                  <input
                    className={selectCls}
                    placeholder="Source model (e.g. gpt-4o)"
                    value={fbModel}
                    onChange={(e) => setFbModel(e.target.value)}
                  />
                  <input
                    className={selectCls}
                    placeholder="Fallback models (comma-separated)"
                    value={fbTargets}
                    onChange={(e) => setFbTargets(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        const model = fbModel.trim();
                        const targets = fbTargets
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean);
                        if (model && targets.length > 0) {
                          setRouter({
                            ...router,
                            fallbacks: { ...router.fallbacks, [model]: targets },
                          });
                        }
                        setFbModel("");
                        setFbTargets("");
                      }
                    }}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      const model = fbModel.trim();
                      const targets = fbTargets
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean);
                      if (model && targets.length > 0) {
                        setRouter({
                          ...router,
                          fallbacks: { ...router.fallbacks, [model]: targets },
                        });
                      }
                      setFbModel("");
                      setFbTargets("");
                    }}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            </div>

            {/* Cache Settings */}
            <div>
              <h4 className={sectionHeadingCls}>Cache Settings</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className={checkboxLabelCls}>
                  <input
                    type="checkbox"
                    checked={cache.enabled}
                    onChange={(e) =>
                      setCache({ ...cache, enabled: e.target.checked })
                    }
                    className={checkboxCls}
                  />
                  Enable Response Caching
                </label>
                <div className="space-y-1">
                  <label className="block text-xs font-medium text-surface-600 dark:text-surface-400">
                    Cache Type
                  </label>
                  <select
                    value={cache.type}
                    onChange={(e) =>
                      setCache({ ...cache, type: e.target.value })
                    }
                    className={selectCls}
                    disabled={!cache.enabled}
                  >
                    {CACHE_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <Input
                  label="Cache TTL (s)"
                  type="number"
                  value={cache.ttl}
                  onChange={(e) =>
                    setCache({ ...cache, ttl: e.target.value })
                  }
                  disabled={!cache.enabled}
                />
              </div>
            </div>
          </div>

          <div className="flex gap-2 pt-3 border-t border-surface-200 dark:border-surface-700">
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              loading={updateConfig.isPending}
            >
              <Save className="h-3 w-3 mr-1" />
              Save Settings
            </Button>
            <Button variant="secondary" size="sm" onClick={handleCancel}>
              <X className="h-3 w-3 mr-1" />
              Cancel
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

// ─── SSO Providers Section ────────────────────────────────────────────────────

function SSOSection() {
  const { data, isLoading } = useSSOProviders();
  const providers = data ?? [];

  if (isLoading) return <LoadingSpinner />;

  return (
    <div>
      {providers.length === 0 ? (
        <EmptyState
          title="No SSO providers"
          description="SSO providers configured in routerbot_config.yaml will appear here."
        />
      ) : (
        <div className="space-y-2">
          {providers.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg"
            >
              <div className="flex items-center gap-2">
                <Key className="h-4 w-4 text-gray-400" />
                <span className="font-medium text-sm">{p.name}</span>
                <Badge variant="neutral">{p.type}</Badge>
              </div>
              <Badge variant={p.enabled ? "success" : "neutral"}>
                {p.enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function Settings() {
  return (
    <PageContainer
      title="Settings"
      description="System configuration and administration"
    >
      <div className="space-y-6">
        <Card title="Configuration" description="View and edit general, router, and cache settings">
          <ConfigSection />
        </Card>

        <Card title="SSO Providers">
          <SSOSection />
        </Card>

        <Card title="Audit Log">
          <AuditLogsSection />
        </Card>
      </div>
    </PageContainer>
  );
}
