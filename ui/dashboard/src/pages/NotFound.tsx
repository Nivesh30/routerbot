import { Home } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "../components/common/Button";

export function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-surface-50 p-4 dark:bg-surface-950">
      <h1 className="text-6xl font-bold text-surface-300 dark:text-surface-700">
        404
      </h1>
      <p className="mt-2 text-lg text-surface-600 dark:text-surface-400">
        Page not found
      </p>
      <Link to="/" className="mt-6">
        <Button icon={<Home className="h-4 w-4" />}>Back to Dashboard</Button>
      </Link>
    </div>
  );
}
