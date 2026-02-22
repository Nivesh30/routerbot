# Stage 4: Authentication & Management

**Duration:** 3-4 weeks  
**Priority:** High — required for multi-tenant production use  
**Depends on:** Stage 1, Stage 3 (Proxy Server)  
**Agents:** Backend Engineer, Frontend Engineer (for SSO flows)

---

## Objective

Build the complete authentication and authorization system: virtual API keys, JWT authentication, SSO (OIDC/SAML), RBAC, team/user management, and spend budgets. Unlike competing products, **all of these features are fully open source** — no enterprise license needed.

---

## Prerequisites

- Stage 1 complete: config, types, exceptions, hashing utilities
- Stage 3 complete: proxy server running with middleware pipeline
- PostgreSQL and Redis available

---

## Tasks

### 4.1 — Database Schema & Migrations

**Agent:** Backend Engineer  
**Estimated effort:** 8-10 hours

Set up the complete database layer with SQLAlchemy models and Alembic migrations.

**Deliverables:**
- [ ] `src/routerbot/db/engine.py` — Database engine setup
  - Async SQLAlchemy engine with connection pooling
  - Support for PostgreSQL (production) and SQLite (development)
  - Connection pool configuration (pool_size, max_overflow, pool_timeout)
  - Health check query on connect
  
- [ ] `src/routerbot/db/models.py` — SQLAlchemy ORM models
  - `User` — id, email, role, max_budget, spend, sso_provider_id, metadata, created_at, updated_at
  - `Team` — id, name, budget_limit, spend, max_budget_per_member, settings (JSON), created_at
  - `UserTeam` — user_id, team_id, role (admin/member), added_at
  - `VirtualKey` — id, key_hash, key_prefix, user_id, team_id, models[], max_budget, spend, rate_limit_rpm, rate_limit_tpm, expires_at, permissions (JSON), metadata (JSON), is_active, created_at
  - `SpendLog` — id, key_id, user_id, team_id, model, provider, request_id, tokens_prompt, tokens_completion, cost, tags[], metadata (JSON), ip_address, created_at
  - `AuditLog` — id, action, actor_id, actor_type, target_type, target_id, old_value (JSON), new_value (JSON), ip_address, user_agent, created_at
  - `ModelConfig` — id, model_name, provider, api_base, api_key_encrypted, settings (JSON), is_active, created_at
  - `GuardrailPolicy` — id, name, type, config (JSON), team_id, key_id, enabled, priority, created_at
  - All tables have proper indexes on foreign keys and query columns
  - UUID primary keys
  
- [ ] `alembic.ini` + `src/routerbot/db/migrations/` — Alembic setup
  - Initial migration creating all tables
  - `env.py` configured for async engine
  - Auto-generate support
  
- [ ] `src/routerbot/db/repositories/` — Repository pattern
  - `KeyRepository` — CRUD + lookup by hash, list by user/team
  - `UserRepository` — CRUD + lookup by email/SSO ID
  - `TeamRepository` — CRUD + member management
  - `SpendRepository` — log creation, aggregation queries, report generation
  - `AuditRepository` — log creation, filtered listing with retention
  
- [ ] `src/routerbot/db/session.py` — Session management
  - Async session factory
  - Request-scoped session via FastAPI dependency
  - Transaction management

- [ ] Tests for all repositories

**Acceptance Criteria:**
- `alembic upgrade head` creates all tables successfully
- All repositories have full CRUD operations
- Queries use proper indexes (verified by EXPLAIN)
- Async operations with connection pooling
- 90%+ coverage on repositories

### 4.2 — Virtual API Key Management

**Agent:** Backend Engineer  
**Estimated effort:** 8-10 hours

**Deliverables:**
- [ ] `src/routerbot/auth/api_key.py` — API key authentication
  - Key format: `rb-<random_string>` (prefix configurable)
  - Key stored as SHA-256 hash in database
  - Key lookup via hash comparison
  - Key validation: active, not expired, budget not exceeded
  - Cache validated keys in Redis (TTL configurable, default 5 min)

