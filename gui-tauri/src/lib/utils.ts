export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/**
 * Compare two small API payloads for equality. Used by polls to skip the state
 * update (and the re-render it triggers) when a check returns the same data.
 * JSON is fine here: these are small, plain objects with stable key order.
 */
export function sameJson(a: unknown, b: unknown): boolean {
  return a === b || JSON.stringify(a) === JSON.stringify(b);
}
