/**
 * The Utter mark: a "u" drawn as two swooping strokes. The left half sweeps
 * round into a tapered tail, the right half swoops past it, and the crescent
 * left between them reads as a speech tail — two halves meeting in a word.
 * Source SVGs live in src/assets/ (mark, wordmark lockup, app tile).
 */
export function Logo({
  size = 18,
  className,
  title,
}: {
  size?: number;
  className?: string;
  title?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 -6.25 100 100"
      fill="currentColor"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      <path d="M6 19.5A12.5 12.5 0 0 1 31 19.5V44C31 55 38 62.5 48 62.5C51.5 62.5 55 62.0 58.5 60.8C54.0 68.5 45.3 74.5 36.8 77.5C20 75.5 6 64 6 46Z" />
      <path d="M69 19.5A12.5 12.5 0 0 1 94 19.5V46C94 66 77 80.5 52 80.5C49 80.5 46.5 80.2 44 79.8C53.7 77 59.7 71.5 63.7 65.5C66 59 69 53 69 46Z" opacity={0.86} />
    </svg>
  );
}

/** App tile: the yellow mark on a graphite squircle, matching the app icon. */
export function LogoTile({ size = 56, className }: { size?: number; className?: string }) {
  return (
    <span
      className={className}
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.26,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--primary)",
        background:
          "radial-gradient(70% 60% at 50% 40%, color-mix(in oklab, var(--primary) 20%, transparent), transparent), linear-gradient(180deg, #2b2b2b, #121212)",
        boxShadow:
          "inset 0 0 0 1px rgb(255 255 255 / 0.08), 0 10px 28px -10px color-mix(in oklab, var(--primary) 45%, transparent)",
      }}
    >
      <Logo size={size * 0.64} />
    </span>
  );
}
