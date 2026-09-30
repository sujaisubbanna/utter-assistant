import { useRef } from "react";

import { cn } from "../../lib/utils";
import { Icon, type IconName } from "../icons";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: IconName;
  /** Hide the label visually (icon-only) but keep it for assistive tech. */
  iconOnly?: boolean;
}

/** A radio-group style segmented control with arrow-key navigation. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  className,
  size = "md",
  stretch,
}: {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  ariaLabel?: string;
  className?: string;
  size?: "sm" | "md";
  stretch?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);

  const onKeyDown = (event: React.KeyboardEvent) => {
    const index = options.findIndex((option) => option.value === value);
    let next = index;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % options.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp")
      next = (index - 1 + options.length) % options.length;
    else return;
    event.preventDefault();
    onChange(options[next].value);
    ref.current?.querySelectorAll<HTMLButtonElement>("[role=radio]")[next]?.focus();
  };

  return (
    <div
      ref={ref}
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md bg-wash p-0.5 shadow-[inset_0_0_0_1px_var(--line)]",
        stretch && "flex w-full",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={option.label}
            title={option.label}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(option.value)}
            className={cn(
              "focus-ring inline-flex items-center justify-center gap-1.5 rounded-[5px] font-medium transition-[background-color,color,box-shadow] duration-150 ease-out",
              size === "sm" ? "h-6 px-2 text-[11px]" : "h-7 px-2.5 text-xs",
              option.iconOnly && (size === "sm" ? "w-7 px-0" : "w-8 px-0"),
              stretch && "flex-1",
              active
                ? "bg-card text-foreground shadow-raised"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.icon && <Icon name={option.icon} size={size === "sm" ? 13 : 14} />}
            {!option.iconOnly && option.label}
          </button>
        );
      })}
    </div>
  );
}
