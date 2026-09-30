import { cn } from "../../lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("shimmer rounded-[5px]", className)} />;
}

/** Skeleton rows that echo the shape of a loaded settings group. */
export function SkeletonRows({ count = 3, leading = true }: { count?: number; leading?: boolean }) {
  const widths = ["w-32", "w-44", "w-28", "w-40", "w-36"];
  return (
    <div aria-hidden="true" className="divide-y divide-line">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="flex min-h-[52px] items-center gap-3 px-4 py-2.5">
          {leading && <Skeleton className="h-7 w-7 rounded-md" />}
          <div className="flex-1 space-y-1.5">
            <Skeleton className={cn("h-3", widths[index % widths.length])} />
            <Skeleton className="h-2.5 w-56 max-w-[60%] opacity-70" />
          </div>
          <Skeleton className="h-7 w-20 rounded-md" />
        </div>
      ))}
    </div>
  );
}

/** A whole-page placeholder: two ghost sections. */
export function SkeletonPage({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" aria-label={label} className="space-y-8">
      {[3, 2].map((rows, index) => (
        <div key={index}>
          <Skeleton className="mb-2 h-3 w-28" />
          <Skeleton className="mb-3 h-2.5 w-64 opacity-70" />
          <div className="overflow-hidden rounded-lg bg-card shadow-card">
            <SkeletonRows count={rows} leading={false} />
          </div>
        </div>
      ))}
    </div>
  );
}
