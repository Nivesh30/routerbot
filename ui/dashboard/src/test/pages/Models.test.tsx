import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { Models } from "../../pages/Models";
import type { Model } from "../../api/types";

// Mock all the model hooks
const mockMutateAsync = vi.fn();

vi.mock("../../api/hooks/useModels", () => ({
  useModels: vi.fn(),
  useAddModel: vi.fn(),
  useUpdateModel: vi.fn(),
  useDeleteModel: vi.fn(),
  useTestConnection: vi.fn(),
}));

import {
  useModels,
  useAddModel,
  useUpdateModel,
  useDeleteModel,
  useTestConnection,
} from "../../api/hooks/useModels";

const mockUseModels = vi.mocked(useModels);
const mockUseAddModel = vi.mocked(useAddModel);
const mockUseUpdateModel = vi.mocked(useUpdateModel);
const mockUseDeleteModel = vi.mocked(useDeleteModel);
const mockUseTestConnection = vi.mocked(useTestConnection);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_MODELS: Model[] = [
  {
    model_name: "gpt-4o",
    model: "openai/gpt-4o",
    provider: "openai",
    api_key_set: true,
    api_base: null,
    max_tokens: 4096,
    rpm: 500,
    tpm: 80000,
    timeout: null,
    extra_headers: {},
    extra_body: {},
    created: 1700000000,
    model_info: {
      supports_streaming: true,
      supports_function_calling: true,
      supports_vision: true,
      input_cost_per_token: 0.00015,
      output_cost_per_token: 0.0006,
    },
  },
  {
    model_name: "claude-3",
    model: "anthropic/claude-3-opus-20240229",
    provider: "anthropic",
    api_key_set: false,
    api_base: null,
    max_tokens: null,
    rpm: 300,
    tpm: null,
    timeout: null,
    extra_headers: {},
    extra_body: {},
    created: 1700000000,
  },
];

function makeMutationResult(overrides: Record<string, unknown> = {}) {
  return {
    mutateAsync: mockMutateAsync,
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    isIdle: true,
    isSuccess: false,
    data: undefined,
    error: null,
    reset: vi.fn(),
    status: "idle" as const,
    variables: undefined,
    failureCount: 0,
    failureReason: null,
    context: undefined,
    submittedAt: 0,
    isPaused: false,
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setupHooks(models: Model[] = MOCK_MODELS, loading = false) {
  mockUseModels.mockReturnValue({
    data: models,
    isLoading: loading,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useModels>);

  const mutation = makeMutationResult();
  mockUseAddModel.mockReturnValue(mutation as unknown as ReturnType<typeof useAddModel>);
  mockUseUpdateModel.mockReturnValue(mutation as unknown as ReturnType<typeof useUpdateModel>);
  mockUseDeleteModel.mockReturnValue(mutation as unknown as ReturnType<typeof useDeleteModel>);
  mockUseTestConnection.mockReturnValue(mutation as unknown as ReturnType<typeof useTestConnection>);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Models Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMutateAsync.mockResolvedValue({ status: "created", model: MOCK_MODELS[0] });
  });

  it("renders page title", () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });
    expect(screen.getByText("Models")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    setupHooks([], true);
    render(<Models />, { wrapper: Wrapper });
    // Table shows spinner when loading
    expect(screen.queryByText("gpt-4o")).not.toBeInTheDocument();
  });

  it("displays model list", () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("claude-3")).toBeInTheDocument();
  });

  it("shows provider info", () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("anthropic")).toBeInTheDocument();
  });

  it("shows API key badges", () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });
    expect(screen.getByText("Set")).toBeInTheDocument();
    expect(screen.getByText("Not set")).toBeInTheDocument();
  });

  it("shows empty state when no models", () => {
    setupHooks([]);
    render(<Models />, { wrapper: Wrapper });
    expect(screen.getByText("No models configured")).toBeInTheDocument();
  });

  it("opens add model modal", () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });
    fireEvent.click(screen.getByText("Add Model"));
    expect(screen.getByText("Provider/Model")).toBeInTheDocument();
  });

  it("add model form validates required fields", async () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });
    fireEvent.click(screen.getByText("Add Model"));

    // Click add without filling in fields — should trigger validation
    const addButton = screen.getAllByText("Add Model").at(-1);
    if (addButton) fireEvent.click(addButton);

    await waitFor(() => {
      expect(screen.getByText("Required")).toBeInTheDocument();
    });
  });

  it("opens edit modal on row click", async () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });

    // Click the edit icon (pencil)
    const editButtons = screen.getAllByTitle("Edit");
    fireEvent.click(editButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("Edit gpt-4o")).toBeInTheDocument();
    });
  });

  it("opens delete confirmation on delete click", async () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });

    const deleteButtons = screen.getAllByTitle("Delete");
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("Delete Model")).toBeInTheDocument();
      expect(screen.getByText(/Are you sure/)).toBeInTheDocument();
    });
  });

  it("displays RPM and TPM values", () => {
    setupHooks();
    render(<Models />, { wrapper: Wrapper });
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText("80000")).toBeInTheDocument();
  });
});
