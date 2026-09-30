import { cn } from "../../lib/utils";

export function Switch({
  checked,
  onCheckedChange,
  disabled,
  ariaLabel,
  id,
}: {
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  disabled?: boolean;
  ariaLabel?: string;
  id?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "focus-ring relative inline-flex h-5 w-[34px] shrink-0 items-center rounded-full transition-[background-color,box-shadow] duration-150 ease-out",
        checked
          ? "bg-primary shadow-[inset_0_0_0_1px_rgb(0_0_0/0.06)]"
          : "bg-[color-mix(in_oklab,var(--foreground)_16%,transparent)] hover:bg-[color-mix(in_oklab,var(--foreground)_22%,transparent)]",
        disabled && "pointer-events-none opacity-45",
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.25),0_0_0_0.5px_rgb(0_0_0/0.06)] transition-transform duration-150 ease-out",
          checked ? "translate-x-4" : "translate-x-0.5",
        )}
      />
    </button>
  );
}
