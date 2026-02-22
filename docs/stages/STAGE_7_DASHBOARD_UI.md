# Stage 7: Admin Dashboard & UI

**Duration:** 4-5 weeks  
**Priority:** Medium-High — needed for non-technical users  
**Depends on:** Stage 1-6 (all backend features)  
**Agents:** Frontend Engineer, Backend Engineer (for API adjustments)

---

## Objective

Build a full-featured admin dashboard SPA (React + TypeScript) that provides UI management for all RouterBot features: models, keys, teams, users, spend analytics, guardrails, and system settings. The dashboard should be production-quality, responsive, and accessible.

---

## Prerequisites

- All Stage 1-6 backend APIs complete and documented
- Authentication system working (SSO, API key, JWT)

---

## Tasks

### 7.1 — Frontend Scaffolding

**Agent:** Frontend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] `ui/dashboard/` — React + TypeScript project
  - Vite as build tool
  - TypeScript strict mode
  - Tailwind CSS for styling
  - React Router for navigation
  - TanStack Query (React Query) for API state
  - Zustand for minimal client state
  - `pnpm` for package management

- [ ] Project structure:
  ```
  ui/dashboard/
  ├── package.json
  ├── tsconfig.json
  ├── vite.config.ts
  ├── tailwind.config.ts
  ├── index.html
  ├── public/
  │   └── favicon.ico
  └── src/
      ├── main.tsx
      ├── App.tsx
      ├── api/
      │   ├── client.ts       # HTTP client (axios/fetch wrapper)
      │   ├── types.ts        # API type definitions
      │   ├── hooks/          # React Query hooks per resource
      │   │   ├── useModels.ts
      │   │   ├── useKeys.ts
      │   │   ├── useTeams.ts
      │   │   ├── useUsers.ts
      │   │   ├── useSpend.ts
      │   │   └── useSettings.ts
      │   └── endpoints.ts    # API endpoint definitions
      ├── components/
      │   ├── layout/
      │   │   ├── Sidebar.tsx
      │   │   ├── Header.tsx
      │   │   ├── MainLayout.tsx
      │   │   └── PageContainer.tsx
      │   ├── common/
      │   │   ├── Button.tsx
      │   │   ├── Input.tsx
      │   │   ├── Modal.tsx
      │   │   ├── Table.tsx
      │   │   ├── Card.tsx
      │   │   ├── Badge.tsx
      │   │   ├── Notification.tsx
      │   │   ├── LoadingSpinner.tsx
      │   │   ├── EmptyState.tsx
      │   │   ├── Pagination.tsx
      │   │   └── CopyButton.tsx  # Copy to clipboard
      │   └── charts/
      │       ├── SpendChart.tsx
      │       ├── RequestsChart.tsx
      │       └── LatencyChart.tsx
      ├── pages/
      │   ├── Dashboard.tsx
      │   ├── Models.tsx
      │   ├── Keys.tsx
      │   ├── Teams.tsx
      │   ├── Users.tsx
      │   ├── Spend.tsx
      │   ├── Guardrails.tsx
      │   ├── Settings.tsx
      │   ├── Logs.tsx
      │   ├── Login.tsx
      │   └── NotFound.tsx
      ├── hooks/
      │   ├── useAuth.ts
      │   └── useTheme.ts
      ├── stores/
      │   └── authStore.ts
      └── utils/
          ├── formatters.ts   # Date, currency, number formatting
          └── constants.ts
  ```

- [ ] ESLint + Prettier configuration
- [ ] Dev proxy to backend (`vite.config.ts` proxy)
- [ ] Tests setup (Vitest + Testing Library)

**Acceptance Criteria:**
- `pnpm install && pnpm dev` starts the dashboard
- Hot reload works
- TypeScript compiles with zero errors
- Tailwind classes work in components

### 7.2 — Authentication & Layout

**Agent:** Frontend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] Login page
  - API key input field
  - SSO login buttons (dynamically loaded from `/sso/providers`)
  - Session persistence (localStorage token or HttpOnly cookie)
  
