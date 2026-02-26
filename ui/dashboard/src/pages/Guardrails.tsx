import { Shield, ToggleLeft, ToggleRight, Settings as SettingsIcon } from "lucide-react";
import { useState } from "react";

import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { Card } from "../components/common/Card";
import { Modal } from "../components/common/Modal";
import { PageContainer } from "../components/layout/PageContainer";

// Guardrail config is managed locally (config-file-based) so we show
// current config from the backend and allow UI to show/explain each guardrail.

interface GuardrailItem {
  id: string;
  type: string;
  label: string;
  description: string;
  enabled: boolean;
  priority: number;
  config: Record<string, unknown>;
}

const DEFAULT_GUARDRAILS: GuardrailItem[] = [
  {
    id: "secret_detection",
    type: "secret_detection",
    label: "Secret Detection",
    description: "Detect and redact API keys, tokens, and credentials in requests and responses.",
    enabled: true,
    priority: 1,
    config: { mode: "redact", check_response: false },
  },
  {
    id: "pii_detection",
    type: "pii_detection",
    label: "PII Detection",
    description: "Detect and redact personally identifiable information (emails, phones, SSNs, credit cards).",
    enabled: true,
    priority: 2,
    config: { mode: "redact", entity_types: ["email", "phone", "ssn", "credit_card"] },
  },
  {
    id: "content_moderation",
    type: "content_moderation",
    label: "Content Moderation",
    description: "Block harmful, hateful, or inappropriate content using configurable backends.",
    enabled: false,
    priority: 3,
    config: { backend: "keyword", mode: "block" },
  },
  {
    id: "banned_keywords",
    type: "banned_keywords",
    label: "Banned Keywords",
    description: "Block requests containing specific keywords or phrases.",
    enabled: false,
    priority: 4,
    config: { keywords: [], case_sensitive: false },
  },
  {
    id: "blocked_users",
    type: "blocked_users",
    label: "Blocked Users",
    description: "Block specific users or teams from sending requests.",
    enabled: false,
    priority: 5,
    config: { blocked_user_ids: [], blocked_team_ids: [] },
  },
];

const TYPE_ICON_COLOR: Record<string, string> = {
  secret_detection: "text-red-500",
  pii_detection: "text-orange-500",
  content_moderation: "text-purple-500",
  banned_keywords: "text-yellow-600",
  blocked_users: "text-gray-500",
};

// ─── Config editor modal ──────────────────────────────────────────────────────

function ConfigModal({
  guardrail,
  onClose,
  onSave,
}: {
  guardrail: GuardrailItem;
  onClose: () => void;
  onSave: (id: string, config: Record<string, unknown>) => void;
}) {
  const [raw, setRaw] = useState(JSON.stringify(guardrail.config, null, 2));
  const [error, setError] = useState("");

  function handleSave() {
    try {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      onSave(guardrail.id, parsed);
      onClose();
    } catch {
      setError("Invalid JSON");
    }
  }

  return (
    <Modal
      open
      title={`Configure: ${guardrail.label}`}
      onClose={onClose}
      footer={
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave}>Save</Button>
        </div>
      }
    >
      <div className="space-y-2">
        <p className="text-sm text-gray-500">{guardrail.description}</p>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Configuration (JSON)</label>
        <textarea
          className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-sm font-mono bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 h-48 resize-y"
          value={raw}
          onChange={(e) => { setRaw(e.target.value); setError(""); }}
        />
        {error && <p className="text-xs text-red-500">{error}</p>}
        <p className="text-xs text-gray-400">
          Note: Changes here are for preview only. Apply to your <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">routerbot_config.yaml</code> to persist.
        </p>
      </div>
    </Modal>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function Guardrails() {
  const [guardrails, setGuardrails] = useState<GuardrailItem[]>(DEFAULT_GUARDRAILS);
  const [configTarget, setConfigTarget] = useState<GuardrailItem | null>(null);

  function toggleEnabled(id: string) {
    setGuardrails((prev) =>
      prev.map((g) => (g.id === id ? { ...g, enabled: !g.enabled } : g)),
    );
  }

  function saveConfig(id: string, config: Record<string, unknown>) {
    setGuardrails((prev) => prev.map((g) => (g.id === id ? { ...g, config } : g)));
  }

  return (
    <PageContainer
      title="Guardrails"
      description="Configure content safety and compliance guardrails"
    >
      <div className="mb-4 flex items-center gap-2 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
        <Shield className="h-5 w-5 text-blue-500 flex-shrink-0" />
        <p className="text-sm text-blue-700 dark:text-blue-300">
          Guardrails run in priority order. Changes here are reflected in the UI only; update{" "}
          <code className="bg-blue-100 dark:bg-blue-800 px-1 rounded">routerbot_config.yaml</code> to persist.
        </p>
      </div>

      <div className="space-y-3">
        {guardrails.map((g) => (
          <Card key={g.id}>
            <div className="flex items-start gap-4">
              <div className={`mt-1 ${TYPE_ICON_COLOR[g.type] ?? "text-gray-400"}`}>
                <Shield className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="font-medium text-gray-900 dark:text-white">{g.label}</h3>
                  <Badge variant="neutral">Priority {g.priority}</Badge>
                  {g.enabled ? (
                    <Badge variant="success">Enabled</Badge>
                  ) : (
                    <Badge variant="neutral">Disabled</Badge>
                  )}
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400">{g.description}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {Object.entries(g.config).map(([k, v]) => (
                    <span key={k} className="text-xs bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded font-mono">
                      {k}: {Array.isArray(v) ? `[${v.length}]` : String(v)}
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex gap-2 items-center flex-shrink-0">
                <Button size="sm" variant="ghost" onClick={() => setConfigTarget(g)} title="Configure">
                  <SettingsIcon className="h-4 w-4" />
                </Button>
                <button
                  onClick={() => toggleEnabled(g.id)}
                  className={`text-gray-400 hover:text-blue-500 transition-colors ${g.enabled ? "text-blue-500" : ""}`}
                  title={g.enabled ? "Disable" : "Enable"}
                >
                  {g.enabled ? (
                    <ToggleRight className="h-8 w-8 text-blue-500" />
                  ) : (
                    <ToggleLeft className="h-8 w-8 text-gray-400" />
                  )}
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {configTarget && (
        <ConfigModal
          guardrail={configTarget}
          onClose={() => setConfigTarget(null)}
          onSave={saveConfig}
        />
      )}
    </PageContainer>
  );
}
