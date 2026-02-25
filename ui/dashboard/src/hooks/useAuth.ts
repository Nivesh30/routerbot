import { useCallback, useEffect, useRef } from "react";

import { useAuthStore } from "../stores/authStore";

import type { UserRole } from "../stores/authStore";

/**
 * Auth hook that provides role checks, permission checks,
 * and automatic session refresh.
 */
export function useAuth() {
  const {
    isAuthenticated,
    role,
    userId,
    email,
    permissions,
    logout,
    refreshAuth,
  } = useAuthStore();
  const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Auto-refresh auth every 5 minutes when authenticated
  useEffect(() => {
    if (!isAuthenticated) {
      if (refreshTimer.current) {
        clearInterval(refreshTimer.current);
        refreshTimer.current = null;
      }
      return;
    }

    refreshTimer.current = setInterval(
      () => {
        refreshAuth();
      },
      5 * 60 * 1000,
    );

    return () => {
      if (refreshTimer.current) {
        clearInterval(refreshTimer.current);
        refreshTimer.current = null;
      }
    };
  }, [isAuthenticated, refreshAuth]);

  const hasPermission = useCallback(
    (perm: string) => permissions.includes(perm),
    [permissions],
  );

  const hasRole = useCallback(
    (requiredRole: UserRole) => {
      if (!role) return false;
      const hierarchy: UserRole[] = ["admin", "editor", "viewer", "api_user"];
      return hierarchy.indexOf(role) <= hierarchy.indexOf(requiredRole);
    },
    [role],
  );

  const isAdmin = role === "admin";

  return {
    isAuthenticated,
    role,
    userId,
    email,
    permissions,
    isAdmin,
    hasPermission,
    hasRole,
    logout,
    refreshAuth,
  };
}
