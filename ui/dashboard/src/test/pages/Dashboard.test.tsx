import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { Dashboard } from "../../pages/Dashboard";
import type { DashboardMetrics } from "../../api/types";

// Mock the useDashboard hook
const mockRefetch = vi.fn();
vi.mock("../../api/hooks/useDashboard", () => ({
  useDashboardStats: vi.fn(),
}));

import { useDashboardStats } from "../../api/hooks/useDashboard";
const mockUseDashboardStats = vi.mocked(useDashboardStats);

function makeMockMetrics(overrides?: Partial<DashboardMetrics>): DashboardMetrics {
  return {
    period: "24h",
    period_start: "2025-01-01T00:00:00Z",
    period_end: "2025-01-02T00:00:00Z",
    total_requests: 1234,
    total_spend: 56.78,
    total_tokens: 500000,
    active_keys: 12,
    active_models: 5,
    active_teams: 3,
    active_users: 8,
    error_rate: 0.015,
    latency_p50: 200,
    latency_p95: 800,
    latency_p99: 2000,
    spend_by_model: { "gpt-4o": 30.0, "claude-3": 20.0 },
    requests_by_model: { "gpt-4o": 800, "claude-3": 434 },
    top_models: [
      { model: "gpt-4o", requests: 800, spend: 30.0 },
      { model: "claude-3", requests: 434, spend: 20.0 },
    ],
    time_series: [
      { timestamp: "2025-01-01T00:00:00Z", requests: 50, spend: 2.5, tokens: 20000 },
      { timestamp: "2025-01-01T01:00:00Z", requests: 60, spend: 3.0, tokens: 25000 },
    ],
    provider_health: {
      openai: { status: "healthy", value: 1 },
      anthropic: { status: "healthy", value: 1 },
    },
    uptime_seconds: 86400,
    recent_errors: [
      { model: "gpt-4o", error_count: "3", timestamp: "2025-01-02T00:00:00Z" },
    ],
    ...overrides,
  };
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRefetch.mockResolvedValue({} as never);
  });

  it("shows loading state", () => {
    mockUseDashboardStats.mockReturnValue({
      data: undefined,
      isLoading: true,
      isFetching: true,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );
    expect(screen.getByText("Loading dashboard…")).toBeInTheDocument();
  });

  it("shows error state with retry button", () => {
    mockUseDashboardStats.mockReturnValue({
      data: undefined,
      isLoading: false,
      isFetching: false,
      error: new Error("Network error"),
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );
    expect(screen.getByText("Failed to load dashboard metrics")).toBeInTheDocument();
    expect(screen.getByText("Network error")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Retry"));
    expect(mockRefetch).toHaveBeenCalled();
  });

  it("renders KPI cards with real data", () => {
    mockUseDashboardStats.mockReturnValue({
      data: makeMockMetrics(),
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );

    // Check KPI labels
    expect(screen.getByText("Requests (24h)")).toBeInTheDocument();
    expect(screen.getByText("Spend (24h)")).toBeInTheDocument();
    expect(screen.getByText("Active Keys")).toBeInTheDocument();
    expect(screen.getByText("Active Models")).toBeInTheDocument();
    expect(screen.getByText("Error Rate")).toBeInTheDocument();
    expect(screen.getByText("P95 Latency")).toBeInTheDocument();
    expect(screen.getByText("Teams")).toBeInTheDocument();
    expect(screen.getByText("Uptime")).toBeInTheDocument();

    // Check KPI values
    expect(screen.getByText("12")).toBeInTheDocument(); // active_keys
    expect(screen.getByText("5")).toBeInTheDocument(); // active_models
  });

  it("renders chart section titles", () => {
    mockUseDashboardStats.mockReturnValue({
      data: makeMockMetrics(),
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );

    expect(screen.getByText("Requests Over Time")).toBeInTheDocument();
    expect(screen.getByText("Spend Over Time")).toBeInTheDocument();
    expect(screen.getByText("Spend by Model")).toBeInTheDocument();
    expect(screen.getByText("Latency Distribution")).toBeInTheDocument();
    expect(screen.getByText("Top Models")).toBeInTheDocument();
    expect(screen.getByText("Provider Health")).toBeInTheDocument();
    expect(screen.getByText("Recent Errors")).toBeInTheDocument();
  });

  it("renders top models table", () => {
    mockUseDashboardStats.mockReturnValue({
      data: makeMockMetrics(),
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );

    expect(screen.getAllByText("gpt-4o").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("claude-3").length).toBeGreaterThanOrEqual(1);
  });

  it("renders provider health indicators", () => {
    mockUseDashboardStats.mockReturnValue({
      data: makeMockMetrics(),
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );

    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("anthropic")).toBeInTheDocument();
    expect(screen.getAllByText("Healthy")).toHaveLength(2);
  });

  it("renders period selector with all options", () => {
    mockUseDashboardStats.mockReturnValue({
      data: makeMockMetrics(),
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );

    expect(screen.getByText("1 Hour")).toBeInTheDocument();
    expect(screen.getByText("24 Hours")).toBeInTheDocument();
    expect(screen.getByText("7 Days")).toBeInTheDocument();
    expect(screen.getByText("30 Days")).toBeInTheDocument();
  });

  it("changes period on selector click", async () => {
    mockUseDashboardStats.mockReturnValue({
      data: makeMockMetrics(),
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );

    fireEvent.click(screen.getByText("7 Days"));

    // After clicking 7 Days, the hook should be called with the new period
    await waitFor(() => {
      const lastCall = mockUseDashboardStats.mock.calls[mockUseDashboardStats.mock.calls.length - 1];
      expect(lastCall[0]).toBe("7d");
    });
  });

  it("renders recent errors", () => {
    mockUseDashboardStats.mockReturnValue({
      data: makeMockMetrics(),
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );

    expect(screen.getByText("3 errors")).toBeInTheDocument();
  });

  it("renders empty states when no data", () => {
    mockUseDashboardStats.mockReturnValue({
      data: makeMockMetrics({
        top_models: [],
        provider_health: {},
        recent_errors: [],
        spend_by_model: {},
        latency_p50: 0,
        latency_p95: 0,
        latency_p99: 0,
      }),
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: mockRefetch,
    } as never);

    render(
      <Wrapper>
        <Dashboard />
      </Wrapper>,
    );

    expect(screen.getByText("No model activity yet")).toBeInTheDocument();
    expect(screen.getByText("No provider data available")).toBeInTheDocument();
    expect(screen.getByText("No errors recorded")).toBeInTheDocument();
    expect(screen.getByText("No latency data yet")).toBeInTheDocument();
    expect(screen.getByText("No spend data yet")).toBeInTheDocument();
  });
});
