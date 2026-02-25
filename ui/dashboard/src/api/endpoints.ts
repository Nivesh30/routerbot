export const endpoints = {
  // Auth
  login: "/auth/login",
  ssoProviders: "/sso/providers",
  ssoLogin: (provider: string) => `/sso/${provider}/login`,

  // Health
  health: "/health",

  // Models
  models: "/v1/models",
  model: (id: string) => `/v1/models/${id}`,
  modelTest: (id: string) => `/v1/models/${id}/test`,

  // Keys
  keys: "/v1/keys",
  key: (id: string) => `/v1/keys/${id}`,
  keyGenerate: "/v1/keys/generate",
  keyRotate: (id: string) => `/v1/keys/${id}/rotate`,

  // Teams
  teams: "/v1/teams",
  team: (id: string) => `/v1/teams/${id}`,
  teamMembers: (id: string) => `/v1/teams/${id}/members`,

  // Users
  users: "/v1/users",
  user: (id: string) => `/v1/users/${id}`,

  // Spend
  spend: "/v1/spend",
  spendLogs: "/v1/spend/logs",
  spendSummary: "/v1/spend/summary",
  spendExport: "/v1/spend/export",

  // Guardrails
  guardrails: "/v1/guardrails",
  guardrail: (id: string) => `/v1/guardrails/${id}`,

  // Settings
  settings: "/v1/settings",
  auditLogs: "/v1/audit/logs",

  // Dashboard
  dashboard: "/v1/dashboard/metrics",
} as const;
