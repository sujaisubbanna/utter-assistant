import type { ReactNode } from "react";

import { cn } from "../../lib/utils";

type Tone = "neutral" | "accent" | "ok" | "warn" | "danger" | "muted";

const tint = (color: string, amount = 13) => ({
  color,
  background: `color-mix(in oklab, ${color} ${amount}%, transparent)`,
});

const STYLES: Record<Tone, { className: string; style?: React.CSSProperties }> = {
  neutral: { className: "bg-wash-strong text-muted-foreground" },
  muted: { className: "text-muted-foreground shadow-[inset_0_0_0_1px_var(--line-strong)]" },
  accent: { className: "bg-accent-soft text-accent-text" },
  ok: { className: "", style: tint("var(--success)") },
  warn: { className: "", style: tint("var(--warning)", 15) },
  danger: { className: "", style: tint("var(--destructive)") },
};

export function Badge({
  children,
  tone = "neutral",
  dot,
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
  className?: string;
}) {
  const styles = STYLES[tone];
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[5px] px-1.5 text-[11px] font-medium leading-none",
        styles.className,
        className,
      )}
      style={styles.style}
    >
      {dot && <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}
