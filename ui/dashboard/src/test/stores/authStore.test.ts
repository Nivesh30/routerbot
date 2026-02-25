import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../../stores/authStore";

// Mock the API client
const mockPost = vi.fn();
const mockGet = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
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

describe("authStore", () => {
  beforeEach(() => {
    // Reset store state
    useAuthStore.setState({
      token: null,
      role: null,
      userId: null,
      email: null,
      authMethod: null,
      permissions: [],
      isAuthenticated: false,
    });
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe("login", () => {
    it("stores auth info on successful login", async () => {
      mockPost.mockResolvedValueOnce({
        authenticated: true,
        user_id: "master",
        email: null,
        team_id: null,
        role: "admin",
        auth_method: "master_key",
        permissions: ["llm:access", "settings:manage"],
      });

      await useAuthStore.getState().login("test-key");

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(true);
      expect(state.role).toBe("admin");
      expect(state.userId).toBe("master");
      expect(state.authMethod).toBe("master_key");
      expect(state.permissions).toContain("llm:access");
      expect(localStorage.getItem("routerbot_token")).toBe("test-key");
    });

    it("throws on failed login (not authenticated)", async () => {
      mockPost.mockResolvedValueOnce({
        authenticated: false,
        role: "api_user",
        auth_method: "none",
        permissions: [],
      });

      await expect(useAuthStore.getState().login("bad-key")).rejects.toThrow();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
    });

    it("throws when API returns error", async () => {
      mockPost.mockRejectedValueOnce(new Error("Network error"));

      await expect(useAuthStore.getState().login("key")).rejects.toThrow("Network error");
    });
  });

  describe("loginSSO", () => {
    it("stores SSO auth info without a token", () => {
      useAuthStore.getState().loginSSO({
        authenticated: true,
        user_id: "sso-user",
        email: "user@example.com",
        team_id: null,
        role: "editor",
        auth_method: "sso",
        permissions: ["llm:access", "models:manage"],
      });

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(true);
      expect(state.token).toBeNull(); // SSO uses cookies
      expect(state.role).toBe("editor");
      expect(state.email).toBe("user@example.com");
    });
  });

  describe("refreshAuth", () => {
    it("updates state from server response", async () => {
      // First login
      useAuthStore.setState({
        token: "key",
        isAuthenticated: true,
        role: "admin",
      });

      mockGet.mockResolvedValueOnce({
        authenticated: true,
        user_id: "master",
        email: "admin@test.com",
        team_id: null,
        role: "admin",
        auth_method: "master_key",
        permissions: ["llm:access"],
      });

      await useAuthStore.getState().refreshAuth();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(true);
      expect(state.email).toBe("admin@test.com");
    });

    it("logs out on refresh failure", async () => {
      useAuthStore.setState({
        token: "key",
        isAuthenticated: true,
        role: "admin",
      });

      mockGet.mockRejectedValueOnce(new Error("401"));

      await useAuthStore.getState().refreshAuth();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.token).toBeNull();
    });
  });

  describe("logout", () => {
    it("clears all auth state", () => {
      useAuthStore.setState({
        token: "key",
        role: "admin",
        userId: "master",
        isAuthenticated: true,
        permissions: ["llm:access"],
      });
      localStorage.setItem("routerbot_token", "key");

      useAuthStore.getState().logout();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.token).toBeNull();
      expect(state.role).toBeNull();
      expect(state.userId).toBeNull();
      expect(state.permissions).toEqual([]);
      expect(localStorage.getItem("routerbot_token")).toBeNull();
    });
  });
});
