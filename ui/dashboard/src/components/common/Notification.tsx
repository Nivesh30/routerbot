import { AlertCircle, CheckCircle, Info, X, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import type { ReactNode } from "react";

type NotificationType = "success" | "error" | "warning" | "info";

interface NotificationProps {
  type: NotificationType;
  title: string;
  message?: string;
  onClose?: () => void;
  autoClose?: number;
}

const icons: Record<NotificationType, ReactNode> = {
  success: <CheckCircle className="h-5 w-5 text-success" />,
  error: <XCircle className="h-5 w-5 text-danger" />,
  warning: <AlertCircle className="h-5 w-5 text-warning" />,
  info: <Info className="h-5 w-5 text-info" />,
};

const bgClasses: Record<NotificationType, string> = {
  success: "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/50",
  error: "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950/50",
  warning: "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/50",
  info: "border-sky-200 bg-sky-50 dark:border-sky-800 dark:bg-sky-950/50",
};

export function Notification({ type, title, message, onClose, autoClose = 5000 }: NotificationProps) {
  const [visible, setVisible] = useState(true);

  const handleClose = useCallback(() => {
    setVisible(false);
    onClose?.();
  }, [onClose]);

  useEffect(() => {
    if (autoClose <= 0) return;
    const timer = setTimeout(handleClose, autoClose);
    return () => clearTimeout(timer);
  }, [autoClose, handleClose]);

  if (!visible) return null;

  return (
    <div className={`flex items-start gap-3 rounded-lg border p-4 ${bgClasses[type]}`}>
      {icons[type]}
      <div className="flex-1">
        <p className="text-sm font-medium text-surface-900 dark:text-surface-100">
          {title}
        </p>
        {message && (
          <p className="mt-0.5 text-sm text-surface-600 dark:text-surface-400">
            {message}
          </p>
        )}
      </div>
      {onClose && (
        <button
          onClick={handleClose}
          className="text-surface-400 hover:text-surface-600 dark:hover:text-surface-200"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
