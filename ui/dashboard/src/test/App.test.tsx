import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { App } from "../App";

// Mock the auth store
const mockAuthState = {
  isAuthenticated: false,
  role: null as string | null,
  token: null as string | null,
  userId: null as string | null,
  email: null as string | null,
  authMethod: null as string | null,
  permissions: [] as string[],
  login: vi.fn(),
  loginSSO: vi.fn(),
  refreshAuth: vi.fn(),
  logout: vi.fn(),
};

vi.mock("../stores/authStore", () => ({
  useAuthStore: (selector: (state: typeof mockAuthState) => unknown) =>
    selector(mockAuthState),
}));

// Mock the API client
vi.mock("../api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue([]),
    post: vi.fn().mockResolvedValue({}),
  },
  ApiError: class extends Error {
    status: number;
    statusText: string;
    data: unknown;
    constructor(status: number, statusText: string, data: unknown) {
      super(`API Error ${status}`);
      this.status = status;
      this.statusText = statusText;
      this.data = data;
    }
  },
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("App Routing", () => {
  it("shows login page when not authenticated", () => {
    mockAuthState.isAuthenticated = false;
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </Wrapper>,
    );
    // Login page should redirect to /login
    expect(screen.getByText("RouterBot")).toBeInTheDocument();
    expect(screen.getByText("Admin Dashboard")).toBeInTheDocument();
  });

  it("shows login form elements", () => {
    mockAuthState.isAuthenticated = false;
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <MemoryRouter initialEntries={["/login"]}>
          <App />
        </MemoryRouter>
      </Wrapper>,
    );
    expect(screen.getByLabelText("API Key")).toBeInTheDocument();
    expect(screen.getByText("Sign In")).toBeInTheDocument();
  });

  it("redirects to dashboard when authenticated and visiting /login", () => {
    mockAuthState.isAuthenticated = true;
    mockAuthState.role = "admin";
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <MemoryRouter initialEntries={["/login"]}>
          <App />
        </MemoryRouter>
      </Wrapper>,
    );
    // Should NOT show login form
    expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument();
  });

  it("shows 404 for unknown routes", () => {
    mockAuthState.isAuthenticated = false;
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <MemoryRouter initialEntries={["/nonexistent"]}>
          <App />
        </MemoryRouter>
      </Wrapper>,
    );
    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });
});

describe("Role-based route access", () => {
  it("renders admin-only pages for admin role", () => {
    mockAuthState.isAuthenticated = true;
    mockAuthState.role = "admin";
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <MemoryRouter initialEntries={["/users"]}>
          <App />
        </MemoryRouter>
      </Wrapper>,
    );
    // Should render the users page (not redirected)
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });

  it("redirects non-admin from admin-only pages", () => {
    mockAuthState.isAuthenticated = true;
    mockAuthState.role = "viewer";
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <MemoryRouter initialEntries={["/users"]}>
          <App />
        </MemoryRouter>
      </Wrapper>,
    );
    // Should be redirected to dashboard (not showing users page)
    expect(screen.queryByText("Add User")).not.toBeInTheDocument();
  });
});
