import { ExternalLink, KeyRound, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { endpoints } from "../api/endpoints";
import { useAuthStore } from "../stores/authStore";

import type { SSOProvider } from "../api/types";

export function Login() {
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [ssoProviders, setSsoProviders] = useState<SSOProvider[]>([]);
  const [ssoLoading, setSsoLoading] = useState(true);
  const login = useAuthStore((s) => s.login);

  // Fetch SSO providers on mount
  useEffect(() => {
    let cancelled = false;
    api
      .get<SSOProvider[]>(endpoints.ssoProviders)
      .then((providers) => {
        if (!cancelled) {
          setSsoProviders(providers.filter((p) => p.enabled));
        }
      })
      .catch(() => {
        // SSO not configured — no providers to show
      })
      .finally(() => {
        if (!cancelled) setSsoLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) {
      setError("API key is required");
      return;
    }

    setLoading(true);
    setError("");

    try {
      await login(apiKey.trim());
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Authentication failed";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const handleSSOLogin = (provider: SSOProvider) => {
    // Redirect to backend SSO login — the callback will set a session cookie
    // and redirect back to the dashboard
    window.location.href = endpoints.ssoLogin(provider.id);
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
          <p className="mt-1 text-sm text-surface-500">Admin Dashboard</p>
        </div>

        <div className="rounded-xl border border-surface-200 bg-white p-6 shadow-sm dark:border-surface-700 dark:bg-surface-800">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="apiKey"
                className="mb-1.5 block text-sm font-medium text-surface-700 dark:text-surface-300"
              >
                API Key
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
                  placeholder="Master key or API key (rb-...)"
                  disabled={loading}
                  className="w-full rounded-lg border border-surface-300 bg-white py-2.5 pl-10 pr-3 text-sm text-surface-900 placeholder:text-surface-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:opacity-50 dark:border-surface-600 dark:bg-surface-800 dark:text-surface-100"
                />
              </div>
              {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary-600 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing in…
                </>
              ) : (
                "Sign In"
              )}
            </button>
          </form>

          {/* SSO Providers */}
          {!ssoLoading && ssoProviders.length > 0 && (
            <>
              <div className="my-4 flex items-center gap-3">
                <div className="h-px flex-1 bg-surface-200 dark:bg-surface-700" />
                <span className="text-xs text-surface-400">or</span>
                <div className="h-px flex-1 bg-surface-200 dark:bg-surface-700" />
              </div>

              <div className="space-y-2">
                {ssoProviders.map((provider) => (
                  <button
                    key={provider.id}
                    onClick={() => handleSSOLogin(provider)}
                    className="flex w-full items-center justify-center gap-2 rounded-lg border border-surface-300 bg-white py-2.5 text-sm font-medium text-surface-700 transition-colors hover:bg-surface-50 dark:border-surface-600 dark:bg-surface-800 dark:text-surface-200 dark:hover:bg-surface-700"
                  >
                    <ExternalLink className="h-4 w-4" />
                    Continue with {provider.name}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <p className="mt-4 text-center text-xs text-surface-400">
          Enter your master key or a valid API key to access the dashboard.
        </p>
      </div>
    </div>
  );
}
