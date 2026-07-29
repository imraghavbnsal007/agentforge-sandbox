/** Inline icon set (lucide-style strokes) — no icon package, no font, no CDN. */

type IconProps = { className?: string };

function base(className?: string) {
  return {
    className,
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
}

export const IconGrid = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
  </svg>
);

export const IconFolder = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9L9.2 3.9A2 2 0 0 0 7.5 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
  </svg>
);

export const IconPlus = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M5 12h14" />
    <path d="M12 5v14" />
  </svg>
);

export const IconChart = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M3 3v16a2 2 0 0 0 2 2h16" />
    <path d="M7 14v3" />
    <path d="M12 9v8" />
    <path d="M17 5v12" />
  </svg>
);

export const IconChevronLeft = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="m15 18-6-6 6-6" />
  </svg>
);

export const IconSearch = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3" />
  </svg>
);

export const IconRetry = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M21 12a9 9 0 1 1-2.6-6.4" />
    <path d="M21 3v6h-6" />
  </svg>
);

export const IconCopy = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);

export const IconEye = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

export const IconExternal = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M15 3h6v6" />
    <path d="M10 14 21 3" />
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
  </svg>
);

export const IconClock = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);

export const IconBranch = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <circle cx="6" cy="6" r="2.5" />
    <circle cx="6" cy="18" r="2.5" />
    <circle cx="18" cy="6" r="2.5" />
    <path d="M6 8.5v7" />
    <path d="M18 8.5a9 9 0 0 1-9 9" />
  </svg>
);

export const IconSpark = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M12 2 9.6 9.6 2 12l7.6 2.4L12 22l2.4-7.6L22 12l-7.6-2.4Z" />
  </svg>
);

export const IconCoin = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M14.8 9.2A3 3 0 0 0 12 7.5c-1.7 0-3 1-3 2.25s1.3 2.25 3 2.25 3 1 3 2.25-1.3 2.25-3 2.25a3 3 0 0 1-2.8-1.7" />
    <path d="M12 5.5v13" />
  </svg>
);

export const IconMenu = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M4 6h16" />
    <path d="M4 12h16" />
    <path d="M4 18h16" />
  </svg>
);

export const IconX = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M18 6 6 18" />
    <path d="m6 6 12 12" />
  </svg>
);

export const IconTrash = ({ className }: IconProps) => (
  <svg {...base(className)}>
    <path d="M3 6h18" />
    <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    <path d="M10 11v6M14 11v6" />
  </svg>
);

/** Brand mark: forge spark inside a rounded gradient tile. */
export function Logo({ className }: IconProps) {
  return (
    <span
      className={`inline-flex items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-[0_4px_14px_rgba(99,102,241,0.4)] ${className ?? ""}`}
      aria-hidden
    >
      <svg
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 2 9.6 9.6 2 12l7.6 2.4L12 22l2.4-7.6L22 12l-7.6-2.4Z" />
      </svg>
    </span>
  );
}
