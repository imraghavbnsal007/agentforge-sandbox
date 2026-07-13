import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "sm" | "md";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-gradient-to-b from-indigo-500 to-indigo-600 text-white " +
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.18),0_4px_14px_-4px_rgba(99,102,241,0.55)] " +
    "hover:from-indigo-400 hover:to-indigo-600 active:translate-y-px",
  secondary:
    "border border-line-strong bg-surface-2 text-ink " +
    "hover:bg-surface-3 hover:border-[rgba(255,255,255,0.24)] active:translate-y-px",
  danger:
    "bg-gradient-to-b from-red-500 to-red-600 text-white " +
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.15),0_4px_14px_-4px_rgba(239,68,68,0.5)] " +
    "hover:from-red-400 hover:to-red-600 active:translate-y-px",
  ghost:
    "text-ink-mid hover:bg-surface-2 hover:text-ink active:translate-y-px",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1.5 text-xs gap-1.5",
  md: "px-4 py-2 text-sm gap-2",
};

/** Class string for button-shaped things (also used to style <Link>s). */
export function buttonClasses(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
): string {
  return (
    "inline-flex select-none items-center justify-center rounded-[10px] font-medium " +
    "transition-all duration-150 disabled:pointer-events-none disabled:opacity-45 " +
    `${VARIANTS[variant]} ${SIZES[size]}`
  );
}

export function Spinner({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-90"
        fill="currentColor"
        d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4z"
      />
    </svg>
  );
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  children,
  className = "",
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={`${buttonClasses(variant, size)} ${className}`}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}
