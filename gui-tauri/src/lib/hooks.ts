import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n } from "../i18n";
import { humanizeError } from "./errors";

interface AsyncState<T> {
  loading: boolean;
  error?: string;
  data?: T;
}

/** Run an async function, tracking loading/error data for the UI. */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[],
  immediate = true,
): AsyncState<T> & { reload: () => Promise<void> } {
  const { t } = useI18n();
  const [state, setState] = useState<AsyncState<T>>({ loading: immediate });
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true, error: undefined }));
    try {
      const data = await fnRef.current();
      setState({ loading: false, data });
    } catch (error) {
      setState({ loading: false, error: humanizeError(error, t) });
    }
  }, [t]);

  useEffect(() => {
    if (immediate) void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, reload };
}

/**
 * Poll a function while the component is mounted.
 *
 * These polls shell out (the `assistant` CLI, `systemctl`), so they are deliberately
 * gentle: nothing runs while the window is in the background, a run that is still in
 * flight is never overlapped, and the poll catches up as soon as the window becomes
 * visible again.
 */
export function usePoll(
  fn: () => void | Promise<void>,
  intervalMs: number,
  enabled = true,
): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    if (!enabled || intervalMs <= 0) return;
    let busy = false;
    const run = async () => {
      // Never overlap a run, but a skipped run must not wedge the poll: the
      // `busy` flag is always cleared in `finally`.
      if (busy) return;
      busy = true;
      try {
        await fnRef.current();
      } finally {
        busy = false;
      }
    };
    // Kick once immediately so the first value appears without waiting a full
    // interval, and so returning to the window refreshes at once.
    void run();
    const id = window.setInterval(() => void run(), intervalMs);
    // `visibilitychange` is the primary wake-up, but a macOS permission prompt
    // or System Settings pane can occlude the window without firing it reliably,
    // so also refresh whenever the window regains focus.
    const onWake = () => void run();
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("focus", onWake);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onWake);
      window.removeEventListener("focus", onWake);
    };
  }, [intervalMs, enabled]);
}

/** Debounce a callback. */
export function useDebouncedCallback<A extends unknown[]>(
  fn: (...args: A) => void,
  delayMs: number,
): (...args: A) => void {
  const timer = useRef<number | undefined>(undefined);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  return useCallback(
    (...args: A) => {
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => fnRef.current(...args), delayMs);
    },
    [delayMs],
  );
}
