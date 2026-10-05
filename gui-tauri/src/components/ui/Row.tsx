import { memo, type ReactNode } from "react";

import { cn } from "../../lib/utils";
import { Icon, type IconName } from "../icons";

export function Row({
  title,
  description,
  children,
  leading,
  className,
  onClick,
  as = "div",
  htmlFor,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  leading?: ReactNode;
  className?: string;
  onClick?: () => void;
  as?: "div" | "button" | "label";
  htmlFor?: string;
}) {
  const Tag = as;
  return (
    <Tag
      className={cn(
        // `cv-row` lets WebKit skip layout and paint for off-screen rows while
        // scrolling; the intrinsic size matches the `min-h-[52px]` below.
        "cv-row flex min-h-[52px] w-full items-center gap-3 px-4 py-2.5 text-left transition-colors duration-150",
        (onClick || as === "button" || as === "label") && "focus-ring cursor-pointer hover:bg-wash",
        className,
      )}
      {...(as === "button" ? { type: "button" as const, onClick } : {})}
      {...(as === "label" && htmlFor ? { htmlFor } : {})}
    >
      {leading}
      <div className="min-w-0 flex-1 py-0.5">
        <div className="truncate text-[13px] font-medium text-foreground">{title}</div>
        {description && (
          <div className="mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">{description}</div>
        )}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </Tag>
  );
}

/** Leading icon tile for a row. */
export const Tile = memo(function Tile({
  icon,
  tone = "muted",
  className,
}: {
  icon: IconName;
  tone?: "muted" | "accent" | "ok" | "warn" | "danger";
  className?: string;
}) {
  const style =
    tone === "ok"
      ? { color: "var(--success)", background: "color-mix(in oklab, var(--success) 13%, transparent)" }
      : tone === "warn"
        ? { color: "var(--warning)", background: "color-mix(in oklab, var(--warning) 14%, transparent)" }
        : tone === "danger"
          ? {
              color: "var(--destructive)",
              background: "color-mix(in oklab, var(--destructive) 12%, transparent)",
            }
          : undefined;
  return (
    <span
      aria-hidden="true"
      style={style}
      className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
        tone === "accent" && "bg-accent-soft text-accent-text",
        tone === "muted" && "bg-wash text-muted-foreground shadow-[inset_0_0_0_1px_var(--line)]",
        className,
      )}
    >
      <Icon name={icon} size={15} />
    </span>
  );
});

/** Right-aligned secondary value (versions, paths, states). */
export function Value({ children, mono = true, className }: { children: ReactNode; mono?: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "max-w-[22rem] truncate text-xs text-muted-foreground",
        mono && "font-mono text-[11.5px]",
        className,
      )}
    >
      {children}
    </span>
  );
}
