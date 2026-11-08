import type { ReactNode } from "react";
import type { Family } from "../api";

export const FAMILIES: Family[] = ["food", "nature", "stays", "culture"];
export const FAMILY_LABEL: Record<Family, string> = {
  food: "Food",
  nature: "Nature",
  stays: "Stays",
  culture: "Culture",
};

export type Tab = "inbox" | "capture" | "globe";

const icons = {
  inbox: <path d="M3 13h5l2 3h4l2-3h5M5 5h14l2 8v6H3v-6z" />,
  capture: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v8M8 12h8" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.8 3 2.8 15 0 18M12 3c-2.8 3-2.8 15 0 18" />
    </>
  ),
  back: <path d="M15 5l-7 7 7 7" />,
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <circle cx="9" cy="10" r="2" />
      <path d="m4 18 5-5 4 4 3-3 4 4" />
    </>
  ),
  flame: (
    <path d="M12 22c4 0 7-2.8 7-6.8 0-4.4-3.6-6.6-4.6-10.2-2.4 1.6-3.4 4-3.4 6-1.4-.8-2.2-2.2-2.4-3.6C6.6 9.2 5 11.9 5 15.2 5 19.2 8 22 12 22z" />
  ),
  chat: <path d="M4 5h16v11H9l-5 4z" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </>
  ),
  link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />,
  refresh: <path d="M20 11a8 8 0 0 0-14.9-3.5L4 9M4 4v5h5M4 13a8 8 0 0 0 14.9 3.5L20 15M20 20v-5h-5" />,
  pin: (
    <>
      <path d="M12 21s-6-5.6-6-11a6 6 0 1 1 12 0c0 5.4-6 11-6 11z" />
      <circle cx="12" cy="10" r="2.2" />
    </>
  ),
};

export function Icon({ name, size = 20, stroke = 1.9 }: { name: keyof typeof icons; size?: number; stroke?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {icons[name]}
    </svg>
  );
}

export function Heart({ filled, size = 14 }: { filled: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 21s-7.5-4.6-9.6-9.2C.8 8.2 3 4.5 6.7 4.5c2.1 0 3.6 1.1 5.3 3 1.7-1.9 3.2-3 5.3-3 3.7 0 5.9 3.7 4.3 7.3C19.5 16.4 12 21 12 21z"
        fill={filled ? "var(--heart)" : "none"}
        stroke={filled ? "var(--heart)" : "currentColor"}
        strokeWidth="1.9"
      />
    </svg>
  );
}

export function Chip({
  active,
  onClick,
  dot,
  children,
}: {
  active: boolean;
  onClick: () => void;
  dot?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors duration-150 ${
        active ? "border-text bg-text font-semibold text-bg" : "border-line bg-surface font-medium text-text"
      }`}
    >
      {dot && <span className="size-2 rounded-full" style={{ background: dot }} />}
      {children}
    </button>
  );
}

const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

export function MonthBar({ best, good }: { best: number[]; good: number[] }) {
  return (
    <div className="grid grid-cols-12 gap-1" aria-label={describeMonths(best, good)}>
      {MONTHS.map((m, i) => {
        const b = best.includes(i + 1);
        const g = !b && good.includes(i + 1);
        return (
          <span
            key={i}
            className="grid h-7 place-items-center rounded-md font-mono text-[11px]"
            style={{
              background: b ? "var(--accent)" : g ? "var(--accent-soft)" : "color-mix(in oklab, var(--line) 60%, var(--bg))",
              color: b ? "var(--on-accent)" : g ? "var(--accent-ink)" : "var(--muted)",
            }}
          >
            {m}
          </span>
        );
      })}
    </div>
  );
}

const NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function monthRange(months: number[]): string {
  if (!months.length) return "";
  const s = [...months].sort((a, b) => a - b);
  return s.length === 1 ? NAMES[s[0] - 1] : `${NAMES[s[0] - 1]}–${NAMES[s[s.length - 1] - 1]}`;
}
function describeMonths(best: number[], good: number[]): string {
  const parts = [];
  if (best.length) parts.push(`Best in ${best.map((m) => NAMES[m - 1]).join(", ")}`);
  if (good.length) parts.push(`good in ${good.map((m) => NAMES[m - 1]).join(", ")}`);
  return parts.join(", ") || "No season yet";
}

export function BottomNav({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  const items: { id: Tab; label: string }[] = [
    { id: "inbox", label: "Inbox" },
    { id: "capture", label: "Capture" },
    { id: "globe", label: "Globe" },
  ];
  return (
    <nav
      aria-label="Main"
      className="grid shrink-0 grid-cols-3 border-t border-line bg-bg pt-2.5"
      style={{ paddingBottom: "max(14px, env(safe-area-inset-bottom))" }}
    >
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          aria-current={tab === it.id ? "page" : undefined}
          onClick={() => onTab(it.id)}
          className={`flex flex-col items-center gap-1 text-[11.5px] ${tab === it.id ? "font-semibold text-accent" : "font-medium text-muted"}`}
        >
          <Icon name={it.id} size={22} stroke={tab === it.id ? 2 : 1.8} />
          {it.label}
        </button>
      ))}
    </nav>
  );
}
