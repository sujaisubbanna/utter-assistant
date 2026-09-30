import type { ReactNode } from "react";

import { useT } from "../../i18n";
import { cn } from "../../lib/utils";
import { Icon, type IconName } from "../icons";
import { Button } from "./Button";

/** A designed empty state: layered icon tile, one line of guidance, an action. */
export function EmptyState({
  icon = "folder",
  title,
  description,
  action,
  compact,
}: {
  icon?: IconName;
  title: string;
  description?: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-2 px-6 py-7" : "gap-3 px-6 py-10",
      )}
    >
      <span className="relative flex h-11 w-11 items-center justify-center">
        <span
          aria-hidden="true"
          className="absolute inset-[-10px] rounded-full bg-[radial-gradient(closest-side,var(--accent-soft),transparent)]"
        />
        <span className="relative flex h-11 w-11 items-center justify-center rounded-xl bg-card text-accent-text shadow-raised">
          <Icon name={icon} size={20} />
        </span>
      </span>
      <div className="space-y-1">
        <div className="text-[13px] font-semibold text-foreground">{title}</div>
        {description && (
          <p className="mx-auto max-w-[22rem] text-xs text-muted-foreground">{description}</p>
        )}
      </div>
      {action && <div className="mt-1 flex items-center gap-2">{action}</div>}
    </div>
  );
}

/** A full-width error block inside a section. */
export function ErrorState({
  title,
  message,
  onRetry,
  action,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
  action?: ReactNode;
}) {
  const t = useT();
  return (
    <div
      role="alert"
      className="flex items-start gap-3 px-4 py-4"
      style={{ background: "color-mix(in oklab, var(--destructive) 5%, transparent)" }}
    >
      <span
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
        style={{
          color: "var(--destructive)",
          background: "color-mix(in oklab, var(--destructive) 12%, transparent)",
        }}
      >
        <Icon name="alert" size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-foreground">{title ?? t("common.somethingWrong")}</div>
        {message && (
          <p className="mt-0.5 font-mono text-[11.5px] text-muted-foreground [overflow-wrap:anywhere]">
            {message}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {action}
        {onRetry && (
          <Button size="sm" icon="refresh" onClick={onRetry}>
            {t("common.retry")}
          </Button>
        )}
      </div>
    </div>
  );
}

/** Back-compat alias used by older call sites. */
export function ErrorRow({ message, onRetry }: { message: string; onRetry?: () => void; className?: string }) {
  return <ErrorState message={message} onRetry={onRetry} />;
}
