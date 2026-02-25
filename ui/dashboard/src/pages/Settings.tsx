import { Card } from "../components/common/Card";
import { Input } from "../components/common/Input";
import { PageContainer } from "../components/layout/PageContainer";
import { Button } from "../components/common/Button";

export function Settings() {
  return (
    <PageContainer title="Settings" description="System configuration and administration">
      <div className="space-y-6">
        <Card title="General">
          <div className="space-y-4">
            <Input label="Server Port" value="8000" readOnly />
            <Input label="Log Level" value="info" readOnly />
            <Input label="Max Parallel Requests" type="number" value="100" />
          </div>
        </Card>

        <Card title="CORS Configuration">
          <div className="space-y-4">
            <Input
              label="Allowed Origins"
              placeholder="*, https://example.com"
              value="*"
            />
          </div>
        </Card>

        <Card title="Master Key" description="Rotate the master admin API key">
          <div className="flex items-center gap-4">
            <Input
              type="password"
              value="sk-master-••••••••"
              readOnly
              className="max-w-sm"
            />
            <Button variant="danger">Rotate Key</Button>
          </div>
        </Card>

        <Card title="SSO Providers" description="Configure Single Sign-On authentication">
          <div className="rounded-lg border border-surface-200 p-8 text-center text-sm text-surface-500 dark:border-surface-700">
            No SSO providers configured. Add one to enable SSO login.
          </div>
          <div className="mt-4">
            <Button variant="secondary">Add SSO Provider</Button>
          </div>
        </Card>

        <Card title="Danger Zone">
          <div className="flex items-center justify-between rounded-lg border border-red-200 p-4 dark:border-red-900">
            <div>
              <p className="text-sm font-medium text-surface-900 dark:text-surface-100">
                Reset All Spend Data
              </p>
              <p className="text-xs text-surface-500">
                This will permanently delete all spend tracking data.
              </p>
            </div>
            <Button variant="danger" size="sm">
              Reset
            </Button>
          </div>
        </Card>
      </div>
    </PageContainer>
  );
}
