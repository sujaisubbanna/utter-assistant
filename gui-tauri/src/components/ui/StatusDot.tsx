import { memo } from "react";

import { cn } from "../../lib/utils";
import { Icon } from "../icons";

export type DotTone = "ok" | "warn" | "error" | "busy" | "unknown" | "muted" | "accent";

export function toneColor(tone: DotTone): string {
  return tone === "ok"
    ? "var(--success)"
    : tone === "warn"
      ? "var(--warning)"
      : tone === "error"
        ? "var(--destructive)"
        : tone === "busy" || tone === "accent"
          ? "var(--primary)"
          : "color-mix(in oklab, var(--muted-foreground) 70%, transparent)";
}

export const StatusDot = memo(function StatusDot({
  tone = "unknown",
  pulse,
  className,
}: {
  tone?: DotTone;
  pulse?: boolean;
  className?: string;
}) {
  const color = toneColor(tone);
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex h-2 w-2 shrink-0 rounded-full",
        (pulse || tone === "busy") && "animate-dot-pulse",
        className,
      )}
      style={{
        background: color,
        color,
        boxShadow: `0 0 0 3px color-mix(in oklab, ${color} 18%, transparent)`,
      }}
    />
  );
});

export function DotLabel({ tone, label, pulse }: { tone?: DotTone; label: string; pulse?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
      <StatusDot tone={tone} pulse={pulse} />
      {label}
    </span>
  );
}

export function StateIcon({ tone }: { tone: "ok" | "warn" | "error" | "unknown" }) {
  if (tone === "ok") return <Icon name="check-circle" size={16} className="text-[color:var(--success)]" />;
  if (tone === "warn") return <Icon name="alert" size={16} className="text-[color:var(--warning)]" />;
  if (tone === "error") return <Icon name="alert" size={16} className="text-[color:var(--destructive)]" />;
  return <Icon name="circle" size={16} className="text-muted-foreground" />;
}
