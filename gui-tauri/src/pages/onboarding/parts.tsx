import { useEffect, useId, useState, type ReactNode } from "react";

import { Icon, type IconName } from "../../components/icons";
import { Modal } from "../../components/ui/Modal";
import { useI18n } from "../../i18n";
import { KIND_ICON } from "../../lib/appKinds";
import { displayMacKey, displayName, domCodeToEvdev, domCodeToMacKey } from "../../lib/keys";
import { usePlatform } from "../../lib/platform";
import { cn } from "../../lib/utils";

/**
 * Shared pieces for the onboarding wizard. Kept together so the steps stay
 * about content and flow, and the visual system lives in one place.
 */

/** Which step the rail marks, plus the total. `onSelect` jumps back only. */
export function ProgressRail({
  index,
  total,
  onSelect,
}: {
  index: number;
  total: number;
  onSelect: (index: number) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3 pb-2 pt-4">
      <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
        {t("onboarding.step", { current: index + 1, total })}
      </span>
      <div className="flex flex-1 items-center gap-1" role="group" aria-label={t("onboarding.step", { current: index + 1, total })}>
        {Array.from({ length: total }).map((_, i) => {
          const done = i < index;
          const current = i === index;
          const reachable = i <= index;
          return (
            <button
              key={i}
              type="button"
              disabled={!reachable}
              onClick={() => reachable && i !== index && onSelect(i)}
              aria-label={t("onboarding.step", { current: i + 1, total })}
              aria-current={current ? "step" : undefined}
              className={cn(
                "h-1.5 flex-1 rounded-full transition-[background-color,transform] duration-200 ease-out",
                reachable && "focus-ring",
                current ? "bg-primary" : done ? "bg-primary/55" : "bg-wash-strong",
                reachable && !current && "hover:bg-primary/80",
                reachable && "cursor-pointer",
              )}
            />
          );
        })}
      </div>
    </div>
  );
}

/** Eyebrow, display title and one paragraph — the heading every step opens with. */
export function StepHeading({
  eyebrow,
  title,
  body,
  children,
}: {
  eyebrow: string;
  title: string;
  body?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-7">
      <div className="eyebrow">{eyebrow}</div>
      <h1 className="mt-1.5 max-w-[36rem] font-display text-[26px] font-semibold leading-[32px] tracking-[-0.02em] text-foreground">
        {title}
      </h1>
      {body && <p className="mt-2 max-w-[40rem] text-[13.5px] leading-[20px] text-muted-foreground">{body}</p>}
      {children}
    </div>
  );
}

/** A feature line for the "what Utter does" step. */
export function Feature({ icon, title, body }: { icon: IconName; title: string; body: string }) {
  return (
    <div className="flex items-start gap-3.5">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-text shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--primary)_22%,transparent)]">
        <Icon name={icon} size={18} />
      </span>
      <div className="min-w-0 pt-0.5">
        <div className="text-[13.5px] font-medium text-foreground">{title}</div>
        <p className="mt-0.5 text-xs leading-[18px] text-muted-foreground">{body}</p>
      </div>
    </div>
  );
}

/** True for icon values the webview can actually render without an asset URL. */
function isRenderableIcon(icon: string | null | undefined): icon is string {
  return Boolean(icon && (/^data:image\//.test(icon) || /^https?:\/\//.test(icon)));
}

function AppIconImage({ src, alt, size }: { src: string; alt: string; size: number }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      loading="lazy"
      draggable={false}
      onError={() => setFailed(true)}
      className="h-full w-full object-contain"
    />
  );
}

/**
 * An app's icon: the real one when the catalogue supplies a data/http image,
 * the kind glyph otherwise. A broken image falls back to the glyph, so a
 * patchy catalogue never leaves a hole.
 */
export function AppIcon({
  icon,
  kind,
  size = 20,
  tileClassName,
}: {
  icon?: string | null;
  kind: string;
  size?: number;
  tileClassName?: string;
}) {
  const fallback = (
    <span
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-wash text-muted-foreground shadow-[inset_0_0_0_1px_var(--line)]",
        tileClassName,
      )}
    >
      <Icon name={KIND_ICON[kind] ?? "window"} size={16} />
    </span>
  );
  if (!isRenderableIcon(icon)) return fallback;
  return (
    <span
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-card p-[5px] shadow-[inset_0_0_0_1px_var(--line)]",
        tileClassName,
      )}
    >
      <AppIconImage key={icon} src={icon} alt="" size={size} />
    </span>
  );
}

