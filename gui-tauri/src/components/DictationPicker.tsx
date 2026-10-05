import { useCallback, useEffect, useRef, useState } from "react";

import { useT } from "../i18n";
import { api } from "../lib/api";
import type { PendingDictation, WindowInfo } from "../lib/types";
import { cn, sameJson } from "../lib/utils";
import { Icon } from "./icons";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Modal } from "./ui/Modal";
import { Skeleton } from "./ui/Skeleton";
import { useToast } from "./ui/Toast";

/** How often to check for a dictation that needs a destination. */
const POLL_MS = 2000;

type Action = "deliver" | "copy" | "dismiss";

/**
 * A global, app-wide picker for a dictation that couldn't be delivered because
 * no text field was focused. It polls `dictation_pending` and, when a record
 * appears, lets the user type the transcript into an open window, copy it, or
 * dismiss it. Rendered at the Shell level so it appears on any page.
 */
export function DictationPicker() {
  const t = useT();
  const toast = useToast();

  const [pending, setPending] = useState<PendingDictation | null>(null);
  const [windows, setWindows] = useState<WindowInfo[] | null>(null);
  const [windowsError, setWindowsError] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // The `ts` of a record we've already resolved locally: the backend may lag a
  // beat behind, and we don't want the modal to flash back open.
  const resolvedTs = useRef<number | null>(null);

  // Poll for a pending dictation. A sparse engine (no Python yet) just keeps
  // the current state — the picker silently does nothing.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const record = await api.dictationPending();
        if (cancelled) return;
        if (!record) {
          resolvedTs.current = null;
          setPending((current) => (current ? null : current));
          return;
        }
        if (resolvedTs.current === record.ts) return;
        setPending((current) => (sameJson(current, record) ? current : record));
      } catch {
        /* engine missing or a transient failure: leave the picker as-is */
      }
    };
    void tick();
    const id = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const pendingTs = pending?.ts ?? null;

  // When a new record appears, load the open windows and preselect the focused
  // one (the most likely destination).
  const loadWindows = useCallback(async () => {
    setWindows(null);
    setWindowsError(false);
    try {
      const list = await api.contextWindows();
      setWindows(list);
      setSelected((current) => {
        if (current) return current;
        const focused = list.find((win) => win.focused);
        return focused ? String(focused.id) : current;
      });
    } catch {
      setWindows([]);
      setWindowsError(true);
    }
  }, []);

  useEffect(() => {
    if (pendingTs === null) return;
    setSelected(null);
    setActionError(null);
    void loadWindows();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only for a new record
  }, [pendingTs, loadWindows]);

  const closeLocally = useCallback((ts: number) => {
    resolvedTs.current = ts;
    setPending(null);
  }, []);

  const dismiss = useCallback(async () => {
    const record = pending;
    if (!record) return;
    setBusy("dismiss");
    setActionError(null);
    await api.dictationDismiss().catch(() => {});
    closeLocally(record.ts);
    setBusy(null);
  }, [pending, closeLocally]);

  const deliver = useCallback(async () => {
    const record = pending;
    if (!record || !selected) return;
    setBusy("deliver");
    setActionError(null);
    try {
      const result = await api.dictationDeliver(record.text, selected);
      if (result.ok) {
        toast(t("dictation.typed"), "ok");
        closeLocally(record.ts);
      } else {
        setActionError(t("dictation.typeFailed"));
      }
    } catch {
      setActionError(t("dictation.typeFailed"));
    } finally {
      setBusy(null);
    }
  }, [pending, selected, toast, t, closeLocally]);

  const copy = useCallback(async () => {
    const record = pending;
    if (!record) return;
    setBusy("copy");
    setActionError(null);
    try {
      await navigator.clipboard.writeText(record.text);
    } catch {
      setActionError(t("dictation.copyFailed"));
      setBusy(null);
      return;
    }
    toast(t("common.copied"), "ok");
    // The text is safely on the clipboard, so clear the pending record too —
    // otherwise the poll would reopen the picker a moment later.
    await api.dictationDismiss().catch(() => {});
    closeLocally(record.ts);
    setBusy(null);
  }, [pending, toast, t, closeLocally]);

  const hasWindows = windows !== null && windows.length > 0;

  return (
    <Modal
      open={pending !== null}
      onClose={() => void dismiss()}
      title={t("dictation.title")}
      description={t("dictation.description")}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={() => void dismiss()} loading={busy === "dismiss"}>
            {t("dictation.dismiss")}
          </Button>
          <Button variant="secondary" icon="copy" onClick={() => void copy()} loading={busy === "copy"}>
            {t("common.copy")}
          </Button>
          <Button
            variant="primary"
            icon="keyboard"
            onClick={() => void deliver()}
            loading={busy === "deliver"}
            disabled={!selected}
          >
            {t("dictation.typeSelected")}
          </Button>
        </>
      }
    >
      {pending && (
        <div className="space-y-4 pt-1">
          <div>
            <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {t("dictation.transcriptLabel")}
            </div>
            <p className="max-h-28 overflow-y-auto whitespace-pre-wrap rounded-lg bg-wash px-3 py-2 text-[13px] leading-snug text-foreground [overflow-wrap:anywhere]">
              {pending.text}
            </p>
          </div>

          <div>
            <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {t("dictation.windowsLabel")}
            </div>

            {windowsError ? (
              <div className="flex items-center gap-3 rounded-lg bg-wash px-3 py-2.5">
                <Icon name="alert" size={15} className="shrink-0 text-[color:var(--warning)]" />
                <span className="min-w-0 flex-1 text-xs text-muted-foreground">
                  {t("dictation.windowsError")}
                </span>
                <Button size="sm" icon="refresh" onClick={() => void loadWindows()}>
                  {t("common.retry")}
                </Button>
              </div>
            ) : windows === null ? (
              <div className="space-y-1" aria-busy="true">
                <Skeleton className="h-10 w-full rounded-lg" />
                <Skeleton className="h-10 w-full rounded-lg" />
              </div>
            ) : windows.length === 0 ? (
              <div className="flex items-start gap-2.5 rounded-lg bg-wash px-3 py-2.5">
                <Icon name="info" size={15} className="mt-0.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 text-xs text-muted-foreground">
                  {t("dictation.noWindows")}
                </span>
              </div>
            ) : (
              <ul className="max-h-60 space-y-0.5 overflow-y-auto">
                {windows.map((win) => {
                  const key = String(win.id);
                  const active = selected === key;
                  const label = win.app_id || t("dictation.unknownApp");
                  return (
                    <li key={key}>
                      <button
                        type="button"
                        onClick={() => setSelected(key)}
                        aria-pressed={active}
                        className={cn(
                          "focus-ring flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
                          active ? "bg-accent-soft" : "hover:bg-wash",
                        )}
                      >
                        <Icon
                          name="window"
                          size={15}
                          className={active ? "shrink-0 text-accent-text" : "shrink-0 text-muted-foreground"}
                        />
                        <span
                          className={cn(
                            "min-w-0 flex-1 truncate text-[13px]",
                            active ? "font-medium text-foreground" : "text-foreground",
                          )}
                        >
                          {label}
                          {win.title ? ` — ${win.title}` : ""}
                        </span>
                        {win.focused && <Badge tone="accent">{t("dictation.focused")}</Badge>}
                        {active && <Icon name="check" size={15} className="shrink-0 text-accent-text" />}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {actionError && (
            <div className="flex items-start gap-2.5 rounded-lg bg-[color-mix(in_oklab,var(--destructive)_7%,transparent)] px-3 py-2.5">
              <Icon name="alert" size={15} className="mt-0.5 shrink-0 text-[color:var(--destructive)]" />
              <span className="min-w-0 flex-1 text-xs text-foreground">{actionError}</span>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
