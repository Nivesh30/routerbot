import { ChevronRight, Home } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import { NAV_ITEMS } from "../../utils/constants";

/**
 * Breadcrumb navigation that shows the current path in the app.
 */
export function Breadcrumbs() {
  const location = useLocation();
  const pathSegments = location.pathname.split("/").filter(Boolean);

  if (pathSegments.length === 0) {
    return null; // Don't show breadcrumbs on the dashboard root
  }

  // Build breadcrumb items from the path
  const crumbs = pathSegments.map((segment, idx) => {
    const path = "/" + pathSegments.slice(0, idx + 1).join("/");
    const navItem = NAV_ITEMS.find((item) => item.path === path);
    const label = navItem?.label ?? segment.charAt(0).toUpperCase() + segment.slice(1);
    const isLast = idx === pathSegments.length - 1;
    return { path, label, isLast };
  });

  return (
    <nav aria-label="Breadcrumb" className="mb-4 flex items-center gap-1.5 text-sm">
      <Link
        to="/"
        className="flex items-center gap-1 text-surface-500 transition-colors hover:text-surface-700 dark:text-surface-400 dark:hover:text-surface-200"
      >
        <Home className="h-3.5 w-3.5" />
        <span>Dashboard</span>
      </Link>

      {crumbs.map((crumb) => (
        <span key={crumb.path} className="flex items-center gap-1.5">
          <ChevronRight className="h-3.5 w-3.5 text-surface-400" />
          {crumb.isLast ? (
            <span className="font-medium text-surface-900 dark:text-surface-100">
              {crumb.label}
            </span>
          ) : (
            <Link
              to={crumb.path}
              className="text-surface-500 transition-colors hover:text-surface-700 dark:text-surface-400 dark:hover:text-surface-200"
            >
              {crumb.label}
            </Link>
          )}
        </span>
      ))}
    </nav>
  );
}