/** A platform-aware key capture dialog, shared by the key-picking step. */
export function KeyCaptureModal({
  open,
  title,
  current,
  onClose,
  onCaptured,
}: {
  open: boolean;
  title: string;
  current: string;
  onClose: () => void;
  onCaptured: (name: string) => void;
}) {
  const { t } = useI18n();
  const { isMac } = usePlatform();
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    const onKey = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      if (event.key === "Escape") {
        onClose();
        return;
      }
      const name = isMac ? domCodeToMacKey(event.code) : domCodeToEvdev(event.code);
      if (!name) {
        setPreview(t("voice.keys.unmapped", { code: event.code }));
        return;
      }
      onCaptured(name);
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onCaptured, onClose, isMac, t]);

  return (
    <Modal open={open} onClose={onClose} title={t("voice.keys.modalTitle", { name: title.toLowerCase() })} size="sm">
      <div className="flex flex-col items-center gap-4 pb-1 pt-3 text-center">
        <span className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft text-accent-text">
          <span className="absolute inset-0 animate-dot-pulse rounded-2xl text-primary" aria-hidden="true" />
          <Icon name="keyboard" size={26} />
        </span>
        <div>
          <div className="text-[15px] font-semibold text-foreground">{t("onboarding.keys.capture")}</div>
          <p className="mt-1 text-xs text-muted-foreground">{t("onboarding.keys.captureHint")}</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {t("voice.keys.current")}
          <span className="kbd">{current ? (isMac ? displayMacKey(current) : displayName(current)) : t("onboarding.keys.notSet")}</span>
        </div>
        {preview && <p className="text-xs text-[color:var(--warning)]">{preview}</p>}
      </div>
    </Modal>
  );
}

/** One selectable model tier. A radio card with room for a size and details. */
export function TierCard({
  selected,
  onSelect,
  title,
  body,
  badge,
  sizeLabel,
  details,
  disabled,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  body: string;
  badge?: string;
  sizeLabel?: string;
  details: string[];
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-labelledby={id}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        "focus-ring flex w-full items-start gap-3.5 rounded-xl bg-card p-4 text-left shadow-card transition-[box-shadow,transform,background-color] duration-150 ease-out",
        disabled ? "pointer-events-none opacity-45" : "hover:shadow-raised",
        selected && "shadow-[0_0_0_1.5px_var(--primary),0_4px_14px_-8px_color-mix(in_oklab,var(--primary)_55%,transparent)]",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full transition-colors duration-150",
          selected ? "bg-primary" : "shadow-[inset_0_0_0_1.5px_var(--line-strong)]",
        )}
      >
        {selected && <span className="h-1.5 w-1.5 rounded-full bg-primary-foreground" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span id={id} className="text-[14px] font-semibold text-foreground">
            {title}
          </span>
          {badge && (
            <span className="inline-flex h-5 items-center rounded-[5px] bg-accent-soft px-1.5 text-[11px] font-medium leading-none text-accent-text">
              {badge}
            </span>
          )}
          {sizeLabel && (
            <span className="ml-auto font-mono text-[11.5px] tabular-nums text-muted-foreground">{sizeLabel}</span>
          )}
        </span>
        <span className="mt-1 block text-xs leading-[18px] text-muted-foreground">{body}</span>
        {details.length > 0 && (
          <span className="mt-2.5 flex flex-col gap-1">
            {details.map((detail) => (
              <span key={detail} className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
                <Icon name="check" size={12} className="shrink-0 text-[color:var(--success)]" strokeWidth={2.2} />
                {detail}
              </span>
            ))}
          </span>
        )}
      </span>
    </button>
  );
}
