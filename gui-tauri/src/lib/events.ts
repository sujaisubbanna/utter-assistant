import { useEffect, useRef } from "react";

/**
 * Subscribe to a Tauri event with a stable handler.
 *
 * `listen` is imported lazily so the bundle still evaluates if the app is
 * opened outside a Tauri window (e.g. a browser during UI work).
 */
export function useTauriEvent<T>(
  name: string,
  handler: (payload: T) => void,
  enabled = true,
): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    if (!enabled) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;

    import("@tauri-apps/api/event")
      .then(({ listen }) => listen<T>(name, (event) => handlerRef.current(event.payload)))
      .then((off) => {
        if (cancelled) off();
        else unlisten = off;
      })
      .catch(() => {
        /* events are optional */
      });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [name, enabled]);
}
