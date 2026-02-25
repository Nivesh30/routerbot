import { Navigate } from "react-router-dom";

import { useAuthStore } from "../../stores/authStore";

import type { ReactNode } from "react";
import type { UserRole } from "../../stores/authStore";

interface ProtectedRouteProps {
  children: ReactNode;
  /** If set, only users with this role or higher can access */
  requiredRole?: UserRole;
}

/**
 * Wraps a route to require authentication (and optionally a minimum role).
 * Redirects to the login page if the user is not authenticated or lacks
 * the required role.
 */
export function ProtectedRoute({ children, requiredRole }: ProtectedRouteProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const role = useAuthStore((s) => s.role);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (requiredRole && role) {
    const hierarchy: UserRole[] = ["admin", "editor", "viewer", "api_user"];
    const userLevel = hierarchy.indexOf(role);
    const requiredLevel = hierarchy.indexOf(requiredRole);
    if (userLevel > requiredLevel) {
      // User doesn't have sufficient privileges — redirect to dashboard
      return <Navigate to="/" replace />;
    }
  }

  return <>{children}</>;
}
