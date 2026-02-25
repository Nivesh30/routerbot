import { create } from "zustand";
import { persist } from "zustand/middleware";

import { api, ApiError } from "../api/client";
import { endpoints } from "../api/endpoints";

import type { AuthInfo } from "../api/types";

export type UserRole = "admin" | "editor" | "viewer" | "api_user";

interface AuthState {
  token: string | null;
  role: UserRole | null;
  userId: string | null;
  email: string | null;
  authMethod: string | null;
  permissions: string[];
  isAuthenticated: boolean;

  /** Server-validated login — calls POST /auth/login */
  login: (key: string) => Promise<void>;

  /** SSO callback — stores session from cookie-based auth */
  loginSSO: (info: AuthInfo) => void;

  /** Refresh current auth state from server */
  refreshAuth: () => Promise<void>;

  /** Clear all auth state */
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      role: null,
      userId: null,
      email: null,
      authMethod: null,
      permissions: [],
      isAuthenticated: false,

      login: async (key: string) => {
        const data = await api.post<AuthInfo>(endpoints.login, { key });
        if (!data.authenticated) {
          throw new ApiError(401, "Unauthorized", { detail: "Invalid API key" });
        }
        localStorage.setItem("routerbot_token", key);
        set({
          token: key,
          role: data.role as UserRole,
          userId: data.user_id,
          email: data.email,
          authMethod: data.auth_method,
          permissions: data.permissions,
          isAuthenticated: true,
        });
      },

      loginSSO: (info: AuthInfo) => {
        set({
          token: null, // SSO uses cookies, not bearer tokens
          role: info.role as UserRole,
          userId: info.user_id,
          email: info.email,
          authMethod: info.auth_method,
          permissions: info.permissions,
          isAuthenticated: true,
        });
      },

      refreshAuth: async () => {
        try {
          const data = await api.get<AuthInfo>(endpoints.me);
          if (data.authenticated) {
            set({
              role: data.role as UserRole,
              userId: data.user_id,
              email: data.email,
              authMethod: data.auth_method,
              permissions: data.permissions,
              isAuthenticated: true,
            });
          } else {
            get().logout();
          }
        } catch {
          get().logout();
        }
      },

      logout: () => {
        localStorage.removeItem("routerbot_token");
        set({
          token: null,
          role: null,
          userId: null,
          email: null,
          authMethod: null,
          permissions: [],
          isAuthenticated: false,
        });
      },
    }),
    {
      name: "routerbot-auth",
      partialize: (state) => ({
        token: state.token,
        role: state.role,
        userId: state.userId,
        email: state.email,
        authMethod: state.authMethod,
        permissions: state.permissions,
        isAuthenticated: state.isAuthenticated,
      }),
    },
  ),
);
