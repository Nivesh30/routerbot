import { Navigate, Route, Routes } from "react-router-dom";

import { MainLayout } from "./components/layout/MainLayout";
import { ProtectedRoute } from "./components/layout/ProtectedRoute";
import { Dashboard } from "./pages/Dashboard";
import { Guardrails } from "./pages/Guardrails";
import { Keys } from "./pages/Keys";
import { Login } from "./pages/Login";
import { Logs } from "./pages/Logs";
import { Models } from "./pages/Models";
import { NotFound } from "./pages/NotFound";
import { Settings } from "./pages/Settings";
import { Spend } from "./pages/Spend";
import { Teams } from "./pages/Teams";
import { Users } from "./pages/Users";
import { useAuthStore } from "./stores/authStore";

export function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  return (
    <Routes>
      {/* Login page — redirect to dashboard if already authenticated */}
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/" replace /> : <Login />}
      />

      {/* Protected routes (require authentication) */}
      <Route
        element={
          <ProtectedRoute>
            <MainLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/models" element={<Models />} />
        <Route path="/keys" element={<Keys />} />
        <Route path="/teams" element={<Teams />} />
        <Route
          path="/users"
          element={
            <ProtectedRoute requiredRole="admin">
              <Users />
            </ProtectedRoute>
          }
        />
        <Route path="/spend" element={<Spend />} />
        <Route path="/guardrails" element={<Guardrails />} />
        <Route path="/logs" element={<Logs />} />
        <Route
          path="/settings"
          element={
            <ProtectedRoute requiredRole="admin">
              <Settings />
            </ProtectedRoute>
          }
        />
      </Route>

      {/* Catch-all */}
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
