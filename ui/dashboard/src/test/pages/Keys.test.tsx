/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { Keys } from "../../pages/Keys";
import type { VirtualKey } from "../../api/types";

// ---------------------------------------------------------------------------
// Mock all key hooks
// ---------------------------------------------------------------------------
const mockGenerateMutateAsync = vi.fn();
const mockUpdateMutateAsync = vi.fn();
const mockDeleteMutateAsync = vi.fn();
const mockRotateMutateAsync = vi.fn();

vi.mock("../../api/hooks/useKeys", () => ({
  useKeys: vi.fn(),
  useGenerateKey: vi.fn(),
  useUpdateKey: vi.fn(),
  useDeleteKey: vi.fn(),
  useRotateKey: vi.fn(),
}));

vi.mock("../../api/hooks/useModels", () => ({
  useModels: vi.fn(() => ({ data: [], isLoading: false })),
}));

vi.mock("../../api/hooks/useTeams", () => ({
  useTeams: vi.fn(() => ({
    data: [{ id: "team-uuid-1", team_alias: "Team 1" }],
    isLoading: false,
  })),
}));

vi.mock("../../api/hooks/useUsers", () => ({
  useUsers: vi.fn(() => ({
    data: [{ id: "user-uuid-1", email: "user@example.com" }],
    isLoading: false,
  })),
}));

import {
  useKeys,
  useGenerateKey,
  useUpdateKey,
  useDeleteKey,
  useRotateKey,
} from "../../api/hooks/useKeys";

