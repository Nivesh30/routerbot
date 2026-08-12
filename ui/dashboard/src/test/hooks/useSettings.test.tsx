import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { useSSOProviders } from "../../api/hooks/useSettings";
import type { SSOProvider } from "../../api/types";

const mockGet = vi.fn();
vi.mock("../../api/client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

function Wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useSSOProviders", () => {
  it("unwraps the { providers: [...] } envelope returned by the backend", async () => {
    const providers: SSOProvider[] = [
      { id: "okta-1", name: "okta", type: "okta", enabled: true },
    ];
    mockGet.mockResolvedValueOnce({ providers });

    const { result } = renderHook(() => useSSOProviders(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Regression guard: must be the bare array, not the envelope object,
    // or callers doing `(data ?? []).map(...)` will throw at runtime.
    expect(Array.isArray(result.current.data)).toBe(true);
    expect(result.current.data).toEqual(providers);
  });
});
