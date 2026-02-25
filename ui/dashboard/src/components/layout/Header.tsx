import { LogOut, Menu, Moon, Sun } from "lucide-react";

import { useTheme } from "../../hooks/useTheme";
import { useAuthStore } from "../../stores/authStore";

interface HeaderProps {
  onToggleSidebar: () => void;
}

export function Header({ onToggleSidebar }: HeaderProps) {
  const { theme, setTheme } = useTheme();
  const logout = useAuthStore((s) => s.logout);
  const role = useAuthStore((s) => s.role);

  const cycleTheme = () => {
    const order: Array<"light" | "dark" | "system"> = ["light", "dark", "system"];
    const idx = order.indexOf(theme);
    setTheme(order[(idx + 1) % order.length]);
  };

  return (
    <header className="flex h-14 items-center justify-between border-b border-surface-200 bg-white px-4 dark:border-surface-700 dark:bg-surface-900">
      <button
        onClick={onToggleSidebar}
        className="rounded-lg p-2 text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800"
      >
        <Menu className="h-5 w-5" />
      </button>

      <div className="flex items-center gap-2">
        <button
          onClick={cycleTheme}
          className="rounded-lg p-2 text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800"
          title={`Theme: ${theme}`}
        >
          {theme === "dark" ? (
            <Moon className="h-5 w-5" />
          ) : (
            <Sun className="h-5 w-5" />
          )}
        </button>

        {role && (
          <span className="rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-medium text-primary-700 dark:bg-primary-900/30 dark:text-primary-400">
            {role}
          </span>
        )}

        <button
          onClick={logout}
          className="rounded-lg p-2 text-surface-500 hover:bg-surface-100 hover:text-danger dark:hover:bg-surface-800"
          title="Logout"
        >
          <LogOut className="h-5 w-5" />
        </button>
      </div>
    </header>
  );
}
