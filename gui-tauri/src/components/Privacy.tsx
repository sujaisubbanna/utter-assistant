import { useI18n } from "../i18n";
import { REMOTE_ROUTE, useRemoteParts } from "../lib/privacy";
import { cn } from "../lib/utils";
import { Icon, type IconName } from "./icons";
import { Button } from "./ui/Button";

/** The offline promise, big. Derived from config so it never over-claims. */
export function PrivacyCard() {
  const { t } = useI18n();
  const remote = useRemoteParts();
  const offline = remote.length === 0;
  const color = offline ? "var(--success)" : "var(--warning)";
  const points: { icon: IconName; key: "voice" | "screen" | "account" }[] = [
    { icon: "mic", key: "voice" },
    { icon: "eye", key: "screen" },
    { icon: "lock", key: "account" },
  ];

  return (
    <section
      aria-labelledby="privacy-title"
      className="relative overflow-hidden rounded-xl bg-card shadow-card"
      style={{
        boxShadow: `0 0 0 1px color-mix(in oklab, ${color} 28%, var(--line)), 0 1px 2px rgb(0 0 0 / 0.05), 0 12px 32px -18px color-mix(in oklab, ${color} 45%, transparent)`,
      }}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background: `radial-gradient(120% 90% at 0% 0%, color-mix(in oklab, ${color} 13%, transparent), transparent 60%)`,
        }}
      />
      <div className="relative flex items-start gap-5 px-6 py-6 max-[879px]:flex-col max-[879px]:gap-4">
        <span
          className="relative flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl"
          style={{
            color,
            background: `color-mix(in oklab, ${color} 13%, var(--card))`,
            boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${color} 30%, transparent)`,
          }}
        >
          <Icon name="shield" size={28} strokeWidth={1.7} />
          {offline && (
            <span
              aria-hidden="true"
              className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full text-white shadow-raised"
              style={{ background: color }}
            >
              <Icon name="check" size={12} strokeWidth={2.6} />
            </span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <h2
            id="privacy-title"
            className="text-[19px] font-semibold tracking-[-0.018em] text-foreground"
          >
            {offline ? t("privacy.title") : t("privacy.remoteTitle")}
          </h2>
          <p className="mt-1 max-w-[30rem] text-[13px] text-muted-foreground">
            {offline
              ? t("privacy.body")
              : t("privacy.remoteBody", { list: remote.map((part) => t(`privacy.parts.${part}`)).join(", ") })}
          </p>
          <ul className="mt-4 flex flex-wrap gap-2">
            {points.map((point) => (
              <li
                key={point.key}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-full bg-wash pl-2 pr-3 text-xs font-medium text-foreground shadow-[inset_0_0_0_1px_var(--line)]",
                )}
              >
                <Icon name={point.icon} size={13} style={{ color }} />
                {t(`privacy.points.${point.key}`)}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11.5px] text-muted-foreground/85">{t("privacy.fine")}</p>
        </div>
        {!offline && (
          <Button
            size="sm"
            icon="chevron-right"
            onClick={() => {
              window.location.hash = `/${REMOTE_ROUTE[remote[0]]}`;
            }}
          >
            {t("privacy.review")}
          </Button>
        )}
      </div>
    </section>
  );
}

/** Compact, always-visible version for the titlebar. */
export function OfflineBadge() {
  const { t } = useI18n();
  const remote = useRemoteParts();
  const offline = remote.length === 0;
  const color = offline ? "var(--success)" : "var(--warning)";
  return (
    <div
      role="status"
      title={offline ? t("privacy.badgeTitle") : t("privacy.badgeRemote")}
      className="hidden h-7 items-center gap-1.5 rounded-full pl-2 pr-2.5 text-[11.5px] font-medium md:flex"
      style={{
        color,
        background: `color-mix(in oklab, ${color} 11%, transparent)`,
        boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${color} 24%, transparent)`,
      }}
    >
      <Icon name="shield" size={13} strokeWidth={2} />
      {offline ? t("privacy.badge") : t("privacy.badgeRemote")}
    </div>
  );
}