const mockUseKeys = vi.mocked(useKeys);
const mockUseGenerateKey = vi.mocked(useGenerateKey);
const mockUseUpdateKey = vi.mocked(useUpdateKey);
const mockUseDeleteKey = vi.mocked(useDeleteKey);
const mockUseRotateKey = vi.mocked(useRotateKey);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const MOCK_KEYS: VirtualKey[] = [
  {
    id: "key-uuid-1",
    key_prefix: "rb-abc1234",
    user_id: "user-uuid-1",
    team_id: "team-uuid-1",
    models: ["gpt-4o", "claude-sonnet-4-20250514"],
    max_budget: 100,
    spend: 48.32,
    rate_limit_rpm: 100,
    rate_limit_tpm: 50000,
    expires_at: "2025-12-31T23:59:59+00:00",
    permissions: {},
    metadata: { env: "production" },
    is_active: true,
    created_at: "2024-01-15T10:00:00+00:00",
    updated_at: "2024-06-01T12:00:00+00:00",
  },
  {
    id: "key-uuid-2",
    key_prefix: "rb-def5678",
    user_id: null,
    team_id: null,
    models: [],
    max_budget: null,
    spend: 5.12,
    rate_limit_rpm: null,
    rate_limit_tpm: null,
    expires_at: null,
    permissions: {},
    metadata: {},
    is_active: true,
    created_at: "2024-02-01T14:00:00+00:00",
    updated_at: null,
  },
  {
    id: "key-uuid-3",
    key_prefix: "rb-revoked",
    user_id: null,
    team_id: null,
    models: [],
    max_budget: 50,
    spend: 50,
    rate_limit_rpm: null,
    rate_limit_tpm: null,
    expires_at: null,
    permissions: {},
    metadata: {},
    is_active: false,
    created_at: "2024-03-01T10:00:00+00:00",
    updated_at: null,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function renderKeys() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Keys />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeMutation(mutateAsync = vi.fn()) {
  return {
    mutateAsync,
    mutate: vi.fn(),
    isPending: false,
    isIdle: true,
    isSuccess: false,
    isError: false,
    data: undefined,
    error: null,
    reset: vi.fn(),
    status: "idle" as const,
    variables: undefined,
    context: undefined,
    failureCount: 0,
    failureReason: null,
    submittedAt: 0,
    isPaused: false,
  };
}

beforeEach(() => {
  vi.clearAllMocks();

  mockUseKeys.mockReturnValue({
    data: MOCK_KEYS,
    isLoading: false,
    isError: false,
    error: null,
  } as any);

  mockUseGenerateKey.mockReturnValue(makeMutation(mockGenerateMutateAsync) as any);
  mockUseUpdateKey.mockReturnValue(makeMutation(mockUpdateMutateAsync) as any);
  mockUseDeleteKey.mockReturnValue(makeMutation(mockDeleteMutateAsync) as any);
  mockUseRotateKey.mockReturnValue(makeMutation(mockRotateMutateAsync) as any);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("Keys page", () => {
  it("renders the page title", () => {
    renderKeys();
    expect(screen.getByText("Virtual Keys")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    mockUseKeys.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
    } as any);

    renderKeys();
    // The Table component shows a spinner when loading
    expect(screen.queryByText("rb-abc1234")).not.toBeInTheDocument();
  });

  it("renders the key list with key prefixes", () => {
    renderKeys();
    // truncateKey shows first 8 chars + bullets
    expect(screen.getByText(/rb-abc12/)).toBeInTheDocument();
    expect(screen.getByText(/rb-def56/)).toBeInTheDocument();
    expect(screen.getByText(/rb-revok/)).toBeInTheDocument();
  });

  it("displays models for keys", () => {
    renderKeys();
    expect(screen.getByText("gpt-4o, claude-sonnet-4-20250514")).toBeInTheDocument();
    // Key with no models shows "All"
    const allBadges = screen.getAllByText("All");
    expect(allBadges.length).toBeGreaterThanOrEqual(1);
  });

  it("shows budget progress bar", () => {
    renderKeys();
    // Key 1: $48.32 / $100.00
    expect(screen.getByText(/\$48\.32/)).toBeInTheDocument();
    expect(screen.getByText(/\$100\.00/)).toBeInTheDocument();
    // Key 2: $5.12 / ∞
    expect(screen.getByText(/\$5\.12/)).toBeInTheDocument();
    expect(screen.getByText(/∞/)).toBeInTheDocument();
  });

  it("shows correct status badges", () => {
    renderKeys();
    const activeBadges = screen.getAllByText("active");
    expect(activeBadges.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("revoked")).toBeInTheDocument();
  });

  it("shows RPM and TPM values", () => {
    renderKeys();
    expect(screen.getByText("100")).toBeInTheDocument(); // RPM
    expect(screen.getByText("50000")).toBeInTheDocument(); // TPM
  });

  it("shows empty state when no keys", () => {
    mockUseKeys.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      error: null,
    } as any);

    renderKeys();
    expect(screen.getByText("No keys generated yet")).toBeInTheDocument();
  });

  it("opens generate key modal", () => {
    renderKeys();
    fireEvent.click(screen.getByText("Generate Key"));
    expect(screen.getByText("Generate Virtual Key")).toBeInTheDocument();
    expect(screen.getByLabelText("User ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Team ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Allowed Models")).toBeInTheDocument();
    expect(screen.getByLabelText("Budget Limit ($)")).toBeInTheDocument();
    expect(screen.getByLabelText("Expiration")).toBeInTheDocument();
    expect(screen.getByLabelText("RPM Limit")).toBeInTheDocument();
    expect(screen.getByLabelText("TPM Limit")).toBeInTheDocument();
  });

  it("calls generate mutation and shows copy dialog", async () => {
    mockGenerateMutateAsync.mockResolvedValue({
      key: "rb-plaintext-secret-key-12345",
      id: "new-key-uuid",
      key_prefix: "rb-plaint",
      user_id: null,
      team_id: null,
      models: [],
      max_budget: null,
      spend: 0,
      rate_limit_rpm: null,
      rate_limit_tpm: null,
      expires_at: null,
      permissions: {},
      metadata: {},
      is_active: true,
      created_at: "2024-06-01T10:00:00+00:00",
      updated_at: null,
    });

    renderKeys();
    fireEvent.click(screen.getByText("Generate Key"));

    // Click Generate button in modal
    const buttons = screen.getAllByText("Generate");
    const generateBtn = buttons[buttons.length - 1];
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(mockGenerateMutateAsync).toHaveBeenCalled();
    });

    // Copy dialog should appear
    await waitFor(() => {
      expect(screen.getByText("Your New API Key")).toBeInTheDocument();
      expect(screen.getByText("rb-plaintext-secret-key-12345")).toBeInTheDocument();
      expect(screen.getByText(/you will not be able to see it again/)).toBeInTheDocument();
    });
  });

  it("opens edit modal when clicking edit button", () => {
    renderKeys();
    const editButtons = screen.getAllByTitle("Edit");
    fireEvent.click(editButtons[0]);
    expect(screen.getByText("Edit Key Settings")).toBeInTheDocument();
    // User/Team dropdowns should be pre-populated via select value
    const userSelect = screen.getByLabelText("User ID") as HTMLSelectElement;
    expect(userSelect.value).toBe("user-uuid-1");
    const teamSelect = screen.getByLabelText("Team ID") as HTMLSelectElement;
    expect(teamSelect.value).toBe("team-uuid-1");
    // Models text input (models mock returns empty, so fallback input renders)
    expect(screen.getByDisplayValue("gpt-4o, claude-sonnet-4-20250514")).toBeInTheDocument();
    // Budget and RPM may both be 100 — just check they exist
    const vals = screen.getAllByDisplayValue("100");
    expect(vals.length).toBeGreaterThanOrEqual(1);
  });

  it("opens delete modal when clicking delete button", () => {
    renderKeys();
    const deleteButtons = screen.getAllByTitle("Delete");
    fireEvent.click(deleteButtons[0]);
    expect(screen.getByText("Deactivate Key")).toBeInTheDocument();
    expect(screen.getByText(/Are you sure you want to deactivate this key/)).toBeInTheDocument();
    expect(screen.getByText(/rb-abc1234/)).toBeInTheDocument();
  });

  it("calls delete mutation when confirmed", async () => {
    mockDeleteMutateAsync.mockResolvedValue({ status: "deactivated" });

    renderKeys();
    const deleteButtons = screen.getAllByTitle("Delete");
    fireEvent.click(deleteButtons[0]);

    fireEvent.click(screen.getByText("Deactivate"));

    await waitFor(() => {
      expect(mockDeleteMutateAsync).toHaveBeenCalledWith("key-uuid-1");
    });
  });

  it("opens rotate modal when clicking rotate button", () => {
    renderKeys();
    const rotateButtons = screen.getAllByTitle("Rotate");
    fireEvent.click(rotateButtons[0]);
    expect(screen.getByText("Rotate Key")).toBeInTheDocument();
    expect(screen.getByLabelText("Grace Period (seconds)")).toBeInTheDocument();
    expect(screen.getByText(/rb-abc1234/)).toBeInTheDocument();
  });

  it("shows expiration date or Never", () => {
    renderKeys();
    // First key has an expiration — the exact format depends on timezone
    // At least the "Never" entries for keys with no expiration should appear
    const neverBadges = screen.getAllByText("Never");
    expect(neverBadges.length).toBeGreaterThanOrEqual(1);
  });
});
