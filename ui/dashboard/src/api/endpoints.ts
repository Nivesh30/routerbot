export const endpoints = {
  // Auth
  login: "/auth/login",
  me: "/auth/me",
  ssoProviders: "/sso/providers",
  ssoLogin: (provider: string) => `/sso/login?provider=${provider}`,
  ssoLogout: "/sso/logout",

  // Health
  health: "/health",

  // Config
  config: "/config",
  configReload: "/config/reload",

  // Models (OpenAI-compatible, read-only)
  models: "/v1/models",
  model: (id: string) => `/v1/models/${id}`,

  // Model Management (admin CRUD)
  modelList: "/model/list",
  modelInfo: (name: string) => `/model/info?model_name=${name}`,
  modelNew: "/model/new",
  modelUpdate: "/model/update",
  modelDelete: "/model/delete",
  modelTest: "/model/test_connection",

  // Keys (backend uses /key/ prefix)
  keyGenerate: "/key/generate",
  keyUpdate: "/key/update",
  keyDelete: "/key/delete",
  keyInfo: "/key/info",
  keyList: "/key/list",
  keyRotate: "/key/rotate",

  // Teams
  teamNew: "/team/new",
  teamUpdate: "/team/update",
  teamDelete: "/team/delete",
  teamList: "/team/list",
  teamInfo: (id: string) => `/team/info?team_id=${id}`,
  teamMemberAdd: "/team/member/add",
  teamMemberRemove: "/team/member/remove",

  // Users
  userNew: "/user/new",
  userUpdate: "/user/update",
  userDelete: "/user/delete",
  userInfo: (id: string) => `/user/info?user_id=${id}`,
  userList: "/user/list",

  // Spend
  spendLogs: "/spend/logs",
  spendReport: "/spend/report",
  spendKeys: "/spend/keys",

  // Guardrails (config-based, not REST)
  configGuardrails: "/config",

  // Audit
  auditLogs: "/audit/logs",
  auditLog: (id: string) => `/audit/logs/${id}`,

  // Dashboard metrics (health + config combined)
  dashboard: "/health",
  dashboardStats: "/dashboard/stats",
} as const;
