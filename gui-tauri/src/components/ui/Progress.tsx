import { cn } from "../../lib/utils";

export function Progress({
  value,
  indeterminate,
  className,
  label,
}: {
  value?: number;
  indeterminate?: boolean;
  className?: string;
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value ?? 0));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(clamped * 100)}
      className={cn("relative h-1 w-full overflow-hidden rounded-full bg-wash-strong", className)}
    >
      {indeterminate ? (
        <div className="absolute inset-y-0 w-1/3 rounded-full bg-primary animate-[lv-indet_1.2s_ease-in-out_infinite]" />
      ) : (
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-180 ease-out"
          style={{ width: `${clamped * 100}%` }}
        />
      )}
    </div>
  );
}