- [ ] Main layout
  - Sidebar navigation with icons
  - Header with user info, logout button
  - Breadcrumb navigation
  - Responsive (collapsible sidebar on mobile)
  - Light/dark mode toggle (system preference default)
  
- [ ] Auth context
  - Protected routes (redirect to login if unauthenticated)
  - Role-based route visibility (admins see all, viewers see less)
  - Session refresh on expiration
  
- [ ] Tests for auth flow and routing

**Acceptance Criteria:**
- Login with API key works
- SSO login redirects correctly
- Unauthorized users redirected to login
- Admin sees all nav items, viewer sees subset
- Dark/light mode works

### 7.3 — Dashboard Overview Page

**Agent:** Frontend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] Overview dashboard with real-time metrics:
  - **KPI Cards**: Total requests (24h), Total spend (24h), Active keys, Active models, Error rate
  - **Requests Chart**: Line chart of requests over time (1h, 24h, 7d, 30d)
  - **Spend Chart**: Bar chart of spend by model/provider
  - **Latency Chart**: P50/P95/P99 latency over time
  - **Top Models**: Table of most-used models
  - **Recent Errors**: List of recent error events
  - **Provider Health**: Status indicators for each provider

- [ ] Auto-refresh (configurable interval, default 30s)
- [ ] Date range picker
- [ ] Tests

**Acceptance Criteria:**
- Dashboard loads with real data from API
- Charts render correctly
- Auto-refresh updates data
- Date range filtering works
- Responsive layout on different screen sizes

### 7.4 — Model Management Page

**Agent:** Frontend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] Models list view
  - Table: model name, provider, status, RPM, TPM, request count, avg latency
  - Sortable and filterable columns
  - Status badge (healthy, degraded, down)

- [ ] Add model form/modal
  - Model name input
  - Provider dropdown
  - API base, API key (masked), max tokens
  - Rate limits (RPM, TPM)
  - Test connection button

- [ ] Edit model (inline or modal)
- [ ] Delete model (with confirmation)
- [ ] Tests

**Acceptance Criteria:**
- List shows all configured models
- Add model creates via API
- Edit and delete work
- Connection test returns result
- Form validation on required fields

### 7.5 — Virtual Keys Management Page

**Agent:** Frontend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] Keys list view
  - Table: key prefix, name, team, user, models, budget (used/max), rate limit, expires, status
  - Filter by team, user, status
  - Sort by any column

- [ ] Generate key form/modal
  - Key name
  - Assign to user and/or team
  - Allowed models (multi-select)
  - Budget limit ($)
  - Rate limits (RPM, TPM)
  - Expiration date picker
  - IP restrictions
  - Metadata key-value pairs
  - **Copy key dialog** (shown once on generation — can't retrieve later)

- [ ] Key details view
  - Usage stats (requests, tokens, spend over time)
  - Permissions summary
  - Audit log for this key

- [ ] Rotate key
  - Generate new key, show to user
  - Configurable grace period for old key

- [ ] Edit and delete key
- [ ] Tests

**Acceptance Criteria:**
- Keys list loads with proper formatting
- Generate key shows the key exactly once
- Copy to clipboard works
- Budget usage shown as progress bar
- Key rotation works
- 80%+ test coverage on key components

### 7.6 — Team & User Management Pages

**Agent:** Frontend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] Teams page
  - Team list with budget, member count, key count
  - Create team form
  - Team detail view: members, keys, spend, settings
  - Add/remove team members
  - Team settings (logging, guardrails, budget)

- [ ] Users page (admin only)
  - User list with role, teams, spend
  - Create user form
  - User detail view: teams, keys, spend
  - Role assignment
  - Disable/enable user

- [ ] Tests

**Acceptance Criteria:**
- Full CRUD for teams and users
- Member management works
- Role badges displayed correctly
- Admin-only pages not accessible to non-admins

### 7.7 — Spend Analytics Page

**Agent:** Frontend Engineer  
**Estimated effort:** 8-10 hours

**Deliverables:**
- [ ] Spend overview
  - Total spend with period selector (today, 7d, 30d, custom)
  - Spend breakdown by: model, provider, team, user, tag
  - Spend trend chart over time
  - Budget utilization gauges

