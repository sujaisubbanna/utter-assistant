import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import type { InferenceStatus } from "./types";

/**
 * Read the provisioning state of the sharded vision + planner models.
 *
 * These are installed outside the normal model store, so the Models page can't
 * see them with `models list`; `assistant inference status --json` is the
 * source of truth. A failed probe leaves `status` null (unknown), which callers
 * treat as "offer the download" rather than "ready".
 */
export function useInferenceStatus(): {
  status: InferenceStatus | null;
  loading: boolean;
  refresh: () => Promise<void>;
} {
  const [status, setStatus] = useState<InferenceStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await api.inferenceStatus());
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { status, loading, refresh };
}

/** True only when both halves of the sharded set are present. */
export function inferenceReady(status: InferenceStatus | null): boolean {
  return Boolean(status?.vision && status?.planner);
}
