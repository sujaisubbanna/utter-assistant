import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";

import { cn } from "../../lib/utils";
import { Icon, type IconName } from "../icons";
import { Button } from "./Button";

export interface MenuItem {
  label?: string;
  icon?: IconName;
  onSelect?: () => void;
  disabled?: boolean;
  separator?: boolean;
  danger?: boolean;
}

/**
 * A small overflow menu. The list is rendered in a portal and positioned with
 * `position: fixed`, so it is never clipped by a scrolling panel's
 * `overflow: hidden` — and it flips above the button when there is no room
 * below. Keyboard and outside-click handling are unchanged.
 */
export function Menu({
  items,
  label,
  icon = "more",
  align = "right",
}: {
  items: MenuItem[];
  label: string;
  icon?: IconName;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<CSSProperties>({ visibility: "hidden" });
  const anchorRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const menuItems = useCallback(
    () => Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]:not(:disabled)") ?? []),
    [],
  );

  // Measure the rendered menu, then place it under (or above) the button,
  // clamped to the viewport so no edge can clip it.
  useLayoutEffect(() => {
    if (!open) return;
    const anchor = anchorRef.current?.getBoundingClientRect();
    const menu = menuRef.current;
    if (!anchor || !menu) return;
    const margin = 8;
    const { width, height } = menu.getBoundingClientRect();
    let left = align === "right" ? anchor.right - width : anchor.left;
    left = Math.min(Math.max(margin, left), window.innerWidth - width - margin);
    const below = anchor.bottom + 4;
    const above = anchor.top - height - 4;
    const top = below + height + margin > window.innerHeight && above > margin ? above : below;
    setStyle({ position: "fixed", top, left });
  }, [open, align]);

  useEffect(() => {
    if (!open) return;
    menuItems()[0]?.focus({ preventScroll: true });
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (anchorRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        anchorRef.current?.querySelector<HTMLButtonElement>("[aria-haspopup]")?.focus({ preventScroll: true });
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      const list = menuItems();
      const index = list.indexOf(document.activeElement as HTMLButtonElement);
      const next =
        event.key === "ArrowDown" ? (index + 1) % list.length : (index - 1 + list.length) % list.length;
      list[next]?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    // A fixed menu would drift on scroll/resize, so dismiss it instead.
    const onReflow = () => setOpen(false);
    window.addEventListener("resize", onReflow);
    window.addEventListener("scroll", onReflow, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onReflow);
      window.removeEventListener("scroll", onReflow, true);
    };
  }, [open, menuItems]);

  return (
    <div ref={anchorRef} className="relative">
      <Button
        size="icon-sm"
        variant="ghost"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={label}
        onClick={() => {
          setStyle({ visibility: "hidden" });
          setOpen((value) => !value);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <Icon name={icon} size={16} />
      </Button>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-label={label}
            style={style}
            className={cn(
              "animate-pop z-50 min-w-[11rem] rounded-lg bg-popover p-1 shadow-pop",
              align === "right" ? "origin-top-right" : "origin-top-left",
            )}
          >
            {items.map((item, index) =>
              item.separator ? (
                <div key={index} className="mx-1 my-1 h-px bg-line" />
              ) : (
                <button
                  key={index}
                  type="button"
                  role="menuitem"
                  disabled={item.disabled}
                  onClick={() => {
                    setOpen(false);
                    item.onSelect?.();
                  }}
                  className={cn(
                    "flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-left text-[13px] outline-none transition-colors duration-100 hover:bg-wash-strong focus-visible:bg-wash-strong disabled:pointer-events-none disabled:opacity-40",
                    item.danger ? "text-[color:var(--destructive)]" : "text-foreground",
                  )}
                >
                  {item.icon && <Icon name={item.icon} size={14} className="text-muted-foreground" />}
                  {item.label}
                </button>
              ),
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
