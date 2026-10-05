import { getCurrentWindow } from "@tauri-apps/api/window";

import { useI18n } from "../i18n";
import { navLabelKey } from "../lib/nav";
import { useRunnerStatus } from "../lib/status";
import { useTheme } from "../lib/theme";
import { cn } from "../lib/utils";
import { Icon } from "./icons";
import { Logo } from "./Logo";
import { OfflineBadge } from "./Privacy";
import { StatusDot } from "./ui/StatusDot";

function WindowButton({
  label,
  onClick,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "focus-ring flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors duration-150",
        danger
          ? "hover:bg-[var(--destructive)] hover:text-destructive-foreground"
          : "hover:bg-wash-strong hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function ConnectionPill() {
  const { t, tn } = useI18n();
  const { connected, status, loading } = useRunnerStatus();
  const plugins = status?.plugins?.length ?? 0;
  const tone = loading ? "busy" : connected ? "ok" : "error";
  const label = loading ? t("status.checking") : connected ? t("status.online") : t("status.offline");

  return (
    <div
      className="hidden h-7 items-center gap-2 rounded-full bg-wash pl-2.5 pr-3 shadow-[inset_0_0_0_1px_var(--line)] sm:flex"
      title={status?.error || label}
      role="status"
    >
      <StatusDot tone={tone} />
      <span className="text-[11.5px] font-medium text-muted-foreground">
        {label}
        {connected && plugins > 0 && (
          <span className="text-muted-foreground/70"> · {tn("status.plugins", plugins)}</span>
        )}
      </span>
    </div>
  );
}

export function Titlebar({ route, onboarding = false }: { route: string; onboarding?: boolean }) {
  const { t } = useI18n();
  const { paletteActive } = useTheme();
  const win = getCurrentWindow();

  return (
    <header
      data-tauri-drag-region
      className="relative z-20 flex h-11 shrink-0 select-none-chrome items-center bg-chrome pr-2"
    >
      <div
        data-tauri-drag-region
        className="flex w-[224px] shrink-0 items-center gap-2 pl-4 max-[879px]:w-[60px] max-[879px]:justify-center max-[879px]:pl-0"
      >
        <Logo size={20} className="shrink-0 text-primary" title={t("app.name")} />
        <span
          data-tauri-drag-region
          className="font-display text-[16px] font-semibold tracking-[-0.02em] text-foreground max-[879px]:hidden"
        >
          {t("app.name")}
        </span>
        {paletteActive && (
          <span
            title={t("theme.matugen")}
            className="ml-0.5 flex h-4 w-4 items-center justify-center text-muted-foreground max-[879px]:hidden"
          >
            <Icon name="palette" size={13} />
          </span>
        )}
      </div>

      <div
        data-tauri-drag-region
        className="flex min-w-0 flex-1 items-center gap-1.5 pl-2 text-[12.5px] text-muted-foreground"
      >
        {onboarding ? (
          <span data-tauri-drag-region className="truncate font-medium text-foreground">
            {t("nav.setup")}
          </span>
        ) : (
          <>
            <span data-tauri-drag-region className="max-[879px]:hidden">
              {t("app.settings")}
            </span>
            <Icon name="chevron-right" size={13} className="opacity-50 max-[879px]:hidden" />
            <span data-tauri-drag-region className="truncate font-medium text-foreground">
              {t(navLabelKey(route))}
            </span>
          </>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <OfflineBadge />
        {!onboarding && <ConnectionPill />}
        <div className="flex items-center gap-0.5 pl-1">
          <WindowButton label={t("titlebar.minimize")} onClick={() => void win.minimize()}>
            <Icon name="minus" size={14} />
          </WindowButton>
          <WindowButton label={t("titlebar.maximize")} onClick={() => void win.toggleMaximize()}>
            <Icon name="square" size={12} />
          </WindowButton>
          <WindowButton label={t("titlebar.close")} danger onClick={() => void win.close()}>
            <Icon name="x" size={14} />
          </WindowButton>
        </div>
      </div>
    </header>
  );
}
