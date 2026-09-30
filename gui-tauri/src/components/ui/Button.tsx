import type { ButtonHTMLAttributes, ReactNode } from "react";

import { openLink } from "../../lib/links";
import { cn } from "../../lib/utils";
import { Icon, type IconName } from "../icons";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "outline" | "link";
type Size = "sm" | "md" | "icon" | "icon-sm";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: IconName;
  iconRight?: IconName;
  children?: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-primary text-primary-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.16),0_1px_2px_rgb(0_0_0/0.18)] hover:brightness-[1.07] active:brightness-[0.97]",
  secondary: "bg-card text-foreground shadow-raised hover:bg-[color-mix(in_oklab,var(--card)_92%,var(--foreground))]",
  outline: "text-foreground shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-wash",
  ghost: "text-muted-foreground hover:bg-wash hover:text-foreground",
  danger:
    "bg-destructive text-destructive-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.14),0_1px_2px_rgb(0_0_0/0.18)] hover:brightness-[1.06]",
  link: "text-accent-text hover:bg-accent-soft",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 gap-1.5 px-2.5 text-xs",
  md: "h-8 gap-1.5 px-3 text-[13px]",
  icon: "h-8 w-8",
  "icon-sm": "h-7 w-7",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  iconRight,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  const iconSize = size === "sm" || size === "icon-sm" ? 14 : 15;
  return (
    <button
      type={type}
      className={cn(
        "focus-ring inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-md font-medium transition-[background-color,color,box-shadow,filter,transform] duration-150 ease-out active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner size={iconSize} /> : icon ? <Icon name={icon} size={iconSize} /> : null}
      {children}
      {iconRight && !loading && <Icon name={iconRight} size={iconSize - 2} className="opacity-70" />}
    </button>
  );
}

/** An external project/repo link, opened in the default browser. */
export function LinkButton({
  href,
  children,
  size = "sm",
  variant = "link",
  className,
}: {
  href: string;
  children: ReactNode;
  size?: Size;
  variant?: Variant;
  className?: string;
}) {
  return (
    <Button
      size={size}
      variant={variant}
      iconRight="external"
      className={className}
      title={href}
      onClick={() => openLink(href)}
    >
      {children}
    </Button>
  );
}
