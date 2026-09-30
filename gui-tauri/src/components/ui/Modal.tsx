import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useT } from "../../i18n";
import { cn } from "../../lib/utils";
import { Icon } from "../icons";
import { Button } from "./Button";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  const t = useT();
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = dialogRef.current;
    // Focus the first control after the close button, else the dialog itself.
    const focusables = node ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)) : [];
    (focusables[1] ?? focusables[0] ?? node)?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  const width = size === "sm" ? "max-w-[380px]" : size === "lg" ? "max-w-2xl" : "max-w-[460px]";

  // Portal to <body>: animated (transformed) page wrappers would otherwise
  // become the containing block and pin the dialog inside the scroll area.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
      <div
        className="animate-fade absolute inset-0 bg-[rgb(10_10_14/0.42)] backdrop-blur-[3px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cn(
          "animate-dialog relative z-10 flex max-h-[85vh] w-full flex-col rounded-xl bg-popover shadow-pop outline-none",
          width,
        )}
      >
        <header className="flex items-start justify-between gap-4 px-5 pb-2 pt-4">
          <div className="min-w-0 pt-0.5">
            <h2 id={titleId} className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">
              {title}
            </h2>
            {description && (
              <p id={descId} className="mt-1 text-xs text-muted-foreground">
                {description}
              </p>
            )}
          </div>
          <Button size="icon-sm" variant="ghost" onClick={onClose} aria-label={t("common.close")}>
            <Icon name="x" size={15} />
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-1 text-[13px]">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 rounded-b-xl border-t border-line bg-wash px-5 py-3">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}
