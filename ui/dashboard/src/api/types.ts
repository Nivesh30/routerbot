/* API type definitions matching RouterBot backend models */

export interface Model {
  id: string;
  model_name: string;
  provider: string;
  api_base?: string;
  api_key_name?: string;
  max_tokens?: number;
  rpm?: number;
  tpm?: number;
  status: "healthy" | "degraded" | "down";
  request_count: number;
  avg_latency_ms: number;
}

export interface VirtualKey {
  id: string;
  key_prefix: string;
  key_name: string;
  team_id?: string;
  user_id?: string;
  models: string[];
  max_budget?: number;
  current_spend: number;
  rpm_limit?: number;
  tpm_limit?: number;
  expires_at?: string;
  status: "active" | "expired" | "revoked";
  ip_restrictions: string[];
  metadata: Record<string, string>;
  created_at: string;
}

export interface GeneratedKey {
  key: string;
  key_name: string;
  expires_at?: string;
}

export interface Team {
  id: string;
  team_alias: string;
  max_budget?: number;
  current_spend: number;
  member_count: number;
  key_count: number;
  models: string[];
  metadata: Record<string, string>;
  created_at: string;
}

export interface TeamMember {
  user_id: string;
  role: "admin" | "member";
  joined_at: string;
}

export interface User {
  id: string;
  email?: string;
  role: "admin" | "viewer" | "user";
  teams: string[];
  max_budget?: number;
  current_spend: number;
  status: "active" | "disabled";
  created_at: string;
}

export interface SpendRecord {
  id: string;
  timestamp: string;
  model: string;
  provider: string;
  tokens_used: number;
  cost: number;
  user_id?: string;
  team_id?: string;
  key_id?: string;
  tags: string[];
  request_id: string;
}

export interface SpendSummary {
  total_spend: number;
  total_requests: number;
  total_tokens: number;
  period_start: string;
  period_end: string;
  by_model: Record<string, number>;
  by_provider: Record<string, number>;
  by_team: Record<string, number>;
  by_user: Record<string, number>;
}

export interface GuardrailConfig {
  id: string;
  type: "secret_detection" | "pii_detection" | "content_moderation" | "banned_keywords" | "blocked_users";
  enabled: boolean;
  priority: number;
  config: Record<string, unknown>;
}

export interface AuditEntry {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  target: string;
  details: Record<string, unknown>;
}

export interface HealthStatus {
  status: "ok" | "degraded" | "down";
  uptime_seconds: number;
  providers: Record<string, { status: string; latency_ms: number }>;
}

export interface DashboardMetrics {
  total_requests_24h: number;
  total_spend_24h: number;
  active_keys: number;
  active_models: number;
  error_rate: number;
  requests_over_time: TimeSeriesPoint[];
  spend_by_model: Record<string, number>;
  latency_p50: number;
  latency_p95: number;
  latency_p99: number;
  top_models: Array<{ model: string; requests: number; spend: number }>;
  recent_errors: Array<{ timestamp: string; model: string; error: string }>;
  provider_health: Record<string, { status: string; latency_ms: number }>;
}

export interface TimeSeriesPoint {
  timestamp: string;
  value: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface SSOProvider {
  id: string;
  name: string;
  type: "google" | "github" | "microsoft" | "okta" | "generic_oidc";
  enabled: boolean;
}
