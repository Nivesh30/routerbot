import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useAuth } from "../../hooks/useAuth";
import { useAuthStore } from "../../stores/authStore";

// Mock the API client
vi.mock("../../api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ authenticated: true, role: "admin", permissions: [] }),
    post: vi.fn().mockResolvedValue({}),
  },
  ApiError: class extends Error {
    status: number;
    statusText: string;
    data: unknown;
    constructor(s: number, st: string, d: unknown) {
      super(`API Error ${s}`);
      this.status = s;
      this.statusText = st;
      this.data = d;
    }
  },
}));

afterEach(() => {
  useAuthStore.setState({
    token: null,
    role: null,
    userId: null,
    email: null,
    authMethod: null,
    permissions: [],
    isAuthenticated: false,
  });
  vi.clearAllMocks();
});

describe("useAuth", () => {
  it("returns isAdmin=true for admin role", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      role: "admin",
      permissions: ["llm:access", "settings:manage"],
    });

    const { result } = renderHook(() => useAuth());
    expect(result.current.isAdmin).toBe(true);
    expect(result.current.isAuthenticated).toBe(true);
  });

  it("returns isAdmin=false for non-admin roles", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      role: "viewer",
      permissions: ["spend:view_own"],
    });

    const { result } = renderHook(() => useAuth());
    expect(result.current.isAdmin).toBe(false);
  });

  it("hasPermission checks permissions array", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      role: "editor",
      permissions: ["llm:access", "models:manage"],
    });

    const { result } = renderHook(() => useAuth());
    expect(result.current.hasPermission("llm:access")).toBe(true);
    expect(result.current.hasPermission("settings:manage")).toBe(false);
  });

  it("hasRole checks role hierarchy", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      role: "editor",
      permissions: [],
    });

    const { result } = renderHook(() => useAuth());
    // editor should have access to editor-level and below
    expect(result.current.hasRole("editor")).toBe(true);
    expect(result.current.hasRole("viewer")).toBe(true);
    expect(result.current.hasRole("api_user")).toBe(true);
    // but not admin
    expect(result.current.hasRole("admin")).toBe(false);
  });

  it("logout clears state", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      role: "admin",
      token: "key",
    });

    const { result } = renderHook(() => useAuth());
    act(() => {
      result.current.logout();
    });

    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });
});
