import { Badge } from "../components/common/Badge";
import { Card } from "../components/common/Card";
import { PageContainer } from "../components/layout/PageContainer";

const mockGuardrails = [
  {
    id: "1",
    type: "secret_detection",
    label: "Secret Detection",
    description: "Detect and block API keys, passwords, and other secrets",
    enabled: true,
    priority: 1,
  },
  {
    id: "2",
    type: "pii_detection",
    label: "PII Detection",
    description: "Detect and redact personally identifiable information",
    enabled: true,
    priority: 2,
  },
  {
    id: "3",
    type: "content_moderation",
    label: "Content Moderation",
    description: "Filter harmful or inappropriate content",
    enabled: true,
    priority: 3,
  },
  {
    id: "4",
    type: "banned_keywords",
    label: "Banned Keywords",
    description: "Block messages containing specified keywords",
    enabled: false,
    priority: 4,
  },
  {
    id: "5",
    type: "blocked_users",
    label: "Blocked Users",
    description: "Block specific users or teams from making requests",
    enabled: false,
    priority: 5,
  },
];

export function Guardrails() {
  return (
    <PageContainer
      title="Guardrails"
      description="Configure content safety and security guardrails"
    >
      <div className="space-y-4">
        {mockGuardrails.map((g) => (
          <Card key={g.id}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-semibold text-surface-900 dark:text-surface-100">
                        {g.label}
                      </h3>
                      <Badge variant={g.enabled ? "success" : "neutral"}>
                        {g.enabled ? "Active" : "Disabled"}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-sm text-surface-500">
                      {g.description}
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-xs text-surface-400">Priority {g.priority}</span>
                <button
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    g.enabled ? "bg-primary-600" : "bg-surface-300 dark:bg-surface-600"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      g.enabled ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </PageContainer>
  );
}
