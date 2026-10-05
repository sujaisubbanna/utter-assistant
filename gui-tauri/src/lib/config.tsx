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
import { humanizeError } from "./errors";
import type { Config } from "./types";
import { useToast } from "../components/ui/Toast";
import { useT } from "../i18n";

export interface ConfigApi {
  config: Config;
  loading: boolean;
  error: string | null;
  get: <T>(section: string, key: string, fallback: T) => T;
  set: (section: string, key: string, value: unknown) => Promise<void>;
  setMany: (section: string, values: Record<string, unknown>) => Promise<void>;
  reload: () => Promise<void>;
}

const ConfigContext = createContext<ConfigApi>({
  config: {},
  loading: true,
  error: null,
  get: (_section, _key, fallback) => fallback,
  set: async () => {},
  setMany: async () => {},
  reload: async () => {},
});

export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Config>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const t = useT();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const loaded = await api.getConfig();
      setConfig(loaded ?? {});
      setError(null);
    } catch (err) {
      setError(humanizeError(err, t));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const set = useCallback(
    async (section: string, key: string, value: unknown) => {
      // Optimistic: keep the UI responsive, roll back on failure.
      const previous = config;
      setConfig((current) => ({
        ...current,
        [section]: { ...(current[section] ?? {}), [key]: value },
      }));
      try {
        await api.setConfig(section, key, value);
      } catch (error) {
        setConfig(previous);
        toast(t("common.saveFailed", { what: `${section}.${key}`, error: humanizeError(error, t) }), "error");
      }
    },
    [config, toast, t],
  );

  const setMany = useCallback(
    async (section: string, values: Record<string, unknown>) => {
      const previous = config;
      setConfig((current) => ({
        ...current,
        [section]: { ...(current[section] ?? {}), ...values },
      }));
      try {
        await api.setConfigMany(section, values);
      } catch (error) {
        setConfig(previous);
        toast(t("common.saveFailed", { what: section, error: humanizeError(error, t) }), "error");
      }
    },
    [config, toast, t],
  );

  const get = useCallback(
    <T,>(section: string, key: string, fallback: T): T => {
      const group = config[section];
      const value = group ? group[key] : undefined;
      return value === undefined || value === null ? fallback : (value as T);
    },
    [config],
  );

  const value = useMemo<ConfigApi>(
    () => ({ config, loading, error, get, set, setMany, reload }),
    [config, loading, error, get, set, setMany, reload],
  );

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}

export function useConfig(): ConfigApi {
  return useContext(ConfigContext);
}
