import { KeyRound } from "lucide-react";
import { useState } from "react";

import { useAuthStore } from "../stores/authStore";

export function Login() {
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const login = useAuthStore((s) => s.login);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) {
      setError("API key is required");
      return;
    }
    login(apiKey.trim(), "admin");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-50 p-4 dark:bg-surface-950">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-600 text-xl font-bold text-white shadow-lg">
            R
          </div>
          <h1 className="text-2xl font-bold text-surface-900 dark:text-surface-100">
            RouterBot
          </h1>
          <p className="mt-1 text-sm text-surface-500">
            Admin Dashboard
          </p>
        </div>

        <div className="rounded-xl border border-surface-200 bg-white p-6 shadow-sm dark:border-surface-700 dark:bg-surface-800">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="apiKey"
                className="mb-1.5 block text-sm font-medium text-surface-700 dark:text-surface-300"
              >
                Master API Key
              </label>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-surface-400">
                  <KeyRound className="h-4 w-4" />
                </div>
                <input
                  id="apiKey"
                  type="password"
                  value={apiKey}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    setError("");
                  }}
                  placeholder="Enter your API key"
                  className="w-full rounded-lg border border-surface-300 bg-white py-2.5 pl-10 pr-3 text-sm text-surface-900 placeholder:text-surface-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-surface-600 dark:bg-surface-800 dark:text-surface-100"
                />
              </div>
              {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
            </div>

            <button
              type="submit"
              className="w-full rounded-lg bg-primary-600 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
            >
              Sign In
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