- [ ] Detailed spend logs table
  - Paginated, sortable, filterable
  - Columns: timestamp, model, tokens, cost, user, team, key, tags
  - Click-through to request details
  - Search by request ID

- [ ] Spend reports
  - Generate report for period
  - Group by: model, team, user, provider
  - Export as CSV or JSON

- [ ] Tests

**Acceptance Criteria:**
- Spend data renders correctly
- Filtering by any dimension works
- Export produces valid CSV/JSON
- Charts update on date range change
- Large datasets paginate properly

### 7.8 — Guardrails Configuration Page

**Agent:** Frontend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] Guardrails list
  - Show all configured guardrails with status
  - Enable/disable toggle per guardrail
  - Priority ordering (drag-and-drop)

- [ ] Guardrail editor
  - Type-specific configuration form
  - Secret detection: pattern list editor
  - PII detection: entity type checkboxes, mode selector
  - Content moderation: backend selection, threshold sliders
  - Banned keywords: keyword list editor
  - Blocked users: user list manager

- [ ] Per-team guardrail overrides
- [ ] Tests

**Acceptance Criteria:**
- Guardrails can be configured via UI
- Enable/disable works immediately
- Per-team overrides display correctly
- Form validation prevents invalid config

### 7.9 — Settings & Configuration Page

**Agent:** Frontend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] General settings
  - Server configuration display
  - Master key rotation
  - CORS configuration

- [ ] SSO configuration
  - List configured SSO providers
  - Add/edit SSO provider
  - Test SSO connection

- [ ] Branding settings
  - Custom logo upload
  - Custom title / description
  - Theme color customization(light/dark)

- [ ] Audit log viewer
  - Paginated table of admin actions
  - Filters: actor, action, target, date range
  - Detail view for each entry

- [ ] Tests

**Acceptance Criteria:**
- Settings page shows current configuration
- SSO providers can be managed
- Branding changes reflected immediately
- Audit log displays correctly

### 7.10 — Dashboard Build & Serving

**Agent:** DevOps Engineer  
**Estimated effort:** 3-4 hours

**Deliverables:**
- [ ] Production build configuration
  - `pnpm build` produces optimized static assets
  - Code splitting and lazy loading for routes
  - Asset hashing for cache busting

- [ ] Serving from proxy server
  - FastAPI serves built dashboard as static files
  - SPA fallback (all non-API routes serve `index.html`)
  - `GET /` redirects to dashboard
  - Configurable base path (e.g., `/dashboard/`)

- [ ] Docker integration
  - Multi-stage build: Node (frontend build) → Python (final image)
  - Dashboard baked into Docker image

- [ ] Tests

**Acceptance Criteria:**
- `pnpm build` succeeds with zero warnings
- Dashboard served from proxy at `/`
- API calls from dashboard work (same-origin, no CORS issues)
- Docker image includes dashboard

---

## Definition of Done (Stage 7)

- [ ] All 7.1–7.10 tasks completed and merged
- [ ] Dashboard accessible at proxy root (`/`)
- [ ] Login via API key and SSO works
- [ ] All management pages functional and tested
- [ ] Spend analytics with charts and exports
- [ ] Guardrail configuration via UI
- [ ] Audit logs viewable
- [ ] Dark/light mode
- [ ] Responsive design (tablet/desktop)
- [ ] TypeScript compiles with zero errors
- [ ] ESLint/Prettier clean
- [ ] All tests pass, 80%+ coverage

---

## Notes for Agents

- Use the skill file at `.github/skills/frontend-design/SKILL.md` for design guidance
- Follow `docs/CODING_STANDARDS.md` frontend section (strict TS, no `any`, functional components)
- ALL API calls go through React Query hooks — no raw fetch in components
- Use Tailwind utility classes — no inline styles
- Test components with React Testing Library
- Charts: use Recharts or Chart.js (pick one and be consistent)
- Table component should support: sorting, filtering, pagination, column visibility
- Always show loading states and error states
- Copy-sensitive data (API keys) should use the CopyButton component
- Forms must have proper validation with error messages
