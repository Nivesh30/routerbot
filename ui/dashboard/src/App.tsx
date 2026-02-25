import { Route, Routes } from "react-router-dom";

import { MainLayout } from "./components/layout/MainLayout";
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

  if (!isAuthenticated) {
    return <Login />;
  }

  return (
    <Routes>
      <Route element={<MainLayout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/models" element={<Models />} />
        <Route path="/keys" element={<Keys />} />
        <Route path="/teams" element={<Teams />} />
        <Route path="/users" element={<Users />} />
        <Route path="/spend" element={<Spend />} />
        <Route path="/guardrails" element={<Guardrails />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
