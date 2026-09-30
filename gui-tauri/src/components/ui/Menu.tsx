import { useEffect, useRef, useState } from "react";

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
  const ref = useRef<HTMLDivElement>(null);

  const menuItems = () =>
    Array.from(ref.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]:not(:disabled)") ?? []);

  useEffect(() => {
    if (!open) return;
    menuItems()[0]?.focus();
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        ref.current?.querySelector<HTMLButtonElement>("[aria-haspopup]")?.focus();
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
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Button
        size="icon-sm"
        variant="ghost"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={label}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <Icon name={icon} size={16} />
      </Button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          className={cn(
            "animate-pop absolute z-40 mt-1 min-w-[11rem] rounded-lg bg-popover p-1 shadow-pop",
            align === "right" ? "right-0 origin-top-right" : "left-0 origin-top-left",
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
        </div>
      )}
    </div>
  );
}
