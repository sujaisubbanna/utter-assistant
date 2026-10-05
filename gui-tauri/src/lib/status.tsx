import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useI18n } from "../i18n";
import { api } from "./api";
import { humanizeError } from "./errors";
import { usePoll } from "./hooks";
import type { StatusReport } from "./types";
import { sameJson } from "./utils";

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
  const { t } = useI18n();
  const [status, setStatus] = useState<StatusReport | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      const report = await api.status();
      // The CLI's error is a raw socket path + shell hint; show the friendly
      // version everywhere the report is rendered (titlebar, hero, plugins).
      const next = report?.error ? { ...report, error: humanizeError(report.error, t) } : report;
      // Keep the previous object when the report is unchanged so an idle poll
      // does not re-render every status consumer (titlebar, General hero).
      setStatus((prev) => (sameJson(prev, next) ? prev : next));
    } catch (error) {
      setStatus({ ok: false, connected: false, error: humanizeError(error, t) });
    } finally {
      setLoading(false);
    }
  }, [t]);

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
