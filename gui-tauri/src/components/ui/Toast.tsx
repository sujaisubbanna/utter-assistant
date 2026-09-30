import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

import { Icon, type IconName } from "../icons";

export type ToastTone = "info" | "ok" | "error" | "warn";

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

const TONE: Record<ToastTone, { icon: IconName; color: string }> = {
  info: { icon: "info", color: "var(--muted-foreground)" },
  ok: { icon: "check-circle", color: "var(--success)" },
  error: { icon: "alert", color: "var(--destructive)" },
  warn: { icon: "alert", color: "var(--warning)" },
};

const ToastContext = createContext<(message: string, tone?: ToastTone) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((message: string, tone: ToastTone = "info") => {
    const id = Date.now() + Math.random();
    setItems((current) => [...current.slice(-3), { id, message, tone }]);
    window.setTimeout(() => {
      setItems((current) => current.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[21rem] flex-col items-end gap-2"
      >
        {items.map((item) => (
          <div
            key={item.id}
            className="animate-toast pointer-events-auto flex w-full items-start gap-2.5 rounded-lg bg-popover px-3 py-2.5 shadow-pop"
          >
            <Icon
              name={TONE[item.tone].icon}
              size={15}
              className="mt-[1px] shrink-0"
              style={{ color: TONE[item.tone].color }}
            />
            <span className="text-[13px] leading-snug text-popover-foreground">{item.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