- [ ] `src/routerbot/proxy/routes/keys.py` — Key management endpoints
  - `POST /key/generate` — Generate new key
    - Params: user_id, team_id, models[], max_budget, rate_limit, expires_at, permissions, metadata
    - Returns: the key (only time it's shown in plaintext)
  - `POST /key/update` — Update key settings
  - `POST /key/delete` — Soft delete (deactivate) key
  - `GET /key/info` — Get key info (by key hash or key ID)
  - `GET /key/list` — List keys (filtered by user/team)
  - `POST /key/rotate` — Rotate key (generate new, deactivate old)
    - Configurable grace period where both old and new key work
  
- [ ] Key-level permissions system
  - `models` — restrict which models the key can access
  - `max_budget` — USD spend limit
  - `rate_limit_rpm` — requests per minute
  - `rate_limit_tpm` — tokens per minute
  - `expires_at` — expiration timestamp
  - `permissions` — JSON object for feature flags (guardrails on/off, etc.)
  - `allowed_ips` — IP whitelist per key
  - `metadata` — arbitrary key-value pairs

- [ ] Tests for key generation, validation, rotation, budget checking

**Acceptance Criteria:**
- Generated keys follow `rb-<random>` format
- Key lookup is O(1) via hash
- Expired keys are rejected
- Over-budget keys are rejected with clear error
- Rate limits enforced per key
- Key rotation works with grace period
- 95%+ coverage

### 4.3 — JWT Authentication

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/auth/jwt.py` — JWT authentication
  - Verify JWT tokens (RS256, HS256)
  - Configurable JWT issuer, audience, JWKS URI
  - Extract user claims (user_id, email, roles, team_id)
  - Map JWT claims to RouterBot permissions
  - Token caching (avoid re-verification within TTL)
  - Support for custom claim mappings via config

- [ ] Configuration:
  ```yaml
  auth_settings:
    jwt:
      enabled: true
      issuer: "https://auth.example.com"
      audience: "routerbot"
      jwks_uri: "https://auth.example.com/.well-known/jwks.json"
      claim_mapping:
        user_id: "sub"
        email: "email"
        team_id: "org_id"
        role: "routerbot_role"
  ```

- [ ] Tests for token verification, claim extraction, error handling

**Acceptance Criteria:**
- Valid JWT tokens are accepted
- Expired/invalid tokens return 401
- Claims correctly mapped to RouterBot user context
- JWKS key rotation handled (refresh on unknown kid)
- 95%+ coverage

### 4.4 — SSO (OIDC/SAML) — FREE, No Enterprise Gate

**Agent:** Backend Engineer  
**Estimated effort:** 10-12 hours

This is a key differentiator — SSO is fully free, not limited to 5 users.

**Deliverables:**
- [ ] `src/routerbot/auth/sso.py` — SSO integration
  - **OIDC (OpenID Connect)** support
    - Authorization Code flow
    - Discovery via `.well-known/openid-configuration`
    - Token exchange
    - User info endpoint
    - Automatic user provisioning on first login
  - **SAML 2.0** support
    - SP-initiated SSO
    - IdP metadata parsing
    - Assertion validation
    - Attribute mapping
  - **OAuth2** (generic) support
    - For providers that don't implement full OIDC
  
- [ ] `src/routerbot/auth/session.py` — Session management
  - Server-side sessions stored in Redis
  - Secure session cookies (HttpOnly, Secure, SameSite)
  - Session expiration and renewal
  - CSRF protection

- [ ] SSO Routes:
  - `GET /sso/login` — Redirect to IdP
  - `GET /sso/callback` — Handle IdP callback
  - `POST /sso/logout` — Logout and invalidate session
  - `GET /sso/providers` — List configured SSO providers

- [ ] Configuration:
  ```yaml
  auth_settings:
    sso:
      enabled: true
      providers:
        - name: "Google Workspace"
          type: oidc
          client_id: os.environ/GOOGLE_CLIENT_ID
          client_secret: os.environ/GOOGLE_CLIENT_SECRET
          discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
          allowed_domains: ["example.com"]
        - name: "Okta"
          type: oidc
          client_id: os.environ/OKTA_CLIENT_ID
          client_secret: os.environ/OKTA_CLIENT_SECRET
          discovery_url: "https://example.okta.com/.well-known/openid-configuration"
        - name: "Azure AD"
          type: oidc
          client_id: os.environ/AZURE_CLIENT_ID
          client_secret: os.environ/AZURE_CLIENT_SECRET
          discovery_url: "https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"
  ```

- [ ] Tests for OIDC flow, SAML flow, session management

**Acceptance Criteria:**
- OIDC login flow works end-to-end
- SAML login flow works end-to-end
- Users auto-provisioned on first SSO login
- Sessions stored in Redis with proper expiration
- **No user limit** — unlimited SSO users
- Configuration supports multiple IdPs simultaneously
- 90%+ coverage

### 4.5 — Role-Based Access Control (RBAC)

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/auth/rbac.py` — RBAC system
  - Roles: `admin`, `editor`, `viewer`, `api_user`
  - Permission matrix per role (see below)
  - Team-level roles (team admin, team member)
  - Permission check middleware for proxy routes
  - Decorators for protecting route handlers

- [ ] Permission Matrix:

  | Resource | Admin | Editor | Viewer | API User |
  |---|---|---|---|---|
  | LLM endpoints | ✅ | ✅ | ❌ | ✅ |
  | Own keys (CRUD) | ✅ | ✅ | ❌ | ❌ |
  | All keys (CRUD) | ✅ | ❌ | ❌ | ❌ |
  | Own team keys | ✅ | ✅ | ❌ | ❌ |
  | Teams (CRUD) | ✅ | ❌ | ❌ | ❌ |
  | Users (CRUD) | ✅ | ❌ | ❌ | ❌ |
  | Models (CRUD) | ✅ | ✅ | ❌ | ❌ |
  | Spend (own) | ✅ | ✅ | ✅ | ❌ |
  | Spend (all) | ✅ | ❌ | ❌ | ❌ |
  | Settings | ✅ | ❌ | ❌ | ❌ |
  | Audit logs | ✅ | ❌ | ❌ | ❌ |
  | Guardrails | ✅ | ✅ (own team) | ❌ | ❌ |

- [ ] `src/routerbot/proxy/middleware/auth.py` — Auth middleware
  - Extract Bearer token from Authorization header
  - Determine auth type (API key, JWT, SSO session)
  - Resolve to `AuthContext` (user_id, team_id, role, permissions)
  - Pass `AuthContext` to route handlers via `Depends()`

- [ ] Tests for all permission checks

**Acceptance Criteria:**
- Admin can access everything
- Editor can manage own team resources
- Viewer has read-only access
- API user can only call LLM endpoints
- Unauthorized access returns 403 with clear message
- 95%+ coverage

### 4.6 — Team & User Management

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/proxy/routes/teams.py` — Team management
  - `POST /team/new` — Create team (name, budget_limit, settings)
  - `POST /team/update` — Update team
  - `POST /team/delete` — Delete team (soft delete)
  - `GET /team/list` — List teams
  - `GET /team/info` — Team details + members
  - `POST /team/member/add` — Add member to team
  - `POST /team/member/remove` — Remove member
  - Team-level settings: default models, logging config, guardrail config, budget

- [ ] `src/routerbot/proxy/routes/users.py` — User management
  - `POST /user/new` — Create user (email, role, max_budget)
  - `POST /user/update` — Update user
  - `POST /user/delete` — Deactivate user
  - `GET /user/info` — User details + teams + keys
  - `GET /user/list` — List users (admin only)

- [ ] `src/routerbot/proxy/routes/spend.py` — Spend tracking
  - `GET /spend/logs` — Detailed spend logs (paginated, filterable)
  - `GET /spend/tags` — Spend aggregated by tag
  - `GET /spend/report` — Spend report (by team, user, model, time period)
  - `GET /spend/keys` — Spend per key
  - `POST /spend/export` — Export spend data (CSV/JSON)
  
- [ ] Budget enforcement
  - Check budget before every LLM request
  - Per-key budgets
  - Per-user budgets
  - Per-team budgets
  - Per-model budgets (per key)
  - Per-tag budgets
  - Configurable budget reset period (daily, weekly, monthly)
  - Alert when approaching budget threshold (80%, 90%, 100%)

- [ ] Tests for all management endpoints and budget enforcement

**Acceptance Criteria:**
- Full CRUD for teams and users
- Team membership management works
- Spend logs recorded for every LLM request
- Budget enforcement blocks over-budget requests
- Spend reports generate correct aggregations
- Export produces valid CSV/JSON
- 90%+ coverage

### 4.7 — Audit Logging

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] `src/routerbot/db/repositories/audit.py` — Audit log repository
  - Log all admin actions: key CRUD, user CRUD, team CRUD, config changes, model changes
  - Store: action, actor, target, old_value, new_value, ip_address, timestamp
  - Retention policy: configurable auto-deletion after N days
  - Efficient querying with filters (by actor, action, target, time range)

- [ ] `src/routerbot/proxy/routes/audit.py` — Audit log endpoints
  - `GET /audit/logs` — List audit logs (admin only, paginated)
  - `GET /audit/logs/{id}` — Get single audit log entry
  - Filters: actor_id, action, target_type, date_range

- [ ] Retention management
  - Background task to clean old audit logs
  - Configurable retention period (default: 90 days)
  - Option to export before deletion

- [ ] Tests

**Acceptance Criteria:**
- Every admin action creates an audit log entry
- Audit logs include before/after values for changes
- Retention cleanup works correctly
- Query by any filter returns correct results
- 90%+ coverage

### 4.8 — IP-Based Access Control

**Agent:** Backend Engineer  
**Estimated effort:** 3-4 hours

**Deliverables:**
- [ ] `src/routerbot/proxy/middleware/ip_filter.py` — IP filtering
  - Global IP allowlist/blocklist (config)
  - Per-key IP allowlist (stored in key permissions)
  - Support CIDR notation (e.g., `10.0.0.0/8`)
  - Track request IP address in spend logs
  - X-Forwarded-For header handling for reverse proxies

- [ ] Configuration:
  ```yaml
  general_settings:
    allowed_ips: ["10.0.0.0/8", "192.168.1.0/24"]
    blocked_ips: ["1.2.3.4"]
    trust_proxy_headers: true
  ```

- [ ] Tests

**Acceptance Criteria:**
- Requests from blocked IPs are rejected with 403
- Requests from IPs not in allowlist are rejected (when allowlist configured)
- CIDR ranges work correctly
- Per-key IP restrictions work
- X-Forwarded-For correctly parsed
- 90%+ coverage

---

## Definition of Done (Stage 4)

- [ ] All 4.1–4.8 tasks completed and merged
- [ ] Database migrations run cleanly on fresh PostgreSQL
- [ ] Virtual API keys: generate, authenticate, rotate, expire, budget-limit
- [ ] JWT auth works with configurable JWKS
- [ ] SSO works with OIDC (tested with at least one provider)
- [ ] RBAC enforced on all management endpoints
- [ ] Teams and users fully manageable
- [ ] Spend tracked per request, queryable and exportable
- [ ] Audit logs for all admin actions
- [ ] IP access control works
- [ ] All tests pass, 90%+ coverage
- [ ] **No enterprise license gates on any feature**

---

## Notes for Agents

- Security is paramount — double-check all auth logic
- Never store API keys in plaintext — always hash
- Use parameterized queries only — the ORM handles this
- all auth logic must be in `auth/` module, not in route handlers
- Use `Depends(verify_auth)` pattern for DI in routes
- Test both positive (authorized) and negative (unauthorized) cases
- Budget checks must happen BEFORE the LLM call, not after
- SSO session storage in Redis must handle Redis unavailability gracefully (fallback to cookie-only mode)
