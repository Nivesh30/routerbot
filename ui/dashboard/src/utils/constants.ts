export const APP_NAME = "RouterBot";

interface NavItem {
  label: string;
  path: string;
  icon: string;
  adminOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", path: "/", icon: "LayoutDashboard" },
  { label: "Models", path: "/models", icon: "Brain" },
  { label: "Keys", path: "/keys", icon: "Key" },
  { label: "Teams", path: "/teams", icon: "Users" },
  { label: "Users", path: "/users", icon: "UserCog", adminOnly: true },
  { label: "Spend", path: "/spend", icon: "DollarSign" },
  { label: "Guardrails", path: "/guardrails", icon: "Shield" },
  { label: "Logs", path: "/logs", icon: "ScrollText" },
  { label: "Settings", path: "/settings", icon: "Settings", adminOnly: true },
];

export const PERIOD_OPTIONS = [
  { label: "Today", value: "today" },
  { label: "7 days", value: "7d" },
  { label: "30 days", value: "30d" },
  { label: "90 days", value: "90d" },
] as const;

export const PROVIDER_COLORS: Record<string, string> = {
  openai: "#10a37f",
  anthropic: "#d4a27f",
  google: "#4285f4",
  azure: "#0078d4",
  aws: "#ff9900",
  groq: "#f55036",
  mistral: "#ff7000",
  cohere: "#39594d",
  ollama: "#ffffff",
  deepseek: "#4d6bfe",
};
