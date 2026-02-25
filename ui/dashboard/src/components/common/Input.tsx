import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

import type { InputHTMLAttributes, ReactNode } from "react";
import { forwardRef } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
  icon?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, icon, className, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");

    return (
      <div className="space-y-1">
        {label && (
          <label
            htmlFor={inputId}
            className="block text-sm font-medium text-surface-700 dark:text-surface-300"
          >
            {label}
          </label>
        )}
        <div className="relative">
          {icon && (
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-surface-400">
              {icon}
            </div>
          )}
          <input
            ref={ref}
            id={inputId}
            className={twMerge(
              clsx(
                "w-full rounded-lg border bg-white px-3 py-2 text-sm text-surface-900",
                "placeholder:text-surface-400",
                "focus:outline-none focus:ring-1",
                "dark:border-surface-600 dark:bg-surface-800 dark:text-surface-100",
                error
                  ? "border-danger focus:border-danger focus:ring-danger"
                  : "border-surface-300 focus:border-primary-500 focus:ring-primary-500",
                icon && "pl-10",
                className,
              ),
            )}
            {...props}
          />
        </div>
        {error && <p className="text-xs text-danger">{error}</p>}
        {hint && !error && (
          <p className="text-xs text-surface-500">{hint}</p>
        )}
      </div>
    );
  },
);

Input.displayName = "Input";
