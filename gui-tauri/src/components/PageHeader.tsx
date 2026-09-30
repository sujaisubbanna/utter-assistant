import type { ReactNode } from "react";

import { useT } from "../i18n";
import { useConfig } from "../lib/config";
import { Button } from "./ui/Button";
import { SkeletonPage } from "./ui/Skeleton";
import { EmptyState } from "./ui/States";

const COLUMN = "mx-auto w-full max-w-[720px] px-8 max-[879px]:px-6";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className={`${COLUMN} flex items-end justify-between gap-6 pb-7 pt-9`}>
      <div className="min-w-0 flex-1">
        <h1 className="font-display text-[24px] font-semibold leading-[30px] tracking-[-0.02em] text-foreground">{title}</h1>
        {description && <p className="mt-1.5 max-w-[34rem] text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  );
}

/**
 * The page column. With `config`, the body waits for config.toml: a skeleton
 * while it loads and a designed error (with retry) if it can't be read.
 */
export function PageBody({ children, config }: { children: ReactNode; config?: boolean }) {
  const t = useT();
  const { loading, error, reload } = useConfig();

  let content = children;
  if (config && loading) content = <SkeletonPage label={t("states.configLoading")} />;
  else if (config && error)
    content = (
      <div className="rounded-lg bg-card shadow-card">
        <EmptyState
          icon="alert"
          title={t("states.configErrorTitle")}
          description={t("states.configErrorBody")}
          action={
            <Button icon="refresh" onClick={() => void reload()}>
              {t("common.retry")}
            </Button>
          }
        />
      </div>
    );

  return (
    <div className={`${COLUMN} pb-20`}>
      <div className="stagger space-y-9">{content}</div>
    </div>
  );
}

/** Quiet footnote under a page. */
export function PageNote({ children }: { children: ReactNode }) {
  return <p className="px-0.5 text-xs text-muted-foreground/85">{children}</p>;
}
