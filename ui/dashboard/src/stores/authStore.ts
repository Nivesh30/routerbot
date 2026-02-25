import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  role: "admin" | "viewer" | "user" | null;
  isAuthenticated: boolean;
  login: (token: string, role?: "admin" | "viewer" | "user") => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      role: null,
      isAuthenticated: false,

      login: (token, role = "admin") => {
        localStorage.setItem("routerbot_token", token);
        set({ token, role, isAuthenticated: true });
      },

      logout: () => {
        localStorage.removeItem("routerbot_token");
        set({ token: null, role: null, isAuthenticated: false });
      },
    }),
    {
      name: "routerbot-auth",
      partialize: (state) => ({
        token: state.token,
        role: state.role,
        isAuthenticated: state.isAuthenticated,
      }),
    },
  ),
);
