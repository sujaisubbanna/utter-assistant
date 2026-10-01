import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api } from "./api";
import { usePoll } from "./hooks";
import type { StatusReport } from "./types";

interface StatusApi {
  status: StatusReport | null;
  connected: boolean;
  loading: boolean;
  reload: () => Promise<void>;
}

const StatusContext = createContext<StatusApi>({
  status: null,
  connected: false,
  loading: true,
  reload: async () => {},
});

/** Polls `assistant status --json` and shares the result across the shell. */
export function RunnerStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<StatusReport | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      const next = await api.status();
      setStatus(next);
    } catch (error) {
      setStatus({ ok: false, connected: false, error: String(error) });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Each check spawns the `assistant` CLI, so poll gently and pause entirely while
  // the window is in the background (usePoll also prevents overlapping runs).
  usePoll(() => reload(), 15000);

  const value = useMemo<StatusApi>(() => {
    // `runner.status` has no explicit `connected` field; a JSON reply without
    // an error means the socket answered, so the runner is up.
    const connected = Boolean(status && status.ok !== false && !status.error);
    return { status, connected, loading, reload };
  }, [status, loading, reload]);

  return <StatusContext.Provider value={value}>{children}</StatusContext.Provider>;
}

export function useRunnerStatus(): StatusApi {
  return useContext(StatusContext);
}
