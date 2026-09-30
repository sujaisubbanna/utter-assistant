import type { ReactNode } from "react";

import { cn } from "../../lib/utils";

/**
 * A settings group: the heading sits *above* a single elevated surface whose
 * rows are split by hairlines — no boxed headers, no heavy outlines.
 */
export function Section({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
  tone = "default",
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
  tone?: "default" | "danger";
}) {
  const hasHeader = Boolean(title || description || actions);
  return (
    <section className={className}>
      {hasHeader && (
        <header className="mb-2.5 flex items-end justify-between gap-4 px-0.5">
          <div className="min-w-0">
            {title && (
              <h2 className="text-[13px] font-semibold tracking-[-0.005em] text-foreground">{title}</h2>
            )}
            {description && (
              <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
        </header>
      )}
      {children && (
        <div
          className={cn(
            "divide-y divide-line overflow-hidden rounded-lg bg-card",
            tone === "danger"
              ? "shadow-[0_0_0_1px_color-mix(in_oklab,var(--destructive)_45%,transparent),0_1px_2px_rgb(0_0_0/0.05)]"
              : "shadow-card",
            bodyClassName,
          )}
        >
          {children}
        </div>
      )}
    </section>
  );
}
