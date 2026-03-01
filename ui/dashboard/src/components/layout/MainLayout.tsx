import { useCallback, useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import { Breadcrumbs } from "./Breadcrumbs";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

export function MainLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => window.matchMedia("(max-width: 1024px)").matches,
  );
  const [mobileOpen, setMobileOpen] = useState(false);

  // Auto-collapse sidebar on small screens
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1024px)");
    const handler = (e: MediaQueryListEvent) => {
      if (e.matches) {
        setSidebarCollapsed(true);
        setMobileOpen(false);
      }
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const toggleSidebar = useCallback(() => {
    // On mobile, toggle overlay; on desktop, collapse
    if (window.innerWidth < 1024) {
      setMobileOpen((prev) => !prev);
    } else {
      setSidebarCollapsed((c) => !c);
    }
  }, []);

  const closeMobile = useCallback(() => setMobileOpen(false), []);

  return (
    <div className="flex h-screen">
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/40 lg:hidden"
          onClick={closeMobile}
        />
      )}

      <Sidebar
        collapsed={sidebarCollapsed && !mobileOpen}
        onToggle={toggleSidebar}
        mobileOpen={mobileOpen}
        onMobileClose={closeMobile}
      />

      <div
        className={`flex flex-1 flex-col transition-all duration-300 ${
          sidebarCollapsed ? "lg:ml-16" : "lg:ml-[260px]"
        }`}
      >
        <Header onToggleSidebar={toggleSidebar} />

        <main className="flex-1 overflow-y-auto p-4 sm:p-6">
          <Breadcrumbs />
          <Outlet />
        </main>
      </div>
    </div>
  );
}
