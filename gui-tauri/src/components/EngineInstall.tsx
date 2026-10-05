import { useCallback, useState } from "react";

import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { INSTALL_ONE_LINER, useEnginePresent } from "../lib/engine";
import { humanizeError } from "../lib/errors";
import { cn } from "../lib/utils";
import { Icon } from "./icons";
import { Button } from "./ui/Button";
import { useToast } from "./ui/Toast";

/**
 * Copy the installer one-liner and open it in the user's terminal (never run it
 * silently). Shared by the full card and the slim app-wide banner.
 */
function useInstallerActions() {
  const { t } = useI18n();
  const toast = useToast();
  const { present } = useEnginePresent();
  const [copied, setCopied] = useState(false);
  const [opening, setOpening] = useState(false);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(INSTALL_ONE_LINER);
      setCopied(true);
      toast(t("common.copied"), "ok");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      toast(t("engine.missing.copyFailed"), "error");
    }
  }, [t, toast]);

  const openTerminal = useCallback(async () => {
    setOpening(true);
    try {
      await api.openInstallerTerminal();
      toast(t("engine.missing.opened"), "ok");
    } catch (error) {
      toast(t("engine.missing.openFailed", { error: humanizeError(error, t) }), "error");
    } finally {
      setOpening(false);
    }
  }, [t, toast]);

  return { present, copied, opening, copy, openTerminal };
}

/**
 * First-run notice shown when the `assistant` engine cannot run — the case for
 * a GUI-only AppImage/deb/rpm, which ships no Python core. It offers the
 * official one-liner, a copy button and a button that opens the installer in
 * the user's own terminal (never run silently). It renders nothing when the
 * engine is present, so callers can drop it in unconditionally.
 */
export function EngineInstallCard({ className }: { className?: string }) {
  const { t } = useI18n();
  const { present, copied, opening, copy, openTerminal } = useInstallerActions();

  if (present !== false) return null;

  return (
    <section
      className={cn("relative overflow-hidden rounded-lg bg-card p-5 shadow-card", className)}
      aria-live="polite"
    >
      <div className="flex items-start gap-4">
        <span
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl"
          style={{
            color: "var(--primary)",
            background: "color-mix(in oklab, var(--primary) 13%, transparent)",
          }}
        >
          <Icon name="terminal" size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="eyebrow">{t("engine.missing.eyebrow")}</div>
          <div className="mt-1 text-[15px] font-semibold text-foreground">{t("engine.missing.title")}</div>
          <p className="mt-1 max-w-[44rem] text-xs leading-[18px] text-muted-foreground">
            {t("engine.missing.body")}
          </p>
          <div className="mt-3 flex items-center gap-2 rounded-lg bg-wash px-3 py-2 shadow-[inset_0_0_0_1px_var(--line)]">
            <code className="min-w-0 flex-1 select-all break-all font-mono text-[12px] text-foreground">
              {INSTALL_ONE_LINER}
            </code>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={copied ? "check" : "copy"}
              onClick={() => void copy()}
            >
              {copied ? t("common.copied") : t("common.copy")}
            </Button>
            <Button
              size="sm"
              variant="primary"
              icon="terminal"
              loading={opening}
              onClick={() => void openTerminal()}
            >
              {t("engine.missing.openTerminal")}
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * A slim, always-visible strip for the shell. It says the same thing as the
 * card in one line, so every page makes sense on its own when the engine is
 * missing. Renders nothing when the engine is present.
 */
export function EngineInstallBanner({ className }: { className?: string }) {
  const { t } = useI18n();
  const { present, copied, opening, copy, openTerminal } = useInstallerActions();

  if (present !== false) return null;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-lg bg-card px-4 py-2.5 shadow-card",
        className,
      )}
      aria-live="polite"
    >
      <span
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
        style={{
          color: "var(--primary)",
          background: "color-mix(in oklab, var(--primary) 13%, transparent)",
        }}
      >
        <Icon name="terminal" size={15} />
      </span>
      <p className="min-w-[12rem] flex-1 text-xs leading-[18px] text-muted-foreground">
        {t("engine.missing.short")}
      </p>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" icon={copied ? "check" : "copy"} onClick={() => void copy()}>
          {copied ? t("common.copied") : t("common.copy")}
        </Button>
        <Button
          size="sm"
          variant="primary"
          icon="terminal"
          loading={opening}
          onClick={() => void openTerminal()}
        >
          {t("engine.missing.openTerminal")}
        </Button>
      </div>
    </div>
  );
}
