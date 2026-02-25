import {
  Brain,
  DollarSign,
  Key,
  LayoutDashboard,
  ScrollText,
  Settings,
  Shield,
  UserCog,
  Users,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { useAuthStore } from "../../stores/authStore";
import { APP_NAME, NAV_ITEMS } from "../../utils/constants";

import type { LucideIcon } from "lucide-react";

const iconMap: Record<string, LucideIcon> = {
  LayoutDashboard,
  Brain,
  Key,
  Users,
  UserCog,
  DollarSign,
  Shield,
  ScrollText,
  Settings,
};

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed }: SidebarProps) {
  const role = useAuthStore((s) => s.role);

  const visibleItems = NAV_ITEMS.filter(
    (item) => !item.adminOnly || role === "admin",
  );

  return (
    <aside
      className={`fixed inset-y-0 left-0 z-30 flex flex-col border-r border-surface-200 bg-white transition-all duration-300 dark:border-surface-700 dark:bg-surface-900 ${
        collapsed ? "w-16" : "w-[260px]"
      }`}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-3 border-b border-surface-200 px-4 dark:border-surface-700">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-600 text-sm font-bold text-white">
          R
        </div>
        {!collapsed && (
          <span className="text-lg font-bold text-surface-900 dark:text-surface-100">
            {APP_NAME}
          </span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-3">
        <ul className="space-y-1">
          {visibleItems.map((item) => {
            const Icon = iconMap[item.icon];
            return (
              <li key={item.path}>
                <NavLink
                  to={item.path}
                  end={item.path === "/"}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                      isActive
                        ? "bg-primary-50 text-primary-700 dark:bg-primary-900/20 dark:text-primary-400"
                        : "text-surface-600 hover:bg-surface-100 hover:text-surface-900 dark:text-surface-400 dark:hover:bg-surface-800 dark:hover:text-surface-100"
                    }`
                  }
                >
                  {Icon && <Icon className="h-5 w-5 shrink-0" />}
                  {!collapsed && <span>{item.label}</span>}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="border-t border-surface-200 p-3 dark:border-surface-700">
        {!collapsed && (
          <p className="text-xs text-surface-400">RouterBot v1.0.0</p>
        )}
      </div>
    </aside>
  );
}
